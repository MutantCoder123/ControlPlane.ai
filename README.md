# ControlPlane

**An AI governance gateway for the Accenture Innovation Challenge 2026 — Problem Track 1.**

ControlPlane sits between an organisation's applications and any third-party LLM provider. Every request and every response passes through it. The application changes exactly one line — its `base_url` — and nothing else.

> Companies want to put their real work through an AI model. Their legal and security teams refuse, because sending real customer data to an outside company is an unacceptable risk. **ControlPlane solves that specific disagreement.** It swaps every sensitive value for a consistent placeholder before the request leaves the building, sends the placeholder version onward, and restores the real values only after the response comes back — inside the building, never before. The provider never receives a single real customer detail. The employee still gets a complete, useful answer. Nobody has to choose between "safe" and "useful."

**Status: complete — 513 tests, offline, no API key required to test.**

---

## Table of contents

1. [What it does](#what-it-does)
2. [Key features](#key-features)
3. [Architecture — the request path](#architecture--the-request-path)
4. [Project structure](#project-structure)
5. [Tech stack](#tech-stack)
6. [How to run](#how-to-run)
7. [API reference](#api-reference)
8. [Dashboard guide](#dashboard-guide)
9. [Engineering workflow](#engineering-workflow)
10. [Testing philosophy](#testing-philosophy)
11. [Deliberate non-goals](#deliberate-non-goals)
12. [Team](#team)

---

## What it does

A regulated enterprise — a bank, an insurer, a hospital, a telco — has language-model use cases with obvious value that are stuck in the same place: legal and security cannot approve them, because approval means sending customer records, employee data, or source code to a third party under a contract that offers no technical guarantee about what happens to it. The project doesn't get rejected. It gets deferred, indefinitely.

ControlPlane is the technical control that makes the approval defensible. Five ideas carry the whole product:

| # | Idea | Why it matters |
|---|---|---|
| 1 | **Substitute, don't redact** | `[REDACTED] wants a refund on [REDACTED]` is safe and useless. Real values are swapped for consistent placeholders before dispatch and restored on the way back — the provider never receives personal data *at all*, and the answer stays complete. |
| 2 | **Substitute identifiers, never operands** | Sensitivity lives in the *linkage*. `45,230` alone is meaningless; `"Priya's balance is 45,230"` is not. Swap the name, pass the number — the model still does arithmetic. |
| 3 | **Known-value matching** | Not "does this look like a secret?" (regex) but "is this **our** secret?" (matched against the organisation's own records). The audit line reads "matched customer record 44219," not "matched a regex." |
| 4 | **Split by reversibility, not speed** | A credential or a name, once rendered, is screen-recordable and irreversible → checked **before** release. A hallucination or biased phrasing is reversible → annotated **after**. The safety-vs-latency trade-off dissolves. |
| 5 | **The use case is the policy unit** | A customer bot, an internal assistant, and a decision-support tool have different risk tolerances. Each compiles to a named, fingerprinted profile. The outcome is a function of *severity × confidence × profile*, never the finding alone. |

---

## Key features

### Substitution engine
Finds sensitive values two ways: **known-value matching** against the organisation's own record store (customer names, account numbers — exact-match, with a Bloom filter in front for speed), and a **pattern/checksum tier** underneath as the floor (Luhn for cards, Verhoeff and mod-97 for other identifiers) for values the record store doesn't cover. Every match becomes a placeholder like `[[CUST_A]]`, scoped so one entity keeps one identity across a multi-part request. Placeholders are restored to real values only after the response returns, inside the building.

### Route profiles & jurisdiction floors
Three shipping profiles — `customer-support`, `internal-knowledge`, `decision-support` — each a compiled, content-fingerprinted policy artefact. A **jurisdiction floor** clamps every profile to a regional minimum (`eu`, `in`, `us`): a profile may be stricter than its floor, never looser. The compiler refuses, at authoring time, any profile that would disable substitution or exempt a credential — a control that can be switched off on a Friday is not a control.

### Decision tiers
Four outcomes — **Allow / Annotate / Review / Block** — resolved from *severity × confidence × profile*. Substitution counts as mitigation: the finding still reaches the audit log, it just no longer has anything left to prevent. A per-profile **flag budget** caps how often a route may flag, because a control that flags constantly trains its users to dismiss it; the budget can never suppress a block.

### Commit-point buffer (safe streaming)
Streamed output is held to a sentence, 40 tokens, or 250ms — whichever comes first — with an overlap window so a sensitive value split across two stream chunks is still caught before release. Nothing is delivered to the reader from a partially-scanned chunk.

### Hash-chained audit log
Every entry hashes its own contents together with the hash before it; editing any entry breaks every hash after it. Entries carry categories, confidences, and record references — **never the prompt, never a matched value** — so the log reconstructs a decision while being useless to anyone who steals it. Persisted to disk and re-verified on load: a chain that cannot survive a restart is not an audit log. Called tamper-**evident**, not tamper-proof — an attacker with process access can still append, but cannot quietly rewrite history.

### Session risk counters
Tracks cumulative, multi-turn risk per session — distinct records touched, agent steps, blocks — without storing a single prompt or response. Catches the "no single turn looks wrong" failure mode (an agent quietly touching a fourth, fifth, sixth customer record) using counters instead of a transcript, which is what keeps it compatible with the product's stateless design.

### Post-delivery quality checks
Run **after** the reader already has the answer, because these are reversible harms:
- **Hallucination detection** — entity-not-in-source, unsupported absolute claims, unsupported causal claims, and a narrow re-ask of the highest-confidence flagged claim. Confidence comes from the model's **real per-token log-probabilities**, not a self-reported score or a flat formula — genuine measured uncertainty, highlighted inline with the confidence embedded next to the flagged span.
- **Toxicity** — an offline, on-device pretrained classifier (`alt-profanity-check`), scored against the cumulative released text at each commit point, not the raw fragment.
- **Bias** — counterfactual probing: the same prompt replayed with paired attribute values (e.g. two names), aggregated across many runs. No per-response bias score exists at any point — bias is a property of a distribution, not of one answer.

### Cost ledger
Attributes spend per request, per team, per profile — gross saving, our own overhead, and net, always returned together, because a saving figure that hides its own overhead is the exact failure this product exists to prevent. Detects repeated invariant prompt prefixes (the highest-value cheap win: provider prompt caching) and flags model over-provisioning. A pre-flight budget gate refuses an over-budget request **before** dispatch, at ₹0.00, because billing starts the moment tokens are generated.

### Metrics & canaries
False positives are measured directly — every flag can be shown to a reviewer. False negatives can't be, so seeded canaries (synthetic values planted in traffic) estimate the miss rate, reported with a **Wilson confidence interval**, not a bare point estimate.

### Feedback loop
When human reviewers overturn a flag, proposed policy tweaks accumulate behind a **3-reviewer consensus threshold** before they're applied — a single reviewer's bad day cannot silently loosen a control.

### OpenAI-compatible gateway
`POST /v1/chat/completions` (streaming and non-streaming) and `POST /v1/embeddings`, wire-compatible with the `openai` Python client with only `base_url` changed — the real integration surface, distinct from the narrated demo server.

---

## Architecture — the request path

A governed request passes through nine stages. Everything before dispatch is synchronous and blocking; everything after delivery is asynchronous and annotating — this ordering is the argument that dissolves the usual safety-vs-latency trade-off.

```
 1. Inbound scan        known-value store, then pattern/checksum tier
 2. Substitution        identifiers -> placeholders, scoped per request
 3. Decision            allow / annotate / review / block, per profile
 4. Pre-flight gate      credential refusal + budget check (refusing costs ₹0.00)
 5. Dispatch            leak check asserts no real value reaches the payload
 6. Commit-point buffer  sentence / 40 tok / 250ms, with an overlap window
 7. Restore             placeholders -> real values, inside the building only
 8. Outbound checks      response PII scan + cross-record disclosure check
 9. Async quality pass   hallucination, overclaim, causal claims, toxicity
```

Policy compiles once, centrally, to a fingerprinted artefact; the request path only ever reads it — nothing on the hot path re-reads a file or makes a network call.

---

## Project structure

```text
controlplane/
├── engine/              substitution engine — the core differentiator
│   ├── api.py             ScanOptions, ScanResult, the public engine surface
│   ├── knownvalue.py      known-value store + Bloom filter matching
│   ├── patterns.py        checksum tiers (Luhn, Verhoeff, mod-97)
│   ├── placeholders.py    placeholder minting, boundaries, restore
│   └── substitute.py      scan_inbound / scan_outbound, request scoping
├── policy/              route profiles, compiled and fingerprinted
│   ├── profile.py         profile schema + compiler validation
│   ├── store.py           ControlPlane — compile, publish, hot-swap
│   ├── adapters.py        profile -> ScanOptions mapping
│   ├── enforcement.py     which fields are read, which are declared only
│   ├── profiles/          customer-support.json, internal-knowledge.json,
│   │                      decision-support.json, _base.json
│   └── jurisdictions/     eu / in / us regional floor definitions
├── decision/            allow / annotate / review / block
│   └── tiers.py           DecisionEngine, Signal, flag budget
├── audit/               hash-chained, tamper-evident record
│   └── chain.py
├── feedback/            review queue, session risk, policy tuning
│   ├── loop.py            3-reviewer consensus, proposal application
│   └── session.py         per-session risk counters
├── metrics/             canaries, Wilson intervals, flag rates
│   ├── canary.py
│   └── registry.py
├── cost/                gross / overhead / net
│   ├── ledger.py          budgets, attribution, savings report
│   └── pricing.py         published price book, token estimation
├── stream/              commit-point buffer, seam scanning
│   └── buffer.py
├── quality/             hallucination, toxicity, bias — the async pass
│   └── checks.py
├── demo/                the narrated pipeline + HTTP routes for the dashboard
│   ├── orchestrator.py    runs one request through every stage, emits events
│   ├── events.py          the event vocabulary the dashboard renders
│   └── server.py          FastAPI app, 20 /demo/* routes, curated presets
├── gateway/             the real OpenAI-compatible API
│   ├── app.py             FastAPI app — /v1/chat/completions, /v1/embeddings
│   ├── pipeline.py        GatewayPipeline
│   ├── context.py         per-request context
│   └── upstream.py        real + fake upstream model clients
└── seed/                synthetic customer records + traffic simulator
    ├── generate.py        deterministic record generation (70% governed / 30% not)
    └── traffic.py

dashboard/               Next.js — renders backend events only, computes nothing
└── src/
    ├── app/
    │   ├── page.js          Transit    — watch one request cross the line
    │   ├── policy/page.js   Profiles   — route profiles, live policy edits
    │   ├── queue/page.js    Review     — human-in-the-loop review queue
    │   ├── trust/page.js    Measures   — bias probing, canaries, metrics
    │   └── verify/page.js   Chain      — audit log, tamper demonstration
    ├── components/          Marked.js (span highlighting), Nav.js, Rail.js
    └── lib/api.js           the only place that talks to the backend

tests/                  513 tests, one directory per controlplane package
├── test_engine/          170   test_policy/     55   test_quality/   63
├── test_demo/             45   test_feedback/   27   test_gateway/   28
├── test_decision/         26   test_stream/     28   test_audit/     24
├── test_cost/             22   test_metrics/    25

scripts/
├── demo_roundtrip.py    prints a proof of the substitute/restore round trip
└── warm_demo.py         seeds the review queue for a live demo
```

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Backend / engine** | Python 3.13, stdlib only | The substitution engine ships with zero third-party dependencies by design — determinism on the synchronous path is a stated requirement, and an ML NER model would undercut it. |
| **API framework** | FastAPI + Uvicorn | Both the demo server and the OpenAI-compatible gateway are FastAPI apps; async-native, matches the streaming request path. |
| **Schema / validation** | Pydantic v2 | Request/response models for both HTTP surfaces. |
| **Frontend** | Next.js 16, React 19 | The dashboard — five pages, renders backend-computed events only, never re-derives a value the engine already computed. |
| **Styling** | Tailwind CSS v4 | Utility-first styling for the dashboard. |
| **Local model serving** | Ollama (`llama3.2:1b`) | The demo runs entirely offline against a local model — no API key, no network egress, real per-token log-probabilities for genuine hallucination confidence. |
| **Toxicity classifier** | `alt-profanity-check` 1.9.0 | The one deliberate exception to the stdlib-only rule: a small pretrained linear SVM over character n-grams, weights bundled in the package (~1MB) — no separate download, no network call at inference time. |
| **HTTP client (gateway tests)** | `httpx`, `openai` | The gateway's own test suite drives it with an unmodified `openai` client — the actual compatibility claim, verified. |
| **Testing** | `pytest` | 513 tests, no network and no API key required. |

---

## How to run

ControlPlane runs entirely locally. Three processes, three terminals.

### Prerequisites
- Python 3.13+
- Node.js 18+ (for the dashboard)
- [Ollama](https://ollama.com) (for the local model — only needed to actually generate responses; the test suite doesn't need it)

### 1 — Python environment
```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

### 2 — Local model (for live demo runs)
```bash
ollama serve
ollama pull llama3.2:1b
```

### 3 — Seed data (first run only)
```bash
python -m controlplane.seed.generate      # writes controlplane/seed/data/records.jsonl
```

### 4 — Run a server

**Demo server** (the narrated pipeline + dashboard's backend), on `:8000`:
```bash
python -m controlplane.demo.server
```

**OpenAI-compatible gateway** (the real integration surface), also on `:8000`:
```bash
python -m controlplane.gateway.app
```

Only run one of these at a time on the same port. Optionally warm the review queue for a live demo:
```bash
python scripts/warm_demo.py
```

### 5 — Dashboard
```bash
cd dashboard
npm install
npm run dev        # http://localhost:3000
```

### 6 — Tests
```bash
pytest -q          # 513 tests, offline, no API key required
```

### 7 — Prove the round trip without the dashboard
```bash
python scripts/demo_roundtrip.py
```

---

## API reference

### Gateway — `controlplane/gateway/app.py`

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/v1/chat/completions` | Streaming and non-streaming chat, OpenAI wire-compatible |
| `POST` | `/v1/embeddings` | Embeddings — the largest bulk-egress path in a RAG deployment |
| `GET` | `/healthz` | Liveness check |

### Demo server — `controlplane/demo/server.py`

| Route | Purpose |
|---|---|
| `POST /demo/run` | Runs one request through the full pipeline, streams every stage as an SSE event |
| `GET /demo/presets` | Curated demo prompts, each proving a specific claim |
| `GET /demo/health` | Whether the demo can actually run right now, and what's missing if not |
| `GET /demo/profiles` · `POST /demo/policy/patch` | Route profiles, and live policy edits with a before/after fingerprint diff |
| `GET /demo/jurisdictions` · `POST /demo/jurisdiction` | Regional floors and applying one across all profiles |
| `GET /demo/audit` · `POST /demo/audit/verify` · `POST /demo/audit/tamper` | The audit chain, its own verifier, and a live tamper demonstration |
| `GET /demo/session/{id}` · `POST /demo/session/{id}/forget` | Session risk counters, and proof that forgetting is a real operation |
| `GET /demo/queue` · `POST /demo/queue/resolve` · `POST /demo/queue/apply` | The human review queue and the feedback loop |
| `POST /demo/canary` · `GET /demo/metrics` | Run a canary sweep; the false-positive/false-negative report |
| `GET /demo/cost` | Gross saving, our own overhead, net — the cost ledger's report |
| `POST /demo/bias` | Counterfactual bias probing against an arbitrary prompt |
| `GET /demo/quality/status` | What the async quality pass runs, and what it deliberately doesn't |

---

## Dashboard guide

Five pages, each rendering events the backend already computed — nothing in the dashboard re-derives a value the engine produced.

| Page | Route | Shows |
|---|---|---|
| **Transit** | `/` | One request, live: what you sent, what the provider received, what the model wrote, what you read — side by side across the substitution boundary, plus session risk, the decision, the cost, and the full event tape. |
| **Profiles** | `/policy` | The three route profiles, their settings, which fields are enforced vs. declared-only, live policy edits with a fingerprint diff, and jurisdiction floor application. |
| **Review** | `/queue` | The human-in-the-loop queue — items awaiting a decision, and applying reviewer consensus back into policy. |
| **Measures** | `/trust` | Free-text bias probing, the canary sweep, and the false-positive/false-negative report. |
| **Chain** | `/verify` | The audit log, its hash-chain verification, and a live tamper demonstration that shows exactly where the chain breaks. |

### Screenshots — the dashboard, actually running

Every image below is a real capture of the live app against a local Ollama model, not a mockup. Screenshots also live in [demo-stills/readme/](demo-stills/readme/).

**Transit — before a request.** The composer, the reference-material box, and the eleven curated presets, each proving a specific claim (substitution, credential refusal, known-value matching over regex, and so on).

![Transit page before sending a request](demo-stills/readme/transit-overview.png)

**Transit — the substitution boundary, live.** This is the core of the product, side by side. Left: what you actually sent — `Priya Sharma` and her email, real. Right: what the model provider received — `[[CUST_A]]` and `[[EMAIL_A]]`, placeholders only, with a leak check confirming zero real values crossed. The model writes its answer against the placeholders (bottom-right); the answer restores the real values only on the way back (bottom-left), and the async quality pass has already caught something — the word "Balance" flagged at 73% confidence as unsupported by the source, using the model's own real per-token probability, not a self-report.

![The substitution round trip, both sides of the boundary](demo-stills/readme/transit-substitution.png)

**Transit — session, decision, evidence, cost.** Four panels beneath the boundary. *This session* shows cumulative risk with real budget meters (1 of 3 records touched, 0 of 40 agent steps) — no prompt or response stored, counters only. *Decision* shows why each finding resolved the way it did: both signals were mitigated by substitution, so the tier is Allow even though something matched. *After delivery* is the hallucination flag from the screenshot above, with the exact confidence formula shown, plus an honest list of what's deliberately not built (toxicity_sync, consistency sampling, per-response bias). *Cost* shows what was actually paid against the published price book, priced in ₹, with the baseline for comparison and the running session saving.

![Session risk, decision reasoning, quality findings, and cost, all in one row](demo-stills/readme/transit-panels.png)

**Profiles — three use cases, three compiled policies.** `customer-support`, `decision-support`, and `internal-knowledge`, each with a content fingerprint. Settings greyed with a **declared only** chip (like `hallucination tier` here) are fields the interface shows but the request path doesn't yet act on — labelled rather than silently absent.

![Three route profiles with their settings and fingerprints](demo-stills/readme/profiles.png)

**Review — the human-in-the-loop queue.** Six items awaiting a verdict, each showing only a category, a confidence, and *why* it was queued — never a prompt or a response. The override rate (0.0% here) is the number the team looks at first, because it's the one that says whether the system is trustworthy or just noisy.

![The review queue with pending items awaiting a reviewer verdict](demo-stills/readme/review.png)

**Measures — false positives measured, false negatives estimated.** A canary sweep just ran live against the real engine (not precomputed): synthetic secrets planted, then counted on the way back out. The cost panel repeats the gross/overhead/net split from Transit, now priced in rupees end to end, including the plain-text summary line the backend generates.

![Canary sweep results and the cost report, gross vs net](demo-stills/readme/measures.png)

**Chain — the audit log a person can actually verify.** One real entry, `audit_level: full`, expanded: policy fingerprint, decision tier, decision reasons, per-finding spans — and nothing else. No prompt, no customer name, no matched value anywhere in the payload, which is the whole point of hashing the entry rather than encrypting it.

![One audit chain entry, expanded, with hash chain intact](demo-stills/readme/chain.png)

---

## Engineering workflow

Built as two coordinated tracks against one written contract, so both halves could proceed without either waiting on the other:

1. **Portions, not tickets.** Work is cut into portions small enough that both tracks finish independently.
2. **The contract comes first.** The interface between tracks — schemas, the engine API, the placeholder format — is written down and agreed *before* either side writes code.
3. **Lane ownership.** Track A owns `controlplane/engine/**`; Track B owns `controlplane/gateway/**` and `controlplane/seed/**`. Crossing into the other's lane requires their agreement, recorded in the commit.
4. **Definition of done is a checklist, not a feeling** — specified per portion before work starts.

---

## Testing philosophy

**513 tests, all offline, no API key required.** Beyond coverage, every check on the request path carries a **mutation test**: the code is deliberately broken (a guard commented out, a condition flipped) and the test suite is confirmed to go red. A test that stays green while the code it guards is broken isn't a test — it's decoration. This standard applies to every synchronous check on the request path: substitution, decision tiers, credential blocking, the audit chain, and the cross-record disclosure check.

False positives are measured directly against real reviewer overrides. False negatives are estimated with seeded canaries and reported as a **Wilson confidence interval**, never a bare point estimate — a governance product's own uncertainty about its own detection rate is not something to round away.

---

## Deliberate non-goals

Not gaps — decisions, each with a reason, kept short and defended on purpose:

| Not built | Why |
|---|---|
| Semantic caching | The similarity threshold is a correctness risk, not a cost one — a false cache hit is a wrong answer to a different question. |
| A named-entity ML model on the synchronous path | Non-deterministic, and it would undercut the determinism claim the pattern/checksum floor is built on. |
| Per-response bias scores | Bias is a property of a *distribution*; a single response cannot carry one. |
| Prompt-injection detection on outbound requests | The model provider is better positioned to defend against its own prompt surface — this product's threat model is data leaving the building, not the model being tricked. |
| Multi-turn content memory | Would break the stateless design; cumulative risk counters do the job without the concentration-risk liability of a transcript store. |
| An LLM judging another LLM's output | Measures a second guess, not ground truth. |

---

## Team

| Role | Name |
|---|---|
| Team Leader | Indranil Saha |
| Team Member | Amritesh Kumar Singh |

**Accenture Innovation Challenge 2026 · Problem Track 1**
