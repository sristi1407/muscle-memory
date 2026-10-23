"""P6 — prove the safety guarantees end-to-end against the live app.

MockCore must be running:  python targets/mockcore/app.py

  python scripts/safety_check.py

Checks:
  1. The synthetic SSN never appears in a discovery trace (redacted at the source,
     so the model never saw it either).
  2. The SSN is masked in the page at the moment a screenshot is captured.
  3. The SSN never appears in the saved Capability artifact.
  4. The allowlist blocks an off-domain navigation.
"""
from dotenv import load_dotenv

load_dotenv()

import os
import sys

from cua.agent import DiscoveryAgent
from cua.compiler import compile_trace
from cua.llm import MockLLM
from cua.policy import PolicyGate, PolicyViolation
from cua.schema import Action, ActionType
from cua.surface import PlaywrightWebSurface

SSN = "412-55-9832"  # fake SSN shown on member 12345's detail screen
BASE = "http://127.0.0.1:5001"

llm = MockLLM([
    Action(action=ActionType.TYPE, target="Member ID", text="12345"),
    Action(action=ActionType.CLICK, target="Search"),
    Action(action=ActionType.READ, target="Savings", output_key="savings_balance"),
    Action(action=ActionType.FINISH),
])

os.makedirs("evidence/_runs", exist_ok=True)
shot = "evidence/_runs/safety_detail.png"

with PlaywrightWebSurface(headless=True) as surface:
    trace = DiscoveryAgent(surface, llm).discover(
        "Look up member 12345 and read their savings balance.",
        f"{BASE}/members", {"member_id": "12345"}, app="MidStates Core",
    )
    surface.navigate(f"{BASE}/members/detail?mid=12345")  # a screen that shows the SSN
    surface.screenshot(shot)
    text_at_capture = surface.page.locator("body").inner_text()

cap_json = compile_trace(trace, capability_id="member.lookup_savings").model_dump_json()

results = []


def check(name: str, passed: bool) -> None:
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


check("SSN absent from discovery trace (model never saw it)", SSN not in trace.model_dump_json())
check("SSN masked in the page when the screenshot was captured", SSN not in text_at_capture)
check("SSN absent from the compiled Capability artifact", SSN not in cap_json)

try:
    PolicyGate(allowlist_domains=["127.0.0.1"]).check_url("https://evil.example.com/x")
    check("off-domain navigation blocked by allowlist", False)
except PolicyViolation:
    check("off-domain navigation blocked by allowlist", True)

print(f"\nscreenshot -> {shot}")
print("SAFETY:", "ALL PASS" if all(results) else "SOME FAILED")
sys.exit(0 if all(results) else 1)
