# Muscle Memory

**Discover once with an LLM. Replay free, forever.** Hands for AI agents inside legacy
banking software that has no API.

Banks and credit unions run back-office apps whose only way in is the screen a human
operator clicks through. Muscle Memory lets an LLM (NVIDIA Nemotron, on Nebius Token
Factory) work out how to do a task in such an app **once**, compiles that run into a
typed, versioned **capability**, and then replays the capability **deterministically,
with no model in the loop**. Replay knows the difference between "done", "a legitimate
business answer" (*no such member*) and "something broke", and when it genuinely gets
stuck it hands the *same live browser session* to a human operator and resumes after.

```
 discover ── Nemotron drives the UI through its accessibility tree (once per capability)
    │
 compile ─── the successful path becomes a typed, versioned capability (JSON)
    │
 replay ──── no model: resolve → act → verify → classify:
               success · business_outcome · failure   (+ human handoff when stuck)
```

The design rationale is in [`REPORT.md`](REPORT.md); proof of every outcome is in
[`evidence/`](evidence/README.md).

---

## Quick start

Python 3.10+.

```bash
git clone https://github.com/sristi1407/muscle-memory.git && cd muscle-memory
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

This installs the `muscle-memory` command (`python -m cua` does the same thing).

**Nemotron key (optional).** Live discovery uses NVIDIA Nemotron on Nebius Token Factory:

```bash
echo "NEBIUS_API_KEY=your-key" > .env
```

Without a key everything still runs — see [Running without live services](#running-without-live-services).

**Start the target app** in its own terminal and leave it running:

```bash
python targets/mockcore/app.py
```

MockCore (`http://127.0.0.1:5001`) is a deliberately legacy back-office banking app:
server-rendered, table layouts, no test IDs, a fake SSN on screen, and switchable
runtime conditions. All data is synthetic. Members: `12345`, `67890`, `22222`.

---

## Demo path

Run these from the repo root, with MockCore running.

**1. Discover a capability from a goal** (Nemotron drives the app, once):

```bash
muscle-memory discover \
  --goal "Look up member 12345 and read their savings balance." \
  --start http://127.0.0.1:5001/members \
  --input member_id=12345 \
  --id member.lookup_savings
```

It prints the evidence log and saves `capabilities/member.lookup_savings.json`: typed
input `member_id`, typed output `savings_balance`, four steps with resilient locators,
error rules, and an allowlist. Try your own goal, too — e.g. *"Look up member 67890
and read their checking balance."* with `--input member_id=67890 --id member.lookup_checking`.

**2. Replay it for a different member** — no model involved:

```bash
muscle-memory replay capabilities/member.lookup_savings.json --param member_id=67890
```

```
SUCCESS  member.lookup_savings v1.0.0  run 28a52a1a
  outputs: {"savings_balance": "$15,230.10"}
```

**3. A business outcome, not a crash:**

```bash
muscle-memory replay capabilities/member.lookup_savings.json --param member_id=00000
```

```
BUSINESS_OUTCOME  member.lookup_savings v1.0.0  run b2ba6df4
  business outcome: member_not_found — No member exists for the given ID.
```

Add `--json` to see the full result contract a calling agent receives. Exit codes:
`0` success, `2` business outcome, `1` failure.

**4. Runtime conditions.** Switch MockCore's injected condition, replay, switch back:

```bash
muscle-memory scenario interstitial    # a surprise "System Notice" dialog -> dismissed, replay succeeds
muscle-memory scenario timeout         # session expired -> named failure: session_expired
muscle-memory scenario normal
```

**5. Human handoff.** Expire the session, then replay with the operator console attached:

```bash
muscle-memory scenario timeout
muscle-memory replay capabilities/member.lookup_savings.json --param member_id=12345 --console
```

Open **http://127.0.0.1:5050**. Replay has paused and is waiting for you. Click **Take
control**, click **Return to Sign In** *on the live page picture*, click the Operator ID
field in the picture and type any ID in the panel, press **Tab**, type any password
(tick *hide what I type*), press **Enter**, then **Resume automation**. Replay retries
the blocked step and finishes; every action you took is recorded, the password as
`[REDACTED:secret]`. Run `muscle-memory scenario normal` afterwards.

To see the **risky-step approval** gate instead (replay pauses before an irreversible
click and asks a human to approve or deny):

```bash
APPROVAL=1 python scripts/escalation_demo.py
```

**6. Regenerate the evidence folder** (discovery + five replays, including the handoff):

