# Computer-Use Automation System

> Give an AI agent *hands* inside legacy bank software that has no API — safely, and
> without paying an LLM to re-reason about the UI on every run.

An LLM **discovers** how to accomplish a goal by driving a real application UI once.
That successful run is **compiled** into a typed, versioned *Capability* artifact. In
production, an AI agent invokes that capability and we **replay** it deterministically
— no model in the decision loop — with a real error taxonomy, safety guardrails, and a
human-handoff path for when replay gets stuck.

```
  discover (LLM drives the UI, guardrailed)
      └──> compile (successful path -> typed, versioned Capability artifact)
              └──> replay (deterministic, no LLM, with error taxonomy + checkpoints)
```

This repo implements a small-but-real end-to-end slice of that idea against **one
concrete surface** (a web app), with the core abstractions designed so they don't paint
us into a corner for legacy-web / desktop surfaces or multi-tenant reuse. The design
rationale lives in [`REPORT.md`](REPORT.md).

---

## Why this shape

The target environment is back-office banking apps: **stable UIs but real runtime
errors**, **heterogeneous legacy surfaces** (no clean DOM, no test IDs, sometimes
desktop), and **multi-tenant at scale** (many institutions running the same vendor
product configured differently). That drives three commitments:

1. **Accessibility-tree-first perception.** We lead with roles + accessible names, not
   CSS selectors, because that's more stable *and* generalizes to desktop. Screenshots
   and coordinates are a fallback, not the primary contract.
2. **The artifact is a *capability*, not a script.** It has a typed contract (inputs,
   outputs, success condition), resilient locators with ordered fallbacks, and an
   explicit per-step error policy — so both a human reviewer and a calling agent know
   what it does, needs, and returns.
3. **Business outcome ≠ failure.** "No such member" is a legitimate typed result, not a
   crash. The replay result contract separates *success* / *business outcome* /
   *hard failure* deliberately.

---

## Architecture

```
                          ┌─────────────────── POLICY ENGINE ───────────────────┐
                          │  allowlist (domains/routes/actions) · risk class ·   │
                          │  redaction (PII/secrets → typed refs)                │
                          └──────────────┬───────────────────────┬───────────────┘
                                         │ (gates every action)  │
   goal + target + params                ▼                       ▼
        │                        ┌───────────────┐        ┌──────────────┐
        ▼                        │  AGENT LOOP   │        │ REPLAY ENGINE│  ◄── artifact + params
  ┌───────────┐   observe        │ (discovery)   │        │ (production) │
  │  SURFACE  │◄───────────────► │ observe→decide│        │ resolve→verify│
  │  DRIVER   │   act            │ →act (LLM     │        │ →act→checkpoint│
  │(Playwright│                  │  tool calls)  │        │ →classify err │
  │ web: AX   │                  └──────┬────────┘        └──────┬───────┘
  │ tree +    │                         │ success trace          │ ReplayResult
  │ screenshot│                         ▼                        ▼
  │ + coords) │                  ┌──────────────┐         success | business_outcome | failure
  └─────┬─────┘                  │  ARTIFACT    │
        │                        │  COMPILER    │──► Capability Registry (+ optional catalog API)
        │                        └──────────────┘
        ▼
  SESSION / CONTROL MANAGER  ──(owns live browser context + control token: automation|human)──►  ESCALATION
        │                                                                                         MANAGER
        └──────────────────────────► EVIDENCE STORE (JSONL logs · per-step screenshots ·           +
                                       failure snapshots)                              minimal OPERATOR CONSOLE
```

**Component responsibilities**

| Component | Responsibility |
|---|---|
| **Surface driver** | Perceive (accessibility tree + screenshot + URL) and act (click/type/navigate/read) on a live surface; resolve locators. The one place that knows *how* to touch a surface. |
| **Agent loop** (discovery) | LLM-driven observe→decide→act via a typed tool schema, guardrailed, until success or a stop condition. |
| **Artifact compiler** | Distill the *successful path* out of the messy transcript into a typed, parameterized, versioned Capability artifact. |
| **Replay engine** (production) | Execute an artifact deterministically with input params; resolve + verify locators; assert checkpoints; classify runtime conditions; return a structured result. |
| **Policy engine** | Enforce the allowlist on every action; classify risky/irreversible actions; redact secrets/PII from artifacts, logs, and screenshots. |
| **Session / control manager** | Own the live browser session and a **control token** (`automation \| human`) that says who may act. |
| **Escalation + operator console** | Detect "stuck," route an intervention request with context, let a human drive the *same* live session, then hand control back. |
| **Evidence store** | Structured JSONL logs + per-step screenshots + a richer snapshot on failure. |

### The two load-bearing contracts

**Capability artifact** — a typed, versioned capability (not a step list):

- `metadata` — id, semver, app / vendor-product / tenant, `surface: web | web-legacy | desktop`
- `contract` — typed **inputs** (e.g. `memberId`, with a `sensitive` flag), typed **outputs**
  (e.g. `savingsBalance`), and a **success condition** checkpoint
