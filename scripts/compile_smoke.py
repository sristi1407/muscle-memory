"""P2 — discover, then COMPILE the trace into a reusable Capability artifact.

MockCore must be running:  python targets/mockcore/app.py

  python scripts/compile_smoke.py              # MockLLM (default) — free, deterministic
  MOCK=0 python scripts/compile_smoke.py       # real Nemotron discovery
  HEADLESS=0 python scripts/compile_smoke.py   # watch the browser
"""
from dotenv import load_dotenv

load_dotenv()

import os

from cua.agent import DiscoveryAgent
from cua.compiler import compile_trace, save_capability
from cua.llm import MockLLM, NemotronLLM
from cua.schema import Action, ActionType
from cua.surface import PlaywrightWebSurface

GOAL = "Look up member 12345 and read their savings balance."
START = "http://127.0.0.1:5001/members"
INPUTS = {"member_id": "12345"}

HEADLESS = os.environ.get("HEADLESS", "1") == "1"
USE_MOCK = os.environ.get("MOCK", "1") == "1"

if USE_MOCK:
    llm = MockLLM([
        Action(action=ActionType.TYPE, target="Member ID", text="12345"),
        Action(action=ActionType.CLICK, target="Search"),
        Action(action=ActionType.READ, target="Savings", output_key="savings_balance"),
        Action(action=ActionType.FINISH),
    ])
else:
    llm = NemotronLLM()

with PlaywrightWebSurface(headless=HEADLESS) as surface:
    trace = DiscoveryAgent(surface, llm).discover(GOAL, START, INPUTS, app="MidStates Core")

cap = compile_trace(
    trace,
    capability_id="member.lookup_savings",
    name="Look up member savings balance",
    description="Open member lookup, search by ID, and read the savings balance from the detail screen.",
)

print(cap.model_dump_json(indent=2))
path = save_capability(cap, "capabilities")
print(f"\nsaved -> {path}")
