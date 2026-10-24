"""The human-in-the-loop contract: what an operator is handed when automation stops.

An InterventionRequest carries enough context to act without digging through logs:
which capability and run, which step, what was expected vs. what is on screen, a
screenshot, and which decisions are allowed. Everything the human then does is
recorded as HumanAction entries, so the evidence trail has no gap across the handoff.
"""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Controller(str, Enum):
    """Who may drive the live session right now. Exactly one at a time."""
    AUTOMATION = "automation"          # the replay engine may act
    AWAITING_HUMAN = "awaiting_human"  # automation paused; no operator has taken over yet
    HUMAN = "human"                    # an operator holds the session


class InterventionKind(str, Enum):
    STUCK = "stuck"        # automation can't proceed (e.g. session expired)
    APPROVAL = "approval"  # a risky step needs a human decision before it runs


class Resolution(str, Enum):
    RESUME = "resume"    # human fixed the screen; automation retries the blocked step
    ABORT = "abort"      # human, or a timeout, ended the run
    APPROVE = "approve"  # run the risky step
    DENY = "deny"        # don't run it; the caller gets an approval_denied outcome


class RequestStatus(str, Enum):
    OPEN = "open"          # waiting for an operator
    CLAIMED = "claimed"    # an operator holds the session
    RESOLVED = "resolved"  # decision made; control is back with automation


class HumanAction(BaseModel):
    """One thing the operator did on the live session. Secrets are never recorded."""
    seq: int
    ts: datetime
    operator: str
    kind: str = Field(description="click | click_name | type | key")
    detail: str = Field(description="What was done, redacted (typed secrets become [REDACTED:secret]).")
    url_before: str | None = None
    url_after: str | None = None


class InterventionRequest(BaseModel):
    id: str
    kind: InterventionKind
    status: RequestStatus = RequestStatus.OPEN
    capability_id: str
    capability_version: str
    run_id: str
    step_id: str
    step_index: int
    step_description: str = Field(description="The step automation stopped at, in words.")
    reason: str = Field(description="Why it stopped, e.g. 'session_expired' or 'risky step'.")
    expected: str
    observed: str
    url: str | None = None
    screenshot: str | None = Field(default=None, description="Screenshot at the moment it stopped.")
    allowed: list[Resolution] = Field(description="Decisions the operator may make.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operator: str | None = None
    resolution: Resolution | None = None
    note: str | None = None
    resolved_at: datetime | None = None
    actions: list[HumanAction] = Field(default_factory=list)
