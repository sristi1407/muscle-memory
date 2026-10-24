"""Build the /evidence folder: one discovery run, the Capability it produced, and
replays of that saved Capability covering every outcome in the error taxonomy.

MockCore must be running:  python targets/mockcore/app.py
Run from the repo root:

  python scripts/record_evidence.py            # MockLLM discovery — free, deterministic
  MOCK=0 python scripts/record_evidence.py     # real Nemotron discovery (needs NEBIUS_API_KEY)
  HEADLESS=0 python scripts/record_evidence.py # watch the browser

Replaces evidence/01-* .. 06-*, the saved artifact, and evidence/README.md, then
checks that the synthetic SSN appears in none of the text files it wrote.

Run 06 is the human handoff. A scripted stand-in operator drives the operator
console's HTTP API exactly as the web page does (take control, click, type, resume),
so the handoff is reproducible; scripts/escalation_demo.py is the same flow with a
real person at the console.
"""
from dotenv import load_dotenv

load_dotenv()

import glob
import json
import os
import shutil
import sys
import threading
import time
import urllib.request

from cua.agent import DiscoveryAgent
from cua.compiler import attach_lookup_error_rules, compile_trace, load_capability, save_capability
from cua.escalation import ControlChannel, OperatorConsole
from cua.llm import MockLLM, NemotronLLM
from cua.replay import ReplayEngine
from cua.schema import Action, ActionType
from cua.surface import PlaywrightWebSurface

BASE = "http://127.0.0.1:5001"
EVIDENCE = os.environ.get("EVIDENCE_DIR", "evidence")
SSN = "412-55-9832"  # fake SSN on member 12345's detail screen
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
USE_MOCK = os.environ.get("MOCK", "1") == "1"

GOAL = "Look up member 12345 and read their savings balance."

# (folder, MockCore scenario, member id, what it demonstrates)
REPLAYS = [
    ("02-replay-success", "normal", "67890", "success, with a different member than discovery used"),
    ("03-business-not-found", "normal", "00000", "business outcome: member_not_found, not a crash"),
    ("04-recovered-interstitial", "interstitial", "12345", "recoverable: dismissed a surprise System Notice"),
    ("05-failure-session-timeout", "timeout", "12345", "failure: session expired, with a failure snapshot"),
]


