"""Typed contracts: the Capability artifact (cua.v1), the ReplayResult, and the actions between."""
from .actions import Action, ActionType
from .artifact import (
    CapabilityArtifact,
    Metadata,
    Policy,
    Provenance,
    Surface,
    # contract
    Contract,
    ParamSpec,
    OutputSpec,
    FieldType,
    # steps
    Step,
    RiskLevel,
    # targets / locators
    Target,
    Expect,
    LocatorStrategy,
    RoleStrategy,
    PlaceholderStrategy,
    LabelStrategy,
    TextStrategy,
    CssStrategy,
    CoordinatesStrategy,
    # value sources
    ValueSource,
    LiteralValue,
    ParamValue,
    TemplateValue,
    # checkpoints
    Checkpoint,
    UrlMatches,
    TextPresent,
    TextAbsent,
    ElementVisible,
    ValueEquals,
    # error taxonomy
    ErrorRule,
    ErrorClass,
    RecoveryAction,
    DismissInterstitial,
    RetryWithBackoff,
    ReloadPage,
)
from .result import (
    BusinessOutcome,
    Evidence,
    FailureDetail,
    ReplayResult,
    Status,
    StepResult,
    StepStatus,
)

__all__ = [
    "Action", "ActionType",
    "CapabilityArtifact", "Metadata", "Policy", "Provenance", "Surface",
    "Contract", "ParamSpec", "OutputSpec", "FieldType",
    "Step", "RiskLevel",
    "Target", "Expect", "LocatorStrategy", "RoleStrategy", "PlaceholderStrategy",
    "LabelStrategy", "TextStrategy", "CssStrategy", "CoordinatesStrategy",
    "ValueSource", "LiteralValue", "ParamValue", "TemplateValue",
    "Checkpoint", "UrlMatches", "TextPresent", "TextAbsent", "ElementVisible", "ValueEquals",
    "ErrorRule", "ErrorClass", "RecoveryAction", "DismissInterstitial", "RetryWithBackoff", "ReloadPage",
    "BusinessOutcome", "Evidence", "FailureDetail", "ReplayResult", "Status", "StepResult", "StepStatus",
]
