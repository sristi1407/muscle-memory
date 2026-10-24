"""P3/P4/P5 — the replay engine: execute a Capability deterministically, with NO LLM.

Follows the recipe step by step and classifies what it sees into the three-way
ReplayResult:
  * SUCCESS          — goal met, outputs captured.
  * BUSINESS_OUTCOME — a legitimate real-world answer (e.g. member_not_found).
  * FAILURE          — a genuine problem (locator/runtime/checkpoint/hard).

Error rules (the step's own, then the capability's app-wide ones) are evaluated
after each action:
  * business    -> stop, return the named outcome.
  * recoverable -> run a RecoveryAction (dismiss / reload / retry-with-backoff),
                   then continue or re-attempt the step (bounded).
  * hard        -> stop, return a failure.

With a ControlChannel attached (P5), a failure becomes a *handoff* instead of an
end: automation pauses, a human takes the same live session, and on Resume the
blocked step is retried. Risky steps never run unattended: a human approves them
first, and without an operator channel they fail closed.

No model is imported or called here. The expensive reasoning happened once, in
discovery; replay is free and identical every time.
"""
import time
import uuid

from cua.escalation import ControlChannel
from cua.evidence import EvidenceRecorder, NullRecorder
from cua.policy import PolicyGate, PolicyViolation, Redactor
from cua.schema import (
    ActionType,
    BusinessOutcome,
    CapabilityArtifact,
    DismissInterstitial,
    ErrorClass,
    FailureDetail,
    InterventionKind,
    InterventionRequest,
    LiteralValue,
    ParamValue,
    ReloadPage,
    ReplayResult,
    Resolution,
    RetryWithBackoff,
    RiskLevel,
    Status,
    Step,
    StepResult,
    StepStatus,
    TemplateValue,
)
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


def describe(step: Step) -> str:
    if step.target:
        return f"{step.action.value} '{step.target.description}'"
    return f"{step.action.value} {step.url or ''}".strip()


