"""P5 — take over a live replay as the human operator.

MockCore must be running:  python targets/mockcore/app.py
Run from the repo root:

  python scripts/escalation_demo.py          # replay a lookup into an expired session
  APPROVAL=1 python scripts/escalation_demo.py   # same lookup, but the Search click is marked risky

What happens:
  1. MockCore is put into its session-timeout scenario (APPROVAL=1 skips this).
  2. The operator console starts at http://127.0.0.1:5050 — open it in a browser.
  3. Replay hits "Your session has timed out" (or the risky step), pauses, and hands
     the SAME browser session to you. In the console: Take control -> click
     "Return to Sign In" on the screenshot -> click the fields and type any operator
     id and password -> click "Sign In" -> Resume automation (or Approve / Deny).
  4. Replay retries the blocked step and finishes. Evidence goes to evidence/_runs/.

The browser runs headless on purpose: the console is the only way in, so every
human action goes through the control token and is recorded.
"""
from dotenv import load_dotenv

load_dotenv()

import json
import os
import urllib.request

from cua.compiler import load_capability
from cua.escalation import ControlChannel, OperatorConsole
from cua.replay import ReplayEngine
from cua.schema import RiskLevel
from cua.surface import PlaywrightWebSurface

BASE = "http://127.0.0.1:5001"
ARTIFACT = os.environ.get("ARTIFACT", "evidence/member.lookup_savings.json")
APPROVAL = os.environ.get("APPROVAL") == "1"
HEADLESS = os.environ.get("HEADLESS", "1") == "1"


def set_scenario(scenario: str) -> None:
    req = urllib.request.Request(
        f"{BASE}/__control", data=json.dumps({"scenario": scenario}).encode(),
        headers={"content-type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


cap = load_capability(ARTIFACT)
if APPROVAL:
    for step in cap.steps:
        if step.action.value == "click":
            step.risk = RiskLevel.RISKY  # pretend Search is irreversible, to show the approval gate
elif not cap.error_rules:
    print("note: this artifact has no app-wide rules; regenerate it with scripts/record_evidence.py "
          "so the stop is labelled session_expired.")

channel = ControlChannel()
console = OperatorConsole(channel).start()
print(f"\nOperator console -> {console.url}   (open it now)\n")
set_scenario("normal" if APPROVAL else "timeout")
try:
    with PlaywrightWebSurface(headless=HEADLESS) as surface:
        res = ReplayEngine(surface, evidence_root="evidence/_runs", control=channel).replay(
            cap, {"member_id": "12345"})
finally:
    set_scenario("normal")

print(f"\nstatus: {res.status.value}")
if res.outputs:
    print(f"outputs: {res.outputs}")
if res.business_outcome:
    print(f"business outcome: {res.business_outcome.code} — {res.business_outcome.message}")
if res.failure:
    print(f"failure at {res.failure.step_id}: {res.failure.code or res.failure.error_class} — {res.failure.observed}")
for iv in res.interventions:
    print(f"\nintervention {iv.id} ({iv.kind.value}, reason={iv.reason}) -> {iv.resolution.value} by {iv.operator}")
    for a in iv.actions:
        print(f"  {a.seq}. {a.detail}")
print(f"\nevidence -> {os.path.dirname(res.evidence.log_ref)}")

# Keep the console up so the operator can see control came back to automation.
try:
    input("\nPress Enter to close the operator console... ")
except EOFError:
    pass
console.stop()
