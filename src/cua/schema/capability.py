"""The Capability artifact — a typed, versioned, replayable capability.

This is the load-bearing contract of the whole system. Discovery compiles a
successful run into one of these; replay executes it deterministically with no
LLM in the decision loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .actions import ActionType


# --------------------------------------------------------------------------- #
# Locators: how to find an element, with ordered fallbacks.                    #
# Accessibility-first (role + name) is the most stable; CSS is last resort.    #
# --------------------------------------------------------------------------- #
class LocatorKind(str, Enum):
    ROLE = "role"              # ARIA role + accessible name
    PLACEHOLDER = "placeholder"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"


class Locator(BaseModel):
    kind: LocatorKind
    value: str = Field(
        description="Query value: accessible name, placeholder, label text, visible text, or a CSS selector."
    )
    role: str | None = Field(
        default=None, description="ARIA role when kind == role (e.g. 'textbox', 'button')."
    )


class Target(BaseModel):
    """A resilient reference to one element: ordered strategies + a self-check."""

    description: str = Field(description="Human-readable element description (its accessible name).")
    locators: list[Locator] = Field(
        description="Ordered fallback strategies; replay tries them in order until one resolves."
    )
    expect_text: str | None = Field(
        default=None,
        description="Post-resolution self-check: text the resolved element/area should contain.",
    )


# --------------------------------------------------------------------------- #
# Typed input/output contract.                                                #
# --------------------------------------------------------------------------- #
class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"


class IOField(BaseModel):
    name: str
    type: FieldType = FieldType.STRING
    sensitive: bool = Field(
        default=False, description="If true, redact in artifacts, logs, and screenshots."
    )
    description: str | None = None


class Contract(BaseModel):
    inputs: list[IOField] = Field(default_factory=list)
    outputs: list[IOField] = Field(default_factory=list)
    success_condition: str = Field(
        description="Human-readable condition that defines a successful run."
    )


# --------------------------------------------------------------------------- #
# Steps.                                                                       #
# --------------------------------------------------------------------------- #
class RiskLevel(str, Enum):
    SAFE = "safe"
    RISKY = "risky"  # irreversible / money-moving; may require human approval


class Step(BaseModel):
    index: int
    action: ActionType
    target: Target | None = None
    text_template: str | None = Field(
        default=None,
        description="Text to type; may reference an input as {name}, e.g. '{member_id}'.",
    )
    url: str | None = None
    output_key: str | None = Field(
        default=None, description="For read steps: the Contract output to populate."
    )
    risk: RiskLevel = RiskLevel.SAFE


# --------------------------------------------------------------------------- #
# Metadata, policy, provenance.                                               #
# --------------------------------------------------------------------------- #
class Surface(str, Enum):
    WEB = "web"
    WEB_LEGACY = "web-legacy"
    DESKTOP = "desktop"


class Metadata(BaseModel):
    id: str = Field(description="Stable capability id, e.g. 'member.lookup_savings'.")
    version: str = "0.1.0"
    app: str = Field(description="Vendor/product this capability drives, e.g. 'MidStates Core'.")
    tenant: str | None = None
    surface: Surface = Surface.WEB_LEGACY


class CapabilityPolicy(BaseModel):
    allowlist_domains: list[str] = Field(default_factory=list)
    approval_required_steps: list[int] = Field(
        default_factory=list, description="Step indices that need human approval before execution."
    )


class Provenance(BaseModel):
    discovery_run_id: str
    model: str = Field(description="Model that discovered this capability (e.g. the Nemotron id).")
    transcript_ref: str | None = Field(
        default=None, description="Path to the redacted discovery transcript/evidence."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Capability(BaseModel):
    """A typed, versioned, deterministically-replayable capability."""

    metadata: Metadata
    goal: str = Field(description="The natural-language goal this capability accomplishes.")
    contract: Contract
    steps: list[Step]
    policy: CapabilityPolicy = Field(default_factory=CapabilityPolicy)
    provenance: Provenance
