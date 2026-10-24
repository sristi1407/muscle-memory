"""Domain-knowledge error rules for the member-lookup capability.

A successful discovery run never exercises the failure paths, so the compiler
can't infer these. We author them explicitly — encoding what a human operator
knows about this app — and attach them to the step after which each condition
appears (the Search submit).
"""
from cua.schema import (
    ActionType,
    CapabilityArtifact,
    DismissInterstitial,
    ErrorClass,
    ErrorRule,
    RoleStrategy,
    Target,
    TextPresent,
)

LOOKUP_ERROR_RULES = [
    ErrorRule(
        when=TextPresent(text="No record found"),
        classify=ErrorClass.BUSINESS,
        outcome="member_not_found",
        message="No member exists for the given ID.",
    ),
    ErrorRule(
        when=TextPresent(text="System Notice"),
        classify=ErrorClass.RECOVERABLE,
        recover=DismissInterstitial(
            target=Target(
                description="Acknowledge & Continue",
                strategies=[RoleStrategy(role="button", name="Acknowledge & Continue")],
            ),
        ),
        message="Dismissed a maintenance interstitial and continued.",
    ),
]


# App-wide: these can appear after ANY step, so they live on the capability, not one step.
APP_ERROR_RULES = [
    ErrorRule(
        when=TextPresent(text="Your session has timed out"),
        classify=ErrorClass.HARD,
        outcome="session_expired",
        message="Session expired. Signing back in needs a human: the agent never handles credentials.",
    ),
]


def attach_lookup_error_rules(cap: CapabilityArtifact) -> CapabilityArtifact:
    """Attach the lookup error taxonomy: per-step rules on the Search submit, plus app-wide rules."""
    for step in cap.steps:
        if step.action == ActionType.CLICK:
            step.error_rules = list(LOOKUP_ERROR_RULES)
    cap.error_rules = list(APP_ERROR_RULES)
    return cap
