"""Transient actions the discovery agent emits and the surface executes.

An ``Action`` is a *decision in flight* — one thing the LLM wants to do on the
current screen during discovery. It is deliberately separate from a compiled
``Step`` (see ``artifact.py``): a Step adds resilient locators, waits, per-step
error rules, and a risk level that we learn from a successful discovery run.
"""
from enum import Enum

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"   # choose an <option> in a dropdown
    READ = "read"
    FINISH = "finish"   # the agent signals the goal is complete


class Action(BaseModel):
    """One UI action chosen by the agent for the current screen."""

    action: ActionType
    target: str | None = Field(
        default=None,
        description="Accessible name/role of the element to act on (e.g. 'Member ID', 'Search').",
    )
    text: str | None = Field(
        default=None, description="Text to type (action=type) or option to pick (action=select)."
    )
    url: str | None = Field(default=None, description="URL to open, when action == navigate.")
    output_key: str | None = Field(
        default=None,
        description="When action == read, the Contract output this value populates (e.g. 'savings_balance').",
    )
    reason: str | None = Field(
        default=None, description="Short rationale, kept for the discovery transcript."
    )