def set_scenario(scenario: str) -> None:
    req = urllib.request.Request(
        f"{BASE}/__control", data=json.dumps({"scenario": scenario}).encode(),
        headers={"content-type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def rel(path: str | None) -> str:
    return os.path.relpath(path, EVIDENCE) if path else "-"


# What the stand-in operator does: sign back in on the expired session, then hand back.
# "demo-pass" is a synthetic credential for the local MockCore only.
OPERATOR = "ops.demo"
SIGN_IN = [
    {"kind": "click_name", "name": "Return to Sign In"},
    {"kind": "click_name", "name": "Operator ID"},
    {"kind": "type", "text": OPERATOR},
    {"kind": "click_name", "name": "Password"},
    {"kind": "type", "text": "demo-pass"},
    {"kind": "click_name", "name": "Sign In"},
    {"kind": "resolve", "resolution": "resume", "note": "re-authenticated the expired session"},
]


def scripted_operator(console_url: str, script: list[dict]) -> threading.Thread:
    """A stand-in human that uses the console's HTTP API, exactly like the web page does."""
    def post(path: str, payload: dict) -> None:
        req = urllib.request.Request(console_url + path, data=json.dumps(payload).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)

    def run() -> None:
        while json.load(urllib.request.urlopen(f"{console_url}/api/state"))["controller"] != "awaiting_human":
            time.sleep(0.2)
        post("/api/claim", {"operator": OPERATOR})
        for cmd in script:
            path = "/api/resolve" if cmd["kind"] == "resolve" else "/api/command"
            post(path, {"operator": OPERATOR, **cmd})

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


# Start clean so reruns don't pile up old runs.
for old in glob.glob(f"{EVIDENCE}/0[1-9]-*"):
    shutil.rmtree(old)

if USE_MOCK:
    llm = MockLLM([
        Action(action=ActionType.TYPE, target="Member ID", text="12345", reason="enter the member id"),
        Action(action=ActionType.CLICK, target="Search", reason="submit the search"),
        Action(action=ActionType.READ, target="Savings", output_key="savings_balance",
               reason="read the savings balance from the detail screen"),
        Action(action=ActionType.FINISH, reason="balance captured; goal complete"),
    ])
else:
    llm = NemotronLLM()
print(f"[discovery model: {getattr(llm, 'model', 'mock')}]")

rows = []
set_scenario("normal")
try:
    with PlaywrightWebSurface(headless=HEADLESS) as surface:
        # 1) Discovery — the model figures the flow out once.
        agent = DiscoveryAgent(surface, llm, evidence_root=f"{EVIDENCE}/01-discovery")
        trace = agent.discover(GOAL, f"{BASE}/members", {"member_id": "12345"}, app="MidStates Core")
        if not trace.success:
            sys.exit(f"discovery did not finish; see {trace.evidence_ref}")
        rows.append(("01-discovery", "normal", "12345", "LLM discovers the flow once",
                     "success", json.dumps(trace.outputs), rel(trace.evidence_ref)))

        # 2) Compile + save — the reusable Capability.
        cap = compile_trace(
            trace, capability_id="member.lookup_savings", name="Look up member savings balance",
            description="Open member lookup, search by ID, and read the savings balance from the detail screen.",
        )
        attach_lookup_error_rules(cap)
        artifact_path = save_capability(cap, EVIDENCE)
        cap = load_capability(artifact_path)  # replay from the saved file, not the in-memory object

        # 3) Replays — no model involved.
        for folder, scenario, mid, what in REPLAYS:
            set_scenario(scenario)
            res = ReplayEngine(surface, evidence_root=f"{EVIDENCE}/{folder}").replay(cap, {"member_id": mid})
            if res.outputs:
                detail = json.dumps(res.outputs)
            elif res.business_outcome:
                detail = res.business_outcome.code
            elif res.failure:
                f = res.failure
                detail = f"step {f.step_id}: {f.error_class}/{f.code or '-'} — {f.observed}"
            else:
                detail = ""
            recovered = sum(1 for s in res.steps if s.status.value == "recovered")
            if recovered:
                detail += f" (recovered {recovered} step)"
            rows.append((folder, scenario, mid, what, res.status.value, detail, rel(res.evidence.log_ref)))

        # 4) Human handoff — the same expired session, but now an operator is on call.
        set_scenario("timeout")
        channel = ControlChannel(claim_timeout_s=60)
        with OperatorConsole(channel) as console:
            scripted_operator(console.url, SIGN_IN)
            res = ReplayEngine(surface, evidence_root=f"{EVIDENCE}/06-human-handoff",
                               control=channel).replay(cap, {"member_id": "12345"})
        iv = res.interventions[0] if res.interventions else None
        detail = json.dumps(res.outputs) if res.outputs else (res.failure.observed if res.failure else "")
        if iv:
            detail += (f" (handoff: {iv.reason} -> {iv.resolution.value} by {iv.operator}, "
                       f"{len(iv.actions)} human actions)")
        rows.append(("06-human-handoff", "timeout", "12345",
                     "human handoff: operator signs in on the same session, automation resumes",
                     res.status.value, detail, rel(res.evidence.log_ref)))
finally:
    set_scenario("normal")

# 4) Index for reviewers.
lines = [
    "# Evidence",
    "",
    "Generated by `scripts/record_evidence.py`. Discovery ran once; every replay below ran",
    f"the saved artifact [`{rel(artifact_path)}`]({rel(artifact_path)}) with **no model in the loop**.",
    "",
    "Each run folder has `run.jsonl` (every event, in order), a screenshot after each step,",
    "`summary.json`, and on failure `failure.json` (URL, accessibility tree, expected vs. observed).",
    "Run 06 also has `intervention-*.json` (the request the operator received, and what they did)",
    "and screenshots at the moments control changed hands. Its operator is scripted: it drives the",
    "operator console's HTTP API exactly as the web page does.",
    "All text is redacted before it is written; screenshots are taken after PII is masked in the page.",
    "",
    "| Run | MockCore scenario | member_id | Shows | Status | Detail | Log |",
    "|---|---|---|---|---|---|---|",
]
for folder, scenario, mid, what, status, detail, log in rows:
    lines.append(f"| {folder} | `{scenario}` | `{mid}` | {what} | **{status}** | {detail} | [{log}]({log}) |")
with open(f"{EVIDENCE}/README.md", "w") as f:
    f.write("\n".join(lines) + "\n")

# 5) Prove nothing sensitive was written.
leaks = []
for path in glob.glob(f"{EVIDENCE}/**/*", recursive=True):
    if path.endswith((".json", ".jsonl", ".md")) and SSN in open(path).read():
        leaks.append(path)

for folder, scenario, mid, _, status, detail, _ in rows:
    print(f"{folder:<28} scenario={scenario:<13} member={mid}  ->  {status.upper():<17} {detail}")
print(f"\nartifact -> {artifact_path}")
print(f"index    -> {EVIDENCE}/README.md")
print("SSN scan:", "CLEAN" if not leaks else f"LEAKED in {leaks}")
sys.exit(1 if leaks else 0)
