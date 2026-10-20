"""Validate the LLM boundary.

  * MockLLM — deterministic, no key.
  * NemotronLLM — a real 2-turn exchange (needs NEBIUS_API_KEY) to prove the
    tool-call + record_result protocol works through the boundary.

Run:  python scripts/llm_smoke.py
"""
from dotenv import load_dotenv

load_dotenv()

import os

from cua.llm import ACT_TOOL, MockLLM, NemotronLLM
from cua.schema import Action, ActionType

SYSTEM = (
    "You drive a legacy web UI to accomplish a goal. Emit exactly ONE act() tool call per turn. "
    "Prefer accessible names you can see in the observation. Call act(action='finish') when done."
)

OBS = (
    "GOAL: look up member 12345 and read their savings balance.\n"
    "URL: http://127.0.0.1:5001/members\n"
    '- textbox "Member ID"\n'
    '- button "Search"'
)

print("=== MockLLM (deterministic, no key) ===")
mock = MockLLM([
    Action(action=ActionType.TYPE, target="Member ID", text="12345"),
    Action(action=ActionType.CLICK, target="Search"),
    Action(action=ActionType.FINISH),
])
mock.start(SYSTEM, [ACT_TOOL])
for _ in range(4):
    print(" ", mock.next_action(OBS))

if os.environ.get("NEBIUS_API_KEY"):
    print("\n=== NemotronLLM (Ultra, real 2-turn exchange) ===")
    llm = NemotronLLM()
    llm.start(SYSTEM, [ACT_TOOL])
    a1 = llm.next_action(OBS)
    print("  turn 1:", a1)
    llm.record_result("Typed '12345' into Member ID. The Search button is still visible.")
    a2 = llm.next_action(OBS + "\n(note: you already typed 12345)")
    print("  turn 2:", a2)
else:
    print("\n(skipping NemotronLLM — no NEBIUS_API_KEY in .env)")