class ReplayEngine:
    def __init__(self, surface: Surface, evidence_root: str | None = None,
                 control: ControlChannel | None = None, max_handoffs: int = 2):
        self.surface = surface
        self.evidence_root = evidence_root  # None = no evidence written
        self.control = control              # None = no human available: fail instead of handing off
        self.max_handoffs = max_handoffs    # "stuck" handoffs per run, so a run can't loop forever

    def replay(self, cap: CapabilityArtifact, params: dict[str, str] | None = None) -> ReplayResult:
        params = params or {}
        run_id = uuid.uuid4().hex[:8]
        step_results: list[StepResult] = []
        outputs: dict[str, str] = {}
        interventions: list[InterventionRequest] = []
        gate = PolicyGate.from_capability(cap)
        rec = self._recorder(cap, params, run_id)
        rec.event("run_start", capability_id=cap.id, capability_version=cap.version, params=params)

        def result(status: Status, **kw) -> ReplayResult:
            res = ReplayResult(
                status=status, capability_id=cap.id, capability_version=cap.version,
                run_id=run_id, outputs=outputs, steps=step_results,
                interventions=interventions, **kw,
            )
            res.evidence = rec.finish(result=res.model_dump(mode="json", exclude={"evidence"}))
            return res

        def record(step: Step, status: StepStatus, observed: str | None = None) -> None:
            shot = rec.screenshot(self.surface, f"step-{step.index:02d}")
            step_results.append(StepResult(step_id=step.id, index=step.index, status=status,
                                           observed=observed, screenshot_ref=shot))
            rec.event("step_result", step_id=step.id, index=step.index,
                      status=status.value, observed=observed)
            if self.control:
                self.control.observe(self.surface)  # the operator can watch automation too

        def failure(step_id: str, index: int, expected: str, observed: str,
                    error_class: str, code: str | None = None) -> ReplayResult:
            ref = rec.failure_snapshot(self.surface, step_id=step_id, step_index=index,
                                       expected=expected, observed=observed,
                                       error_class=error_class, code=code)
            return result(Status.FAILURE, failure=FailureDetail(
                step_id=step_id, step_index=index, expected=expected, observed=observed,
                error_class=error_class, code=code, evidence_ref=ref,
            ))

        def fail(step: Step, expected: str, observed: str, error_class: str,
                 code: str | None = None) -> ReplayResult:
            step_results.append(StepResult(step_id=step.id, index=step.index,
                                           status=StepStatus.FAILED, observed=observed))
            return failure(step.id, step.index, expected, observed, error_class, code)

        def hand_off(step: Step, kind: InterventionKind, reason: str,
                     expected: str, observed: str) -> InterventionRequest | None:
            """Pause, give the live session to a human, and block until they decide."""
            if self.control is None:
                return None
            stuck = sum(1 for i in interventions if i.kind == InterventionKind.STUCK)
            if kind == InterventionKind.STUCK and stuck >= self.max_handoffs:
                return None
            n = len(interventions) + 1
            req = InterventionRequest(
                id=f"{run_id}-{n}", kind=kind, capability_id=cap.id,
                capability_version=cap.version, run_id=run_id, step_id=step.id,
                step_index=step.index, step_description=describe(step), reason=reason,
                expected=expected, observed=observed, url=self.surface.current_url(),
                screenshot=rec.screenshot(self.surface, f"intervention-{run_id}-{n}"),
                allowed=([Resolution.APPROVE, Resolution.DENY] if kind == InterventionKind.APPROVAL
                         else [Resolution.RESUME, Resolution.ABORT]),
            )
            interventions.append(req)
            return self.control.hand_off(req, self.surface, rec)

        for step in cap.steps:
            # Risky steps never run unattended: a human approves first, or we fail closed.
            if step.risk == RiskLevel.RISKY or gate.requires_approval(step.id):
                req = hand_off(step, InterventionKind.APPROVAL, reason="risky step: needs human approval",
                               expected="an operator decision", observed=describe(step))
                if req is None:
                    return fail(step, "human approval", "no operator available; risky step not executed",
                                "policy", code="approval_required")
                if req.resolution == Resolution.DENY:
                    record(step, StepStatus.SKIPPED, "approval_denied")
                    return result(Status.BUSINESS_OUTCOME, business_outcome=BusinessOutcome(
                        code="approval_denied", message=req.note or f"denied by {req.operator}"))
                if req.resolution != Resolution.APPROVE:
                    return fail(step, "human approval", req.note or "no decision", "escalation",
                                code="escalation_timed_out" if req.operator is None else "operator_aborted")

            attempts = 0
            while True:
                attempts += 1
                if self.control:
                    self.control.assert_automation()  # the control token: only act while we hold it

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

                rec.event("step_attempt", step_id=step.id, index=step.index,
                          action=step.action.value, attempt=attempts,
                          error=f"{exec_error[0]}: {exec_error[1]}" if exec_error else None)

                # 2) evaluate error rules against the resulting screen
                problem = None  # (expected, observed, error_class, code) if the step didn't land
                verdict = self._evaluate_rules(step, cap.error_rules)
                if verdict is not None:
                    kind, payload, rule = verdict
                    rec.event("rule_fired", step_id=step.id, verdict=kind,
                              detail=getattr(payload, "code", payload))
                    if kind == "business":
                        record(step, StepStatus.OK, payload.code)
                        return result(Status.BUSINESS_OUTCOME, business_outcome=payload)
                    if kind == "recovered":
                        record(step, StepStatus.RECOVERED)
                        break  # proceed to next step
                    if kind == "retry":
                        if attempts < MAX_ATTEMPTS:
                            continue  # re-attempt the same step
                        problem = ("recover", "recovery retries exhausted", "recoverable", None)
                    else:  # hard
                        problem = (f"{describe(step)} to succeed", payload, "hard", rule.outcome)

                # 3) no rule explained it — surface any execution error
                if problem is None and exec_error is not None:
                    cls, msg = exec_error
                    expected = (f"resolve target '{step.target.description}'"
                                if step.target else f"execute {step.action.value}")
                    problem = (expected, msg, cls, None)

                # 4) optional per-step checkpoint
                if problem is None and step.checkpoint and not self.surface.check(step.checkpoint):
                    problem = ("post-step checkpoint", "not satisfied", "checkpoint", None)

                if problem is None:
                    record(step, StepStatus.OK)
                    break

                # 5) can't proceed safely: hand the live session to a human (never for policy blocks)
                expected, observed, error_class, code = problem
                req = None
                if error_class != "policy":
                    req = hand_off(step, InterventionKind.STUCK, reason=code or error_class,
                                   expected=expected, observed=observed)
                if req is not None and req.resolution == Resolution.RESUME:
                    attempts = 0
                    continue  # retry the blocked step on the screen the human left
                if req is not None:
                    observed = f"{observed} (operator: {req.resolution.value}" \
                               f"{': ' + req.note if req.note else ''})"
                return fail(step, expected, observed, error_class, code)

        # overall success condition
        if not self.surface.check(cap.contract.success):
            return failure("success", len(cap.steps), "success condition", "not satisfied", "checkpoint")

        return result(Status.SUCCESS)

    # ------------------------------------------------------------------ #
    def _recorder(self, cap: CapabilityArtifact, params: dict[str, str], run_id: str):
        if not self.evidence_root:
            return NullRecorder()
        # Mask inputs the contract declares sensitive, on top of the default PII patterns.
        sensitive = [params[p.name] for p in cap.contract.inputs if p.sensitive and p.name in params]
        return EvidenceRecorder(self.evidence_root, "replay", run_id,
                                Redactor(sensitive_values=sensitive))

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

    def _evaluate_rules(self, step: Step, app_rules):
        """Return (kind, payload, rule) or None. The step's own rules win over app-wide ones.

        kind: "business" (payload BusinessOutcome) | "hard" (payload message)
              | "retry" | "recovered"
        """
        for rule in [*step.error_rules, *app_rules]:
            if not self.surface.check(rule.when):
                continue
            if rule.classify == ErrorClass.BUSINESS:
                return ("business", BusinessOutcome(code=rule.outcome or "business_outcome",
                                                    message=rule.message), rule)
            if rule.classify == ErrorClass.HARD:
                return ("hard", rule.message or "hard error", rule)
            if rule.classify == ErrorClass.RECOVERABLE:
                kind, payload = self._recover(rule.recover)
                return (kind, payload, rule)
        return None

    def _recover(self, recover):
        if isinstance(recover, DismissInterstitial):
            try:
                self.surface.click_target(recover.target)
                self.surface.settle()
            except Exception:  # noqa: BLE001
                return ("hard", "failed to dismiss interstitial")
            return ("recovered", None)
        if isinstance(recover, ReloadPage):
            self.surface.reload()
            self.surface.settle()
            return ("retry", None)
        if isinstance(recover, RetryWithBackoff):
            time.sleep(recover.backoff_seconds)
            return ("retry", None)
        return ("recovered", None)