- `steps[]` — each = `action` + a resilient **Target** (ordered locator strategies + a
  post-resolution self-check) + `waits` + per-step **error rules** + `risk: safe | risky`
- `policy` — allowlist + which steps require approval
- `provenance` — discovery run id, model, redacted transcript reference

**Replay result** — the production contract:

- `success` → typed outputs
- `business_outcome` → a legitimate answer the caller needs (e.g. `member_not_found`)
- `failure` → step + what was expected + what was observed + evidence reference

---

## Repo layout

```
interface-cua/
├── README.md                    this file
├── REPORT.md                    design write-up (exact headings the brief asks for)
├── requirements.txt
├── targets/mockcore/app.py      the hostile legacy bank app we automate  [BUILT]
├── src/cua/
│   ├── surface/                 perceive/act abstraction + Playwright web driver
│   ├── schema/                  ★ Capability artifact + ReplayResult models
│   ├── agent/                   discovery loop (observe→decide→act)
│   ├── compiler/                trace → artifact
│   ├── replay/                  ★ deterministic engine + error taxonomy
│   ├── policy/                  allowlist + risk + redaction
│   ├── escalation/              session control token + operator console
│   ├── evidence/                JSONL logs + screenshots
│   └── llm/                     Anthropic client + mock boundary
├── cli.py                       run-agent / replay / serve-console
└── evidence/                    saved discovery + replay + error runs
```

---

## Setup

```bash
git clone <this-repo> && cd interface-cua
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

**LLM key (optional).** Discovery uses Claude. To run discovery live:

```bash
export ANTHROPIC_API_KEY=sk-...
```

If no key is set, discovery runs against a **mock LLM boundary** (a recorded decision
sequence) so the full pipeline — discovery → artifact → replay → error handling →
escalation — is reproducible with **no live services**. Replay never needs a key.

---

## Running

### 1. Start the target app

```bash
python targets/mockcore/app.py
```

Opens the MockCore legacy bank console at `http://127.0.0.1:5001`.
Members: `12345` (Active), `67890` (Active), `22222` (Restricted). Unknown IDs → a
*not-found* business outcome. All data is synthetic — no real credentials, no real PII.

You can inject runtime conditions to exercise the error taxonomy:

```bash
# persist a scenario for subsequent requests
curl -s -X POST http://127.0.0.1:5001/__control \
     -H 'content-type: application/json' \
     -d '{"scenario":"interstitial"}'
# scenarios: normal | slow | interstitial | timeout | validation | permission
```

### 2. Demo path (discovery → artifact → replay)

> Status: the mock app is runnable today; the commands below are the **intended demo
> path** and light up as the slices land (see Build status). They are listed here so the
> shape of the deliverable is clear.

```bash
# discover: LLM drives MockCore to complete the goal, emits a Capability artifact
python cli.py run-agent \
  --goal "look up member 12345 and read their current savings balance" \
  --target http://127.0.0.1:5001/members \
  --out artifacts/member_lookup.json

# replay: deterministic, no LLM, with a different input parameter
python cli.py replay artifacts/member_lookup.json --param memberId=67890

# replay into a business outcome (unknown member -> member_not_found, not a crash)
python cli.py replay artifacts/member_lookup.json --param memberId=00000

# escalation demo: run a risky flow, force a stuck state, take over the live session
python cli.py serve-console        # minimal operator console
python cli.py run-agent --goal "open a sub-account for member 22222 ..." ...
```

---

## Build status

Vertical slices — each leaves something working end-to-end.

- [x] **P0 — Foundations & target.** Hostile legacy mock bank app with injectable
      runtime conditions; repo skeleton; deps.
- [ ] **P1 — Discovery.** Agent loop completes "look up member → read savings balance,"
      guardrailed, evidence captured.
- [ ] **P2 — Compile.** Successful run → typed, parameterized, versioned artifact.
- [ ] **P3 — Replay.** Deterministic replay with input params, checkpoint verify, typed
      outputs.
- [ ] **P4 — Error taxonomy.** Inject not-found / validation / interstitial / timeout →
      replay classifies business vs. recoverable vs. hard, and reports.
- [ ] **P5 — Escalation & handoff.** Risky sub-account flow → stuck → operator takes the
      live session → resume.
- [ ] **P6 — Safety hardening.** Allowlist enforcement + redaction proof + evidence polish.
- [ ] **P7 — Write-up & evidence.** `REPORT.md`, saved `/evidence/`, and at most one
      stretch goal.

---

## Safety & data handling

- **Allowlist.** Every action (discovery *and* replay) passes through a policy gate:
  permitted domains/routes and permitted action types. Actions outside it are blocked.
- **Risky actions.** Irreversible steps (submit that creates/moves something) are flagged
  and handled conservatively — gated on confirmation/approval rather than run blindly.
- **Redaction.** Secrets and regulated data (the synthetic SSN on the detail screen,
  credentials, tokens) are never persisted into artifacts or logs. Sensitive inputs are
  stored as typed references, never literals; screenshots mask sensitive fields.

This is a demo against synthetic data. It is **not** production-hardened — see the *Cuts*
section of [`REPORT.md`](REPORT.md) for the boundary between what's real here and what a
production system would add.
