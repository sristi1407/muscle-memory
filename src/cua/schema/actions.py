"""Transient actions the discovery agent emits and the surface executes.

An ``Action`` is a *decision in flight* — one thing the LLM wants to do on the
current screen. It is deliberately separate from a compiled ``Step`` (see
``capability.py``): a Step adds the resilient locators, waits, and risk level
that we learn during a successful discovery run.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    NAVIGATE = "navigate"
    READ = "read"
    FINISH = "finish"  # the agent signals the goal is complete


class Action(BaseModel):
    """One UI action chosen by the agent for the current screen."""

    action: ActionType
    target: str | None = Field(
        default=None,
        description="Accessible name/role of the element to act on (e.g. 'Member ID', 'Search').",
    )
    text: str | None = Field(default=None, description="Text to type, when action == type.")
    url: str | None = Field(default=None, description="URL to open, when action == navigate.")
    output_key: str | None = Field(
        default=None,
        description="When action == read, the Contract output this value populates (e.g. 'savings_balance').",
    )
    reason: str | None = Field(
        default=None, description="Short rationale, kept for the discovery transcript."
    )
