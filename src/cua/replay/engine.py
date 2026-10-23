"""P3/P4 — the replay engine: execute a Capability deterministically, with NO LLM.

Follows the recipe step by step and classifies what it sees into the three-way
ReplayResult:
  * SUCCESS          — goal met, outputs captured.
  * BUSINESS_OUTCOME — a legitimate real-world answer (e.g. member_not_found).
  * FAILURE          — a genuine problem (locator/runtime/checkpoint/hard).

Error rules (authored per step) are evaluated after each action:
  * business    -> stop, return the named outcome.
  * recoverable -> run a RecoveryAction (dismiss / reload / retry-with-backoff),
                   then continue or re-attempt the step (bounded).
  * hard        -> stop, return a failure.

No model is imported or called here. The expensive reasoning happened once, in
discovery; replay is free and identical every time.
"""
import time
import uuid

from cua.schema import (
    ActionType,
    BusinessOutcome,
    CapabilityArtifact,
    DismissInterstitial,
    ErrorClass,
    FailureDetail,
    LiteralValue,
    ParamValue,
    ReloadPage,
    ReplayResult,
    RetryWithBackoff,
    Status,
    Step,
    StepResult,
    StepStatus,
    TemplateValue,
)
from cua.policy import PolicyGate, PolicyViolation
from cua.surface import LocatorError, Surface

MAX_ATTEMPTS = 3


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
        gate = PolicyGate.from_capability(cap)

        def result(status: Status, **kw) -> ReplayResult:
            return ReplayResult(
                status=status, capability_id=cap.id, capability_version=cap.version,
                run_id=run_id, outputs=outputs, steps=step_results, **kw,
            )

        def fail(step: Step, expected: str, observed: str, error_class: str) -> ReplayResult:
            step_results.append(StepResult(step_id=step.id, index=step.index,
                                           status=StepStatus.FAILED, observed=observed))
            return result(Status.FAILURE, failure=FailureDetail(
                step_id=step.id, step_index=step.index,
                expected=expected, observed=observed, error_class=error_class,
            ))

        for step in cap.steps:
            attempts = 0
            while True:
                attempts += 1

                # 1) execute the action (capture, don't raise yet — a rule may explain it)
                exec_error = None
                try:
                    self._do_step(step, params, outputs, gate)
                    self.surface.settle()
                except PolicyViolation as e:
                    exec_error = ("policy", str(e))
                except LocatorError as e:
                    exec_error = ("locator", str(e))
                except Exception as e:  # noqa: BLE001
                    exec_error = ("runtime", str(e))

                # 2) evaluate error rules against the resulting screen
                verdict = self._evaluate_rules(step)

                if verdict is not None:
                    kind = verdict[0]
                    if kind == "business":
                        step_results.append(StepResult(step_id=step.id, index=step.index,
                                                       status=StepStatus.OK, observed=verdict[1].code))
                        return result(Status.BUSINESS_OUTCOME, business_outcome=verdict[1])
                    if kind == "hard":
                        return fail(step, "no hard error", verdict[1], "hard")
                    if kind == "retry":
                        if attempts < MAX_ATTEMPTS:
                            continue  # re-attempt the same step
                        return fail(step, "recover", "recovery retries exhausted", "recoverable")
                    if kind == "recovered":
                        step_results.append(StepResult(step_id=step.id, index=step.index,
                                                       status=StepStatus.RECOVERED))
                        break  # proceed to next step

                # 3) no rule fired — now surface any execution error as a failure
                if exec_error is not None:
                    cls, msg = exec_error
                    expected = (f"resolve target '{step.target.description}'"
                                if step.target else f"execute {step.action.value}")
                    return fail(step, expected, msg, cls)

                # 4) optional per-step checkpoint
                if step.checkpoint and not self.surface.check(step.checkpoint):
                    return fail(step, "post-step checkpoint", "not satisfied", "checkpoint")

                step_results.append(StepResult(step_id=step.id, index=step.index, status=StepStatus.OK))
                break

        # overall success condition
        if not self.surface.check(cap.contract.success):
            return result(Status.FAILURE, failure=FailureDetail(
                step_id="success", step_index=len(cap.steps),
                expected="success condition", observed="not satisfied", error_class="checkpoint",
            ))

        return result(Status.SUCCESS)

    # ------------------------------------------------------------------ #
    def _do_step(self, step: Step, params: dict[str, str], outputs: dict[str, str],
                 gate: PolicyGate) -> None:
        s = self.surface
        a = step.action
        if a == ActionType.NAVIGATE:
            gate.check_url(step.url or "")  # allowlist enforced before every navigation
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

    def _evaluate_rules(self, step: Step):
        """Return a verdict tuple or None.

        ("business", BusinessOutcome) | ("hard", msg) | ("retry",) | ("recovered",)
        """
        for rule in step.error_rules:
            if not self.surface.check(rule.when):
                continue
            if rule.classify == ErrorClass.BUSINESS:
                return ("business", BusinessOutcome(code=rule.outcome or "business_outcome",
                                                    message=rule.message))
            if rule.classify == ErrorClass.HARD:
                return ("hard", rule.message or "hard error")
            if rule.classify == ErrorClass.RECOVERABLE:
                return self._recover(rule.recover)
        return None

    def _recover(self, recover):
        if isinstance(recover, DismissInterstitial):
            try:
                self.surface.click_target(recover.target)
                self.surface.settle()
            except Exception:  # noqa: BLE001
                return ("hard", "failed to dismiss interstitial")
            return ("recovered",)
        if isinstance(recover, ReloadPage):
            self.surface.reload()
            self.surface.settle()
            return ("retry",)
        if isinstance(recover, RetryWithBackoff):
            time.sleep(recover.backoff_seconds)
            return ("retry",)
        return ("recovered",)
