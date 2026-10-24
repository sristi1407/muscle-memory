"""Unit tests for the human handoff: the control token and the engine's escalation paths.

No browser: FakeApp stands in for MockCore, and a thread plays the human operator.
"""
import threading
import time

import pytest

from cua.escalation import ControlChannel, ControlError
from cua.evidence import NullRecorder
from cua.replay import ReplayEngine
from cua.schema import (
    ActionType,
    CapabilityArtifact,
    Contract,
    Controller,
    ErrorClass,
    ErrorRule,
    InterventionKind,
    InterventionRequest,
    Metadata,
    ParamSpec,
    ParamValue,
    Provenance,
    Resolution,
    RiskLevel,
    RoleStrategy,
    Status,
    Step,
    Target,
    TextPresent,
)
from cua.surface import LocatorError

EXPIRED = "Your session has timed out due to inactivity."
PAGES = {
    "none": "",
    "search": "Member Lookup  Member ID  Search",
    "detail": "Member Detail  Savings  $4,210.55",
    "expired": f"Session Expired  {EXPIRED}",
}


class FakeApp:
    """Search page -> detail page, plus an expired-session page that only signing in fixes."""

    def __init__(self, expired: bool = False):
        self.expired = expired
        self.page = "none"
        self.url = ""
        self.secret_focus = False

    # replay-time
    def navigate(self, url):
        self.url = url
        self.page = "expired" if self.expired else "search"

    def settle(self):
        pass

    def current_url(self):
        return self.url

    def _need(self, page, target):
        if self.page != page:
            raise LocatorError(f"no '{target.description}' on the {self.page} page")

    def type_into(self, target, text):
        self._need("search", target)

    def click_target(self, target):
        self._need("search", target)
        self.page = "detail"

    def read_value(self, target):
        self._need("detail", target)
        return "$4,210.55"

    def check(self, checkpoint):
        return checkpoint.text in PAGES[self.page]

    def frame(self):
        return b"png"

    # operator-time
    def do_click(self, name):
        self.secret_focus = name == "Password"
        if name == "Sign In":
            self.expired, self.page = False, "search"

    def click_at(self, x, y):
        pass

    def type_text(self, text):
        pass

    def press_key(self, key):
        pass

    def focus_is_secret(self):
        return self.secret_focus


def capability(risky_search: bool = False) -> CapabilityArtifact:
    def target(name):
        return Target(description=name, strategies=[RoleStrategy(role="textbox", name=name)])

    return CapabilityArtifact(
        id="member.lookup_savings", name="Look up savings", description="test capability",
        metadata=Metadata(app="FakeApp"),
        contract=Contract(inputs=[ParamSpec(name="member_id")], success=TextPresent(text="Savings")),
        steps=[
            Step(id="s0", index=0, action=ActionType.NAVIGATE, url="http://fake/members"),
            Step(id="s1", index=1, action=ActionType.TYPE, target=target("Member ID"),
                 value=ParamValue(param="member_id")),
            Step(id="s2", index=2, action=ActionType.CLICK, target=target("Search"),
                 risk=RiskLevel.RISKY if risky_search else RiskLevel.SAFE),
            Step(id="s3", index=3, action=ActionType.READ, target=target("Savings"),
                 output="savings_balance"),
        ],
        error_rules=[ErrorRule(when=TextPresent(text=EXPIRED), classify=ErrorClass.HARD,
                               outcome="session_expired", message="session expired")],
        provenance=Provenance(discovery_run_id="test", model="test"),
    )


def operator(channel: ControlChannel, script, name: str = "ops1") -> threading.Thread:
    """Play the human: wait for a request, take control, then run the script."""
    def run():
        while channel.controller != Controller.AWAITING_HUMAN:
            time.sleep(0.01)
        channel.claim(name)
        for kind, payload in script:
            if kind == "resolve":
                channel.resolve(name, **payload)
            else:
                channel.command(name, {"kind": kind, **payload})

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


SIGN_IN = [
    ("click_name", {"name": "Return to Sign In"}),
    ("click_name", {"name": "Operator ID"}),
    ("type", {"text": "ops.jdoe"}),
    ("click_name", {"name": "Password"}),
    ("type", {"text": "hunter2"}),
    ("click_name", {"name": "Sign In"}),
]


# --------------------------------------------------------------------------- #
# Stuck -> human -> resume                                                     #
# --------------------------------------------------------------------------- #
def test_expired_session_hands_off_and_resumes_on_the_same_session():
    app, channel = FakeApp(expired=True), ControlChannel()
    operator(channel, [*SIGN_IN, ("resolve", {"resolution": "resume"})])

    res = ReplayEngine(app, control=channel).replay(capability(), {"member_id": "12345"})

    assert res.status == Status.SUCCESS
    assert res.outputs == {"savings_balance": "$4,210.55"}
    [iv] = res.interventions
    assert (iv.kind, iv.reason, iv.resolution, iv.operator) == (
        InterventionKind.STUCK, "session_expired", Resolution.RESUME, "ops1")
    assert channel.controller == Controller.AUTOMATION  # control came back


