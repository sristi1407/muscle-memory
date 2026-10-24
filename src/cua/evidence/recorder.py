"""Evidence store — a black-box recorder for every discovery and replay run.

Each run gets its own folder:

    <root>/<kind>-<run_id>/
        run.jsonl      one JSON event per line: what we saw, what we decided, what we
                       did, and why — in order
        step-NN.png    screenshot after each step (PII masked in the page first)
        failure.json   on failure only: URL, title, accessibility tree, expected vs.
                       observed — the "richer signal" for debugging
        summary.json   final status + outputs + file index

Every string is passed through the Redactor before it is written. That is a second
line of defence behind redaction at the surface: even if something sensitive slips
into an error message or a typed value, it never lands on disk.

Evidence must never break a run, so capture failures are logged, not raised.
"""
import json
import os
import uuid
from datetime import datetime, timezone

from cua.policy import Redactor
from cua.schema import Evidence


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EvidenceRecorder:
    def __init__(self, root: str, kind: str, run_id: str | None = None,
                 redactor: Redactor | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.dir = os.path.join(root, f"{kind}-{self.run_id}")
        os.makedirs(self.dir, exist_ok=True)
        self.redactor = redactor if redactor is not None else Redactor()
        self.log_path = os.path.join(self.dir, "run.jsonl")
        self.screenshots: list[str] = []
        self._seq = 0

    def event(self, event: str, **fields) -> None:
        self._seq += 1
        record = {"seq": self._seq, "ts": _now(), "event": event, **fields}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(self._scrub(record)) + "\n")

    def screenshot(self, surface, name: str) -> str | None:
        path = os.path.join(self.dir, f"{name}.png")
        try:
            surface.screenshot(path)  # the surface masks PII in the DOM before capturing
        except Exception as e:  # noqa: BLE001
            self.event("screenshot_failed", name=name, error=str(e))
            return None
        self.screenshots.append(path)
        self.event("screenshot", path=path)
        return path

    def failure_snapshot(self, surface, **detail) -> str:
        """Pixels + what the accessibility tree said at the moment of failure."""
        snap = {"screenshot": self.screenshot(surface, "failure"), **detail}
        try:
            perc = surface.observe()  # already redacted at the source
            snap.update(url=perc.url, title=perc.title, accessibility_tree=perc.tree)
        except Exception as e:  # noqa: BLE001
            snap["observe_error"] = str(e)
        path = os.path.join(self.dir, "failure.json")
        with open(path, "w") as f:
            json.dump(self._scrub(snap), f, indent=2)
        self.event("failure_snapshot", path=path)
        return path

    def attach(self, name: str, data) -> str:
        """Save a named JSON document next to the log (e.g. an intervention request)."""
        path = os.path.join(self.dir, f"{name}.json")
        with open(path, "w") as f:
            json.dump(self._scrub(data), f, indent=2)
        self.event("attachment", name=name, path=path)
        return path

    def finish(self, **summary) -> Evidence:
        self.event("run_end", **summary)
        data = {"run_id": self.run_id, "log": self.log_path,
                "screenshots": self.screenshots, **summary}
        with open(os.path.join(self.dir, "summary.json"), "w") as f:
            json.dump(self._scrub(data), f, indent=2)
        return Evidence(log_ref=self.log_path, screenshots=list(self.screenshots))

    def _scrub(self, value):
        # Round-trip through JSON first so enums/models become plain strings we can redact.
        return self._redact(json.loads(json.dumps(value, default=str)))

    def _redact(self, value):
        if isinstance(value, str):
            return self.redactor.redact(value)
        if isinstance(value, dict):
            return {k: self._redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact(v) for v in value]
        return value


class NullRecorder:
    """Drop-in no-op so the agent and engine behave exactly as before when evidence is off."""

    run_id = None
    log_path = None

    def event(self, *args, **kwargs) -> None:
        return None

    def screenshot(self, *args, **kwargs) -> None:
        return None

    def failure_snapshot(self, *args, **kwargs) -> None:
        return None

    def attach(self, *args, **kwargs) -> None:
        return None

    def finish(self, **kwargs) -> None:
        return None
