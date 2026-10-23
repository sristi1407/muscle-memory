"""P3 — the replay engine: execute a Capability deterministically, with NO LLM.

Load an artifact, fill in params, and follow the steps: resolve each Target (ordered
strategies + expect self-check), act, read label-anchored values, evaluate error
rules, and assert the success checkpoint. Returns a three-way ReplayResult:
success / business_outcome / failure.

No model is imported or called here — that's the whole point. The expensive
reasoning happened once, in discovery; replay is free and identical every time.

(Error rules are honored but are populated in P4; recoverable-error recovery is
expanded there too.)
"""
import uuid

from cua.schema import (
    ActionType,
    BusinessOutcome,
    CapabilityArtifact,
    ErrorClass,
    FailureDetail,
    LiteralValue,
    ParamValue,
    ReplayResult,
    Status,
    Step,
    StepResult,
    StepStatus,
    TemplateValue,
)
from cua.surface import LocatorError, Surface


def resolve_value(value_source, params: dict[str, str]) -> str:
    if isinstance(value_source, LiteralValue):
        return value_source.value
    if isinstance(value_source, ParamValue):
        if value_source.param not in params:
            raise KeyError(f"missing required param '{value_source.param}'")
        return params[value_source.param]
    if isinstance(value_source, TemplateValue):
        return value_source.template.format(**params)
    return ""


class ReplayEngine:
    def __init__(self, surface: Surface):
        self.surface = surface

    def replay(self, cap: CapabilityArtifact, params: dict[str, str] | None = None) -> ReplayResult:
        params = params or {}
        run_id = uuid.uuid4().hex[:8]
        step_results: list[StepResult] = []
        outputs: dict[str, str] = {}

        def result(status: Status, **kw) -> ReplayResult:
            return ReplayResult(
                status=status, capability_id=cap.id, capability_version=cap.version,
                run_id=run_id, outputs=outputs, steps=step_results, **kw,
            )

        for step in cap.steps:
            try:
                self._do_step(step, params, outputs)
                self.surface.settle()
            except LocatorError as e:
                biz = self._business_rule(step)
                if biz:
                    return result(Status.BUSINESS_OUTCOME, business_outcome=biz)
                step_results.append(StepResult(step_id=step.id, index=step.index,
                                               status=StepStatus.FAILED, observed=str(e)))
                return result(Status.FAILURE, failure=FailureDetail(
                    step_id=step.id, step_index=step.index,
                    expected=f"resolve target '{step.target.description}'" if step.target else "execute step",
                    observed=str(e), error_class="locator",
                ))
            except Exception as e:  # noqa: BLE001
                step_results.append(StepResult(step_id=step.id, index=step.index,
                                               status=StepStatus.FAILED, observed=str(e)))
                return result(Status.FAILURE, failure=FailureDetail(
                    step_id=step.id, step_index=step.index,
                    expected="execute step", observed=str(e), error_class="runtime",
                ))

            # A business condition may appear on the resulting screen (e.g. "No record found").
            biz = self._business_rule(step)
            if biz:
                return result(Status.BUSINESS_OUTCOME, business_outcome=biz)

            # Optional per-step checkpoint.
            if step.checkpoint and not self.surface.check(step.checkpoint):
                step_results.append(StepResult(step_id=step.id, index=step.index,
                                               status=StepStatus.FAILED, observed="checkpoint failed"))
                return result(Status.FAILURE, failure=FailureDetail(
                    step_id=step.id, step_index=step.index,
                    expected="post-step checkpoint", observed="not satisfied", error_class="checkpoint",
                ))

            step_results.append(StepResult(step_id=step.id, index=step.index, status=StepStatus.OK))

        # Overall success condition.
        if not self.surface.check(cap.contract.success):
            return result(Status.FAILURE, failure=FailureDetail(
                step_id="success", step_index=len(cap.steps),
                expected="success condition", observed="not satisfied", error_class="checkpoint",
            ))

        return result(Status.SUCCESS)

    def _do_step(self, step: Step, params: dict[str, str], outputs: dict[str, str]) -> None:
        s = self.surface
        a = step.action
        if a == ActionType.NAVIGATE:
            s.navigate(step.url or "")
        elif a == ActionType.TYPE:
            s.type_into(step.target, resolve_value(step.value, params))
        elif a == ActionType.CLICK:
            s.click_target(step.target)
        elif a == ActionType.SELECT:
            s.select_in(step.target, resolve_value(step.value, params))
        elif a == ActionType.READ:
            value = s.read_value(step.target)
            if step.output:
                outputs[step.output] = value

    def _business_rule(self, step: Step) -> BusinessOutcome | None:
        """Return a BusinessOutcome if a 'business' error rule matches the current screen."""
        for rule in step.error_rules:
            if rule.classify == ErrorClass.BUSINESS and self.surface.check(rule.when):
                return BusinessOutcome(code=rule.outcome or "business_outcome", message=rule.message)
        return None
