"""The control seam: exactly one party drives the live session at a time.

    AUTOMATION --hand_off--> AWAITING_HUMAN --claim--> HUMAN --resolve--> AUTOMATION
                                   |                     |                    ^
                                   +-- claim timeout ----+--- idle timeout ---+   (resolution: abort)

* The replay engine only acts while it holds control (``assert_automation``).
* Operator commands are only accepted from the operator who claimed the request.
* Every page operation still runs on the engine's thread. The operator side (the
  console's HTTP thread) only *enqueues* commands and ``hand_off`` executes them in
  order: a browser session is not thread-safe, so there is exactly one writer.
* Every operator action is recorded (typed secrets masked), so the evidence trail
  covers the handoff with no gap.
"""
import queue
import threading
import time
from datetime import datetime, timezone

from cua.schema import (
    Controller,
    HumanAction,
    InterventionRequest,
    RequestStatus,
    Resolution,
)

OPERATOR_KEYS = {"Enter", "Tab", "Backspace", "Escape"}
MAX_TYPED_CHARS = 500


class ControlError(RuntimeError):
    """Someone tried to act without holding control, or made a decision they can't make."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ControlChannel:
    def __init__(self, claim_timeout_s: float = 600, idle_timeout_s: float = 900,
                 frame_interval_s: float = 1.0):
        self.claim_timeout_s = claim_timeout_s    # nobody took over -> abort, never hang
        self.idle_timeout_s = idle_timeout_s      # operator walked away -> abort
        self.frame_interval_s = frame_interval_s  # how often the console's live view refreshes
        self.controller = Controller.AUTOMATION
        self.request: InterventionRequest | None = None
        self.history: list[InterventionRequest] = []
        self.latest_frame: bytes | None = None
        self._lock = threading.Lock()
        self._commands: queue.Queue = queue.Queue()

    # ------------------------------------------------------------------ #
    # Automation side — called on the engine's thread.                    #
    # ------------------------------------------------------------------ #
    def assert_automation(self) -> None:
        if self.controller != Controller.AUTOMATION:
            raise ControlError(f"automation tried to act while '{self.controller.value}' holds control")

    def hand_off(self, req: InterventionRequest, surface, rec) -> InterventionRequest:
        """Pause automation, give the live session to a human, block until they decide."""
        with self._lock:
            self.assert_automation()
            self._drain()  # drop anything left over from an earlier handoff
            self.request = req
            self.controller = Controller.AWAITING_HUMAN
        rec.event("control_change", controller=Controller.AWAITING_HUMAN.value, request_id=req.id,
                  kind=req.kind.value, reason=req.reason)
        rec.attach(f"intervention-{req.id}-open", req.model_dump(mode="json"))
        self._refresh(surface)

        opened = last_activity = last_frame = time.monotonic()
        resolution, note, operator = None, None, None
        while resolution is None:
            try:
                cmd = self._commands.get(timeout=0.25)
            except queue.Empty:
                cmd = None
            now = time.monotonic()

            if cmd is not None:
                last_activity = now
                if cmd["kind"] == "claimed":
                    rec.event("control_change", controller=Controller.HUMAN.value,
                              request_id=req.id, operator=cmd["operator"])
                    rec.screenshot(surface, f"intervention-{req.id}-claimed")
                elif cmd["kind"] == "resolve":
                    resolution, note, operator = cmd["resolution"], cmd.get("note"), cmd["operator"]
                else:
                    self._execute(cmd, req, surface, rec)
                    self._refresh(surface)
                    last_frame = now
                continue

            if self.controller == Controller.AWAITING_HUMAN and now - opened > self.claim_timeout_s:
                resolution = Resolution.ABORT
                note = f"timed out: no operator took control within {self.claim_timeout_s:.0f}s"
            elif self.controller == Controller.HUMAN and now - last_activity > self.idle_timeout_s:
                resolution, operator = Resolution.ABORT, req.operator
                note = f"timed out: operator idle for {self.idle_timeout_s:.0f}s"
            elif now - last_frame >= self.frame_interval_s:
                self._refresh(surface)
                last_frame = now

        with self._lock:
            req.status = RequestStatus.RESOLVED
            req.resolution = resolution
            req.note = note
            req.resolved_at = _now()
            if operator:
                req.operator = operator
            self.history.append(req)
            self.request = None
            self.controller = Controller.AUTOMATION  # hand control back
        rec.screenshot(surface, f"intervention-{req.id}-resolved")
        rec.event("control_change", controller=Controller.AUTOMATION.value, request_id=req.id,
                  resolution=resolution.value, note=note, operator=req.operator,
                  human_actions=len(req.actions))
        rec.attach(f"intervention-{req.id}-resolved", req.model_dump(mode="json"))
        return req

    # ------------------------------------------------------------------ #
    # Operator side — called from the console's HTTP thread.              #
    # ------------------------------------------------------------------ #
    def claim(self, operator: str) -> None:
        operator = (operator or "").strip()
        if not operator:
            raise ControlError("an operator name is required")
        with self._lock:
            if self.request is None or self.controller != Controller.AWAITING_HUMAN:
                raise ControlError("there is no open request to take over")
            self.request.status = RequestStatus.CLAIMED
            self.request.operator = operator
            self.controller = Controller.HUMAN
        self._commands.put({"kind": "claimed", "operator": operator})

    def command(self, operator: str, cmd: dict) -> None:
        cmd = self._validate(cmd)
        with self._lock:
            self._require_holder(operator)
        self._commands.put({**cmd, "operator": operator})

    @staticmethod
    def _validate(cmd: dict) -> dict:
        """Accept only the small, known command set; reject anything malformed."""
        kind = cmd.get("kind")
        try:
            if kind == "click":
                return {"kind": kind, "x": float(cmd["x"]), "y": float(cmd["y"])}
            if kind == "click_name":
                return {"kind": kind, "name": str(cmd["name"])}
        except (KeyError, TypeError, ValueError):
            raise ControlError(f"malformed '{kind}' command") from None
        if kind == "type":
            text = str(cmd.get("text", ""))
            if not text or len(text) > MAX_TYPED_CHARS:
                raise ControlError(f"type needs 1-{MAX_TYPED_CHARS} characters")
            return {"kind": kind, "text": text}
        if kind == "key":
            if cmd.get("key") not in OPERATOR_KEYS:
                raise ControlError(f"key must be one of {sorted(OPERATOR_KEYS)}")
            return {"kind": kind, "key": cmd["key"]}
        raise ControlError(f"unknown command '{kind}'")

    def resolve(self, operator: str, resolution: str, note: str | None = None) -> None:
        try:
            res = Resolution(resolution)
        except ValueError:
            raise ControlError(f"unknown decision '{resolution}'") from None
        with self._lock:
            self._require_holder(operator)
            if res not in self.request.allowed:
                raise ControlError(f"'{res.value}' is not allowed here; choose one of "
                                   f"{[r.value for r in self.request.allowed]}")
        self._commands.put({"kind": "resolve", "operator": operator, "resolution": res,
                            "note": (note or "").strip() or None})

    def state(self) -> dict:
        with self._lock:
            return {
                "controller": self.controller.value,
                "request": self.request.model_dump(mode="json") if self.request else None,
                "history": [r.model_dump(mode="json") for r in self.history[-5:]],
            }

    # ------------------------------------------------------------------ #
    def _require_holder(self, operator: str) -> None:
        if self.controller != Controller.HUMAN or self.request is None:
            raise ControlError("take control first")
        if self.request.operator != operator:
            raise ControlError(f"control is held by '{self.request.operator}'")

    def _execute(self, cmd: dict, req: InterventionRequest, surface, rec) -> None:
        url_before = surface.current_url()
        kind = cmd["kind"]
        try:
            if kind == "click":
                detail = f"click at ({cmd['x']:.0f}, {cmd['y']:.0f})"
                surface.click_at(cmd["x"], cmd["y"])
            elif kind == "click_name":
                detail = f"click '{cmd['name']}'"
                surface.do_click(cmd["name"])
            elif kind == "type":
                # Decide BEFORE typing what may be recorded: secrets are never written down.
                detail = "type [REDACTED:secret]" if surface.focus_is_secret() else f"type {cmd['text']!r}"
                surface.type_text(cmd["text"])
            else:
                detail = f"press {cmd['key']}"
                surface.press_key(cmd["key"])
            surface.settle()
        except Exception as e:  # noqa: BLE001 - a bad click must not end the handoff
            detail += f" -> ERROR: {e}"

        with self._lock:
            action = HumanAction(seq=len(req.actions) + 1, ts=_now(), operator=cmd["operator"],
                                 kind=kind, detail=detail, url_before=url_before,
                                 url_after=surface.current_url())
            req.actions.append(action)
        rec.event("human_action", request_id=req.id, **action.model_dump(mode="json"))

    def observe(self, surface) -> None:
        """Update the console's live view (the engine calls this after each step it runs)."""
        self._refresh(surface)

    def _refresh(self, surface) -> None:
        try:
            self.latest_frame = surface.frame()
        except Exception:  # noqa: BLE001 - a missed frame only makes the live view stale
            pass

    def _drain(self) -> None:
        while not self._commands.empty():
            self._commands.get_nowait()

