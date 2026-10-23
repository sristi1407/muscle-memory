"""P4 — prove the error taxonomy by INJECTING runtime conditions into MockCore.

MockCore must be running:  python targets/mockcore/app.py
The capability must be compiled WITH error rules:  python scripts/compile_smoke.py

  python scripts/error_smoke.py              # headless
  HEADLESS=0 python scripts/error_smoke.py   # watch it

Each case sets a MockCore scenario via /__control, then replays (no LLM).
"""
from dotenv import load_dotenv

load_dotenv()

import json
import os
import urllib.request

from cua.compiler import load_capability
from cua.replay import ReplayEngine
from cua.surface import PlaywrightWebSurface

HEADLESS = os.environ.get("HEADLESS", "1") == "1"
CONTROL = "http://127.0.0.1:5001/__control"


def set_scenario(scenario: str) -> None:
    req = urllib.request.Request(
        CONTROL, data=json.dumps({"scenario": scenario}).encode(),
        headers={"content-type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


# (scenario, member_id, what we expect to see)
CASES = [
    ("normal", "67890", "SUCCESS  (baseline — a different member)"),
    ("normal", "00000", "BUSINESS_OUTCOME member_not_found  (not a crash)"),
    ("interstitial", "12345", "RECOVERED -> SUCCESS  (dismissed the popup)"),
    ("timeout", "12345", "FAILURE  (session expired — a genuine failure)"),
]

cap = load_capability("capabilities/member.lookup_savings.json")
print(f"Capability: {cap.id} v{cap.version}\n")

with PlaywrightWebSurface(headless=HEADLESS) as surface:
    engine = ReplayEngine(surface)
    for scenario, mid, expect in CASES:
        set_scenario(scenario)
        res = engine.replay(cap, {"member_id": mid})
        detail = ""
        if res.outputs:
            detail = f" outputs={res.outputs}"
        elif res.business_outcome:
            detail = f" business={res.business_outcome.code}"
        elif res.failure:
            detail = f" failure@{res.failure.step_id} ({res.failure.error_class})"
        recovered = sum(1 for s in res.steps if s.status.value == "recovered")
        rec = f" [recovered {recovered} step(s)]" if recovered else ""
        print(f"scenario={scenario:<12} member={mid}  ->  {res.status.value.upper()}{detail}{rec}")
        print(f"    expected: {expect}\n")

set_scenario("normal")  # reset