def test_human_actions_are_recorded_but_secrets_are_not():
    app, channel = FakeApp(expired=True), ControlChannel()
    operator(channel, [*SIGN_IN, ("resolve", {"resolution": "resume"})])

    res = ReplayEngine(app, control=channel).replay(capability(), {"member_id": "12345"})

    details = [a.detail for a in res.interventions[0].actions]
    assert details[2] == "type 'ops.jdoe'"
    assert details[4] == "type [REDACTED:secret]"
    assert not any("hunter2" in d for d in details)


def test_without_an_operator_session_expiry_is_a_named_failure():
    res = ReplayEngine(FakeApp(expired=True)).replay(capability(), {"member_id": "12345"})
    assert res.status == Status.FAILURE
    assert (res.failure.error_class, res.failure.code) == ("hard", "session_expired")


def test_operator_abort_ends_the_run_with_their_note():
    channel = ControlChannel()
    operator(channel, [("resolve", {"resolution": "abort", "note": "member asked to stop"})])

    res = ReplayEngine(FakeApp(expired=True), control=channel).replay(capability(), {"member_id": "1"})

    assert res.status == Status.FAILURE
    assert "operator: abort: member asked to stop" in res.failure.observed


def test_nobody_answering_times_out_instead_of_hanging():
    channel = ControlChannel(claim_timeout_s=0.2)
    res = ReplayEngine(FakeApp(expired=True), control=channel).replay(capability(), {"member_id": "1"})
    assert res.status == Status.FAILURE
    assert res.failure.code == "session_expired"
    assert "timed out" in res.failure.observed


# --------------------------------------------------------------------------- #
# Risky steps                                                                  #
# --------------------------------------------------------------------------- #
def test_risky_step_fails_closed_without_an_operator():
    app = FakeApp()
    res = ReplayEngine(app).replay(capability(risky_search=True), {"member_id": "12345"})
    assert res.status == Status.FAILURE
    assert (res.failure.error_class, res.failure.code) == ("policy", "approval_required")
    assert app.page == "search"  # the risky click never happened


def test_risky_step_runs_after_approval():
    channel = ControlChannel()
    operator(channel, [("resolve", {"resolution": "approve"})])
    res = ReplayEngine(FakeApp(), control=channel).replay(capability(risky_search=True), {"member_id": "1"})
    assert res.status == Status.SUCCESS
    assert res.interventions[0].kind == InterventionKind.APPROVAL


def test_denied_risky_step_is_a_business_outcome_not_a_crash():
    app, channel = FakeApp(), ControlChannel()
    operator(channel, [("resolve", {"resolution": "deny", "note": "deposit looks wrong"})])
    res = ReplayEngine(app, control=channel).replay(capability(risky_search=True), {"member_id": "1"})
    assert res.status == Status.BUSINESS_OUTCOME
    assert res.business_outcome.code == "approval_denied"
    assert app.page == "search"


# --------------------------------------------------------------------------- #
# The control token itself                                                     #
# --------------------------------------------------------------------------- #
def test_only_the_controller_may_act():
    channel = ControlChannel()
    with pytest.raises(ControlError):
        channel.claim("ops1")  # nothing to take over yet

    req = InterventionRequest(
        id="r1", kind=InterventionKind.STUCK, capability_id="c", capability_version="1",
        run_id="r", step_id="s0", step_index=0, step_description="navigate", reason="test",
        expected="x", observed="y", allowed=[Resolution.RESUME, Resolution.ABORT],
    )
    done = threading.Thread(target=channel.hand_off, args=(req, FakeApp(), NullRecorder()), daemon=True)
    done.start()
    while channel.controller != Controller.AWAITING_HUMAN:
        time.sleep(0.01)

    with pytest.raises(ControlError):
        channel.command("ops1", {"kind": "type", "text": "hi"})   # must take control first
    channel.claim("ops1")
    with pytest.raises(ControlError):
        channel.assert_automation()                               # automation is locked out
    with pytest.raises(ControlError):
        channel.command("intruder", {"kind": "type", "text": "hi"})  # someone else
    with pytest.raises(ControlError):
        channel.resolve("ops1", "approve")                        # not a valid decision here
    with pytest.raises(ControlError):
        channel.command("ops1", {"kind": "key", "key": "Delete"})  # not an allowed key
    with pytest.raises(ControlError):
        channel.command("ops1", {"kind": "click"})                # malformed

    channel.resolve("ops1", "resume")
    done.join(timeout=2)
    assert channel.controller == Controller.AUTOMATION
    assert channel.history[-1].resolution == Resolution.RESUME