```bash
MOCK=0 python scripts/record_evidence.py     # live Nemotron discovery
python scripts/record_evidence.py            # recorded decisions, no key
```

**7. Tests** (no browser or key needed):

```bash
pytest -q
```

---

## Running without live services

| Part | Needs a model? | Without a key |
|---|---|---|
| Discovery | Yes — Nemotron Ultra by default | Uses a recorded decision sequence for the sample goal (`--mock`, or automatically when `NEBIUS_API_KEY` is unset) |
| Compile | No | — |
| Replay, error handling, handoff | **Never** | Works exactly the same |
| Tests | No | `pytest -q` |

Everything runs locally against MockCore; nothing touches a real bank, real credentials,
or real PII.

---

## What's in the repo

```
targets/mockcore/app.py      the legacy bank app we automate (Flask)
src/cua/
  surface/                   how we see and act on an app: accessibility tree, screenshots, pixels+keys
  agent/                     discovery: observe → LLM decides one action → act → record
  llm/                       provider-agnostic model boundary: Nemotron driver + mock
  compiler/                  successful run → typed capability; error-rule packs; registry
  schema/                    the contracts: capability (cua.v1), replay result, intervention request
  replay/                    deterministic engine: locators, checkpoints, error taxonomy, handoff
  policy/                    allowlist gate + PII/secret redaction
  escalation/                control token + operator console (human takeover of the live session)
  evidence/                  per-run JSONL logs, screenshots, failure snapshots
  cli.py                     the muscle-memory command
scripts/                     record_evidence.py, escalation_demo.py, and per-phase smoke scripts
tests/                       unit tests (escalation, evidence, policy, redaction)
evidence/                    a real Nemotron discovery run and six labelled replays
capabilities/                saved capabilities
```

---

## Evidence

[`evidence/README.md`](evidence/README.md) indexes one Nemotron discovery run and the
replays of the capability it produced:

| Run | Result |
|---|---|
| 01 Discovery (Nemotron Ultra) | success — read $4,210.55 |
| 02 Replay, different member | success — $15,230.10 |
| 03 Unknown member | business outcome `member_not_found` |
| 04 Surprise maintenance dialog | dismissed automatically, then success |
| 05 Session expired, nobody on call | named failure `session_expired`, with a failure snapshot |
| 06 Session expired, operator on call | human signs in on the same session, automation resumes → success |

Each run has a `run.jsonl` (every observation, decision, action and reason, in order),
a screenshot after each step, and a failure snapshot or intervention record where
relevant. A scan confirms the synthetic SSN appears in none of it.

---

## Built with NVIDIA Nemotron on Nebius Token Factory

- **Where Nemotron is used:** the discovery agent. At each step it receives the page's
  accessibility tree and the goal, and answers with exactly one structured `act()` tool
  call (type, click, select, read, or finish) plus a short reason. **Nemotron 3 Ultra**
  (`nvidia/Nemotron-3-Ultra-550b-a55b`) is the default, because driving an unfamiliar
  legacy UI is the hard reasoning step; `--model super` and `--model nano` select cheaper
  tiers. Code: [`src/cua/llm/nemotron.py`](src/cua/llm/nemotron.py).
- **How Token Factory fit in:** its API is OpenAI-compatible, so the driver is the
  standard `openai` client with Token Factory's base URL — the provider sits behind a
  small interface ([`src/cua/llm/base.py`](src/cua/llm/base.py)) and switching model
  tiers is a model-id change.
- **Why this stretches credits:** the model is called once per decision during
  discovery — four calls to learn the member-lookup flow — and **zero** times after
  that. Every replay, in production, is free and identical. In our runs Ultra learned
  both the sample goal and an unseen one (*read member 67890's checking balance*) on
  the first attempt; the second capability then replayed for another member with no
  model calls.
- **Other Nebius services:** none — the whole system runs locally.

### Feedback

- The OpenAI-compatible endpoint made integration nearly free: no new SDK, and model
  tiers are interchangeable by id.
- Nemotron 3 Ultra followed the single-tool-call contract reliably at temperature 0 and
  used the exact accessible names from the observation, which is what makes the
  recorded steps replayable.

---

## Safety

Every navigation is checked against the capability's allowlist; risky steps never run
unattended (a human approves them, or the run fails closed); PII is redacted at the
source, before the model, the logs or a screenshot can see it; operator-typed secrets
are never recorded. Details and limits: [`REPORT.md`](REPORT.md).

## License

[MIT](LICENSE)
