"""The discovery trace — the raw record of a successful run.

This is the intermediate between discovery and compile: the agent produces it;
the compiler distills it into a Capability artifact. It is deliberately richer
than the artifact (it keeps the per-step observation + which strategies worked)
so the compiler has everything it needs.
"""
from pydantic import BaseModel, Field

from cua.schema import Action, LocatorStrategy


class TraceStep(BaseModel):
    index: int
    action: Action
    strategies: list[LocatorStrategy] = Field(
        default_factory=list, description="Locator strategies that resolved the target (for the compiler)."
    )
    url_before: str
    url_after: str
    observation: str | None = Field(default=None, description="Accessibility tree at decision time.")
    read_value: str | None = None
    note: str | None = None


class DiscoveryTrace(BaseModel):
    run_id: str | None = Field(default=None, description="Discovery run id (links to its evidence).")
    evidence_ref: str | None = Field(default=None, description="Path to this run's redacted JSONL log.")
    goal: str
    app: str | None = None
    model: str | None = Field(default=None, description="Model that produced this trace (for provenance).")
    start_url: str
    inputs: dict[str, str] = Field(default_factory=dict, description="Concrete input values used during discovery.")
    steps: list[TraceStep] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict, description="Values captured by read actions.")
    success: bool = False
