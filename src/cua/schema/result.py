"""The replay result contract — the production answer a caller receives.

Deliberately three-way (``status``): a *business outcome* ("member not found")
is a legitimate answer, NOT a failure. Only a locator/runtime/hard error is a
failure. The brief calls conflating these "the most common design mistake", so
the split is on purpose.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    SUCCESS = "success"                    # goal met, outputs present
    BUSINESS_OUTCOME = "business_outcome"  # a legitimate answer (not-found, permission-denied)
    FAILURE = "failure"                    # could not complete (locator/runtime/hard error)


class StepStatus(str, Enum):
    OK = "ok"
    RECOVERED = "recovered"  # hit a recoverable error and a RecoveryAction fixed it
    SKIPPED = "skipped"
    FAILED = "failed"


class StepResult(BaseModel):
    step_id: str
    index: int
    status: StepStatus
    observed: str | None = None
    screenshot_ref: str | None = None


class BusinessOutcome(BaseModel):
    code: str = Field(description="Named outcome, e.g. 'member_not_found', 'permission_denied'.")
    message: str | None = None


class FailureDetail(BaseModel):
    step_id: str
    step_index: int
    expected: str
    observed: str
    error_class: str
    evidence_ref: str | None = None


class Evidence(BaseModel):
    log_ref: str | None = None
    screenshots: list[str] = Field(default_factory=list)


class ReplayResult(BaseModel):
    status: Status
    capability_id: str
    capability_version: str
    run_id: str
    outputs: dict[str, Any] = Field(default_factory=dict, description="Typed outputs, present on success.")
    business_outcome: BusinessOutcome | None = None
    failure: FailureDetail | None = None
    steps: list[StepResult] = Field(default_factory=list)
    evidence: Evidence | None = None
