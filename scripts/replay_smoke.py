"""P3 — replay the saved Capability deterministically, with NO LLM, for several members.

MockCore must be running:  python targets/mockcore/app.py

  python scripts/replay_smoke.py              # headless
  HEADLESS=0 python scripts/replay_smoke.py   # watch it

The point: the recipe Ultra discovered on member 12345 now runs for ANY member,
with zero model calls.
"""
from dotenv import load_dotenv

load_dotenv()

import os

from cua.compiler import load_capability
from cua.replay import ReplayEngine
from cua.surface import PlaywrightWebSurface

HEADLESS = os.environ.get("HEADLESS", "1") == "1"

cap = load_capability("capabilities/member.lookup_savings.json")
print(f"Capability: {cap.id} v{cap.version}  (model that discovered it: {cap.provenance.model})\n")

members = ["12345", "67890", "22222", "00000"]
with PlaywrightWebSurface(headless=HEADLESS) as surface:
    engine = ReplayEngine(surface)
    for mid in members:
        res = engine.replay(cap, {"member_id": mid})
        line = f"member {mid}: {res.status.value}"
        if res.outputs:
            line += f"  outputs={res.outputs}"
        if res.business_outcome:
            line += f"  business_outcome={res.business_outcome.code}"
        if res.failure:
            line += f"  failure@{res.failure.step_id} ({res.failure.error_class})"
        print(line)
