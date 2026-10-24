"""The Capability artifact — ``cua.v1``.

A typed, versioned, self-documenting *capability*, not a step list. Discovery
compiles a successful run into one of these; replay executes it deterministically
with no LLM in the loop.

Design notes (defend these):
  * Two version numbers: ``schema_version`` (the file format) vs ``version``
    (this capability's semver). They evolve on different clocks.
  * ``Target`` is an *ordered* list of locator strategies + a post-resolution
    ``expect`` self-check. Role+name is primary (stable, generalizes to desktop
    accessibility trees); coordinates are the last resort.
  * ``ValueSource`` stores ``{param: member_id}``, never the literal — one
    recording replays for any member, and sensitive values never freeze in.
  * The error taxonomy lives in the type (``ErrorRule`` per step), not in
    try/except at run time.

Models are ordered bottom-up so every reference is already defined (no forward
refs), which keeps the discriminated unions clean on Pydantic v2.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from .actions import ActionType


# --------------------------------------------------------------------------- #
# Locator strategies — how a step finds a control (tried in order).           #
# --------------------------------------------------------------------------- #
class RoleStrategy(BaseModel):
    """ARIA role + accessible name. PRIMARY: most stable, works on desktop too."""
    kind: Literal["role"] = "role"
    role: str = Field(description="ARIA role, e.g. 'textbox', 'button'.")
    name: str | None = Field(default=None, description="Accessible name of the element.")
    exact: bool = False


class PlaceholderStrategy(BaseModel):
    kind: Literal["placeholder"] = "placeholder"
    placeholder: str


class LabelStrategy(BaseModel):
    kind: Literal["label"] = "label"
    label: str


class TextStrategy(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    exact: bool = False


class CssStrategy(BaseModel):
    """Escape hatch for legacy pages with no accessible names."""
    kind: Literal["css"] = "css"
    selector: str


class CoordinatesStrategy(BaseModel):
    """LAST RESORT. Captured with the viewport so replay can scale."""
    kind: Literal["coordinates"] = "coordinates"
    x: float
    y: float
    viewport_w: int
    viewport_h: int


LocatorStrategy = Annotated[
    Union[
        RoleStrategy,
        PlaceholderStrategy,
        LabelStrategy,
        TextStrategy,
        CssStrategy,
        CoordinatesStrategy,
    ],
    Field(discriminator="kind"),
]


class Expect(BaseModel):
    """Post-resolution self-check: assert the resolved element is the one we meant."""
    role: str | None = None
    editable: bool | None = None
    visible: bool | None = True
    text_contains: str | None = None


class Target(BaseModel):
    """A resilient reference to one element: ordered strategies + a self-check."""
    description: str = Field(description="Human-readable element description.")
    strategies: list[LocatorStrategy] = Field(
        description="Ordered fallbacks; replay tries each until one resolves."
    )
    expect: Expect | None = None


# --------------------------------------------------------------------------- #
# ValueSource — where a step's text comes from (parameterization lives here).  #
# --------------------------------------------------------------------------- #
class LiteralValue(BaseModel):
    kind: Literal["literal"] = "literal"
    value: str


class ParamValue(BaseModel):
    kind: Literal["param"] = "param"
    param: str = Field(description="Name of a declared Contract input to bind at replay time.")


class TemplateValue(BaseModel):
    kind: Literal["template"] = "template"
    template: str = Field(description="A format string referencing inputs, e.g. '{first} {last}'.")


ValueSource = Annotated[
    Union[LiteralValue, ParamValue, TemplateValue],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Checkpoint — assert we reached a state. Reused for step checks, the success  #
# condition, and ErrorRule.when.                                              #
# --------------------------------------------------------------------------- #
class UrlMatches(BaseModel):
    kind: Literal["url_matches"] = "url_matches"
    pattern: str
    description: str | None = None


class TextPresent(BaseModel):
    kind: Literal["text_present"] = "text_present"
    text: str
    description: str | None = None


class TextAbsent(BaseModel):
    kind: Literal["text_absent"] = "text_absent"
    text: str
    description: str | None = None


class ElementVisible(BaseModel):
    kind: Literal["element_visible"] = "element_visible"
    target: Target
    description: str | None = None


class ValueEquals(BaseModel):
    kind: Literal["value_equals"] = "value_equals"
    target: Target
    equals: str
    description: str | None = None


Checkpoint = Annotated[
    Union[UrlMatches, TextPresent, TextAbsent, ElementVisible, ValueEquals],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Recovery actions — what a 'recoverable' error does.                         #
# --------------------------------------------------------------------------- #
class DismissInterstitial(BaseModel):
    kind: Literal["dismiss"] = "dismiss"
    target: Target = Field(description="The control that dismisses the interstitial (e.g. 'Acknowledge').")
    description: str | None = None


class RetryWithBackoff(BaseModel):
    kind: Literal["retry"] = "retry"
    max_attempts: int = 3
    backoff_seconds: float = 1.0


class ReloadPage(BaseModel):
    kind: Literal["reload"] = "reload"


RecoveryAction = Annotated[
    Union[DismissInterstitial, RetryWithBackoff, ReloadPage],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Error taxonomy — encoded per step.                                          #
# --------------------------------------------------------------------------- #
class ErrorClass(str, Enum):
    BUSINESS = "business"        # a legitimate real-world answer -> named outcome
    RECOVERABLE = "recoverable"  # transient/known -> run a RecoveryAction
    HARD = "hard"               # genuine failure -> report with evidence


class ErrorRule(BaseModel):
    when: Checkpoint = Field(description="Condition that detects this error on the current screen.")
    classify: ErrorClass
    outcome: str | None = Field(
        default=None,
        description="Named code: the business outcome (e.g. 'member_not_found'), or for hard "
                    "errors the failure code (e.g. 'session_expired').",
    )
    recover: Optional[RecoveryAction] = Field(
        default=None, description="For recoverable: the action that unsticks replay."
    )
    message: str | None = None


# --------------------------------------------------------------------------- #
# Steps.                                                                       #
# --------------------------------------------------------------------------- #
class RiskLevel(str, Enum):
    SAFE = "safe"
    RISKY = "risky"  # irreversible / money-moving; may require human approval


class Step(BaseModel):
    id: str = Field(description="Stable step id, referenced by failures and approvals.")
    index: int
    action: ActionType
    target: Target | None = None
    value: Optional[ValueSource] = Field(default=None, description="For type/select steps.")
    url: str | None = Field(default=None, description="For navigate steps.")
    output: str | None = Field(default=None, description="For read steps: the Contract output to populate.")
    wait_for: Optional[Checkpoint] = Field(default=None, description="Await this before acting.")
    checkpoint: Optional[Checkpoint] = Field(default=None, description="Assert this after acting.")
    error_rules: list[ErrorRule] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.SAFE


# --------------------------------------------------------------------------- #
# Contract — what makes it a capability, not a script.                        #
# --------------------------------------------------------------------------- #
class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"


class ParamSpec(BaseModel):
    name: str
    type: FieldType = FieldType.STRING
    required: bool = True
    description: str | None = None
    sensitive: bool = Field(
        default=False, description="If true, redact in artifacts, logs, and screenshots."
    )
    example: str | None = Field(default=None, description="Redacted example for documentation.")


class OutputSpec(BaseModel):
    name: str
    type: FieldType = FieldType.STRING
    description: str | None = None
    sensitive: bool = False


class Contract(BaseModel):
    inputs: list[ParamSpec] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    success: Checkpoint = Field(description="The checkpoint that defines a successful run.")


# --------------------------------------------------------------------------- #
# Metadata, policy, provenance, and the top-level artifact.                    #
# --------------------------------------------------------------------------- #
class Surface(str, Enum):
    WEB = "web"
    WEB_LEGACY = "web-legacy"
    DESKTOP = "desktop"


class Metadata(BaseModel):
    app: str = Field(description="Vendor/product driven, e.g. 'MidStates Core'.")
    surface: Surface = Surface.WEB_LEGACY
    tenant: str | None = None
    author: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None


class Policy(BaseModel):
    allowlist_domains: list[str] = Field(default_factory=list)
    allowlist_routes: list[str] = Field(default_factory=list)
    approval_required: list[str] = Field(
        default_factory=list, description="Step ids that need human approval before execution."
    )


class Provenance(BaseModel):
    discovery_run_id: str
    model: str = Field(description="Model that discovered this capability (e.g. the Nemotron id).")
    transcript_ref: str | None = Field(
        default=None, description="Path to the redacted discovery transcript/evidence."
    )


class CapabilityArtifact(BaseModel):
    """A typed, versioned, deterministically-replayable capability (cua.v1)."""
    schema_version: Literal["cua.v1"] = "cua.v1"
    id: str = Field(description="Stable capability id, e.g. 'member.lookup_savings'.")
    version: str = Field(default="1.0.0", description="This capability's semver.")
    name: str
    description: str
    metadata: Metadata
    contract: Contract
    steps: list[Step]
    error_rules: list[ErrorRule] = Field(
        default_factory=list,
        description="App-wide rules checked after every step, after the step's own rules "
                    "(conditions like session expiry that can appear anywhere).",
    )
    policy: Policy = Field(default_factory=Policy)
    provenance: Provenance
