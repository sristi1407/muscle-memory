"""The replay result contract — the production answer a caller receives.

Deliberately three-way: a *business outcome* (e.g. "member not found") is a
legitimate real-world answer, NOT a failure. Only a locator/runtime/hard error
is a failure.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Outcome(str, Enum):
    SUCCESS = "success"                    # goal met, outputs present
    BUSINESS_OUTCOME = "business_outcome"  # a legitimate answer (not-found, permission-denied)
    FAILURE = "failure"                    # could not complete (locator/runtime/hard error)


class FailureDetail(BaseModel):
    step_index: int
    expected: str
    observed: str
    evidence_ref: str | None = None


class ReplayResult(BaseModel):
    outcome: Outcome
    capability_id: str
    capability_version: str
    run_id: str
    outputs: dict[str, Any] = Field(
        default_factory=dict, description="Typed outputs, present on success."
    )
    business_outcome: str | None = Field(
        default=None, description="e.g. 'member_not_found', 'permission_denied'."
    )
    failure: FailureDetail | None = None
