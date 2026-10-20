"""P1 — run discovery against MockCore.

MockCore must be running:  python targets/mockcore/app.py

  python scripts/discover_smoke.py              # real Nemotron (Ultra), headful
  HEADLESS=1 python scripts/discover_smoke.py   # headless
  MOCK=1 python scripts/discover_smoke.py       # deterministic MockLLM, no key
"""
from dotenv import load_dotenv

load_dotenv()

import os

from cua.agent import DiscoveryAgent
from cua.llm import MockLLM, NemotronLLM
from cua.schema import Action, ActionType
from cua.surface import PlaywrightWebSurface

GOAL = "Look up member 12345 and read their savings balance."
START = "http://127.0.0.1:5001/members"
INPUTS = {"member_id": "12345"}

HEADLESS = os.environ.get("HEADLESS") == "1"
USE_MOCK = os.environ.get("MOCK") == "1"

if USE_MOCK:
    llm = MockLLM([
        Action(action=ActionType.TYPE, target="Member ID", text="12345", reason="enter member id"),
        Action(action=ActionType.CLICK, target="Search", reason="submit the search"),
        Action(action=ActionType.READ, target="Savings", output_key="savings_balance", reason="read the balance"),
        Action(action=ActionType.FINISH, reason="goal complete"),
    ])
    print("[using MockLLM — deterministic, no key]")
else:
    llm = NemotronLLM()
    print("[using NemotronLLM — Ultra discovery]")

with PlaywrightWebSurface(headless=HEADLESS) as surface:
    trace = DiscoveryAgent(surface, llm).discover(GOAL, START, INPUTS, app="MidStates Core")

print(trace.model_dump_json(indent=2))
print(f"\nsuccess: {trace.success}  |  outputs: {trace.outputs}  |  steps: {len(trace.steps)}")
