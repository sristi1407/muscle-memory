"""P2 — the compiler: a successful DiscoveryTrace -> a reusable CapabilityArtifact.

The trace is a concrete recording ("typed 12345, read $4,210.55"). Compiling turns
it into a *capability*:
  * literal values that match a declared input become ``{param: ...}`` bindings,
    so one recording replays for any input (and sensitive values never freeze in);
  * read steps anchor on the stable **label**, so replay reads the right cell for
    any member;
  * the resilient locator strategies captured during discovery are baked into each
    step's Target.

Error rules (the business/recoverable/hard taxonomy) are added in P4 — a successful
trace never exercises the failure paths, so we don't invent them here.
"""
import uuid
from urllib.parse import urlparse

from cua.agent.trace import DiscoveryTrace, TraceStep
from cua.schema import (
    ActionType,
    CapabilityArtifact,
    Contract,
    Expect,
    LiteralValue,
    Metadata,
    OutputSpec,
    ParamSpec,
    ParamValue,
    Policy,
    Provenance,
    Step,
    Surface,
    Target,
    TextPresent,
    TextStrategy,
)


def _value_source(text: str | None, inputs: dict[str, str]):
    """Literal typed text -> a param binding when it matches a declared input."""
    for name, value in inputs.items():
        if text is not None and value == text:
            return ParamValue(param=name)
    return LiteralValue(value=text or "")


def _target(description: str, strategies, expect: Expect | None = None) -> Target:
    return Target(description=description, strategies=list(strategies), expect=expect)


def _read_label(ts: TraceStep) -> str:
    """The stable label a read step anchors on (recorded by the surface as a TextStrategy)."""
    for s in ts.strategies:
        if isinstance(s, TextStrategy):
            return s.text
    return ts.action.target or ""


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:48]


def compile_trace(
    trace: DiscoveryTrace,
    *,
    capability_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    version: str = "1.0.0",
    run_id: str | None = None,
) -> CapabilityArtifact:
    steps: list[Step] = []
    for ts in trace.steps:
        a = ts.action
        if a.action == ActionType.NAVIGATE:
            steps.append(Step(id=f"step{ts.index}_navigate", index=ts.index,
                              action=ActionType.NAVIGATE, url=a.url))
        elif a.action in (ActionType.TYPE, ActionType.SELECT):
            steps.append(Step(
                id=f"step{ts.index}_{a.action.value}", index=ts.index, action=a.action,
                target=_target(a.target or "", ts.strategies,
                               expect=Expect(editable=True) if a.action == ActionType.TYPE else None),
                value=_value_source(a.text, trace.inputs),
            ))
        elif a.action == ActionType.CLICK:
            steps.append(Step(
                id=f"step{ts.index}_click", index=ts.index, action=ActionType.CLICK,
                target=_target(a.target or "", ts.strategies),
            ))
        elif a.action == ActionType.READ:
            label = _read_label(ts)
            strategies = ts.strategies or [TextStrategy(text=label, exact=True)]
            steps.append(Step(
                id=f"step{ts.index}_read", index=ts.index, action=ActionType.READ,
                target=_target(label, strategies, expect=Expect(text_contains=label) if label else None),
                output=a.output_key,
            ))

    read_labels = [_read_label(ts) for ts in trace.steps if ts.action.action == ActionType.READ]
    contract = Contract(
        inputs=[ParamSpec(name=k) for k in trace.inputs],
        outputs=[OutputSpec(name=k) for k in trace.outputs],
        success=TextPresent(
            text=read_labels[0] if read_labels else "",
            description="Reached the screen showing the requested value.",
        ),
    )

    host = urlparse(trace.start_url).hostname or ""
    routes: list[str] = []
    for ts in trace.steps:
        for u in (ts.url_before, ts.url_after):
            path = urlparse(u).path
            if path and path not in routes:
                routes.append(path)

    return CapabilityArtifact(
        id=capability_id or _slug(trace.goal),
        version=version,
        name=name or trace.goal,
        description=description or trace.goal,
        metadata=Metadata(app=trace.app or "unknown", surface=Surface.WEB_LEGACY),
        contract=contract,
        steps=steps,
        policy=Policy(allowlist_domains=[host] if host else [], allowlist_routes=routes),
        provenance=Provenance(
            discovery_run_id=run_id or uuid.uuid4().hex[:8],
            model=trace.model or "unknown",
        ),
    )
