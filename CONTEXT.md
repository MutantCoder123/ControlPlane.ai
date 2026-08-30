# CONTEXT — the whole project in one file

**What this is for.** A single self-contained brief you can hand to a fresh
session, a new model, or a teammate joining mid-stream. Everything below is
*state*: what exists, what it does, what is decided, and what is left. The
reasoning lives in the linked documents; this file is the map.

Last updated: 2026-08-30 · **377 tests green** on Track A alone, ~405 with
Track B merged. Phase 6 part one (the dashboard) is built.

---

## 1. The project in five lines

**ControlPlane** — an LLM governance gateway, built for the Accenture
Innovation Challenge 2026, Problem Track 1.

It sits between an organisation's applications and any LLM provider. Every
request and response passes through it. The application changes one line — its
`base_url` — and nothing else.

> The layer that lets a regulated organisation put real company data into a
> third-party model, without the sensitive parts ever leaving the building.

**Who buys it:** the person currently *blocking* AI adoption — the compliance
officer, the CISO, the data protection lead. We turn their "no" into a "yes."

---

## 2. The five load-bearing ideas

Break any of these by being helpful and the project loses its argument.

| # | Idea | Why it matters |
|---|---|---|
| 1 | **Stateless by design** | No conversation store, no request DB. "We retain nothing, and you can verify that" is what earns a light security review and lets us sit in the request path at all. A gatekeeper that fails is degraded; a memory store that leaks is catastrophic. |
| 2 | **Split by reversibility, not speed** | Credentials and PII are irreversible once rendered → checked *synchronously, before release*. Hallucination and bias are reversible → annotated *asynchronously*. This dissolves the usual safety-vs-latency argument. |
| 3 | **Substitution, not redaction** | Real values swapped for placeholders before dispatch, swapped back on return. The provider never receives personal data *at all* — a far stronger claim than "we redact when we detect" — and the answer stays complete and useful. |
| 4 | **Substitute identifiers, never operands** | Sensitivity lives in the *linkage*. `₹45,230` alone is meaningless; *"Priya's salary is ₹45,230"* is not. Swap the name, pass the number: **break the linkage, preserve the arithmetic.** |
| 5 | **Known-value matching** | Regex asks *"does this look like a secret?"* We ask *"is this **our** secret?"* The audit line becomes *"matched customer record 44219"* instead of *"matched a regex."* Everything else in ControlPlane exists in other products. This does not. |

Full reasoning: [IDEATION.md](IDEATION.md) §3, §6, §9.2–§9.4.

---

## 3. What is built, right now

Python 3.13 · FastAPI at the edge · **stdlib-only engine** · pytest.

### Track A — `controlplane/` (complete through Phase 5)

| Package | What it does | Part |
|---|---|---|
| `engine/` | Substitution engine: known-value store + Bloom filter, checksum patterns (Luhn / Verhoeff / mod-97), placeholder mint & restore, `RequestScope` for placeholder identity across a multi-part request | P3 |
| `policy/` | Route profiles compiled to fingerprinted artefacts, hot-swappable | P2 |
| `audit/` | Hash-chained append-only log — tamper-**evident**, not tamper-proof | P8 |
| `decision/` | Four tiers — allow / annotate / review / block — resolved from severity × confidence × profile | P6 |
| `feedback/` | Reviewer outcomes → threshold adjustment, in the *control* plane only | P9 |
| `metrics/` | Seeded canaries, Wilson-interval FN estimation, metric registry | P10 |
| `cost/` | Gross / overhead / net ledger — the flattering number cannot be read alone | P11 |
| `stream/` | Commit-point buffer: sentence / 40 tokens / 250 ms, with overlap window | P4 |
| `quality/` | Async post-hoc checks (thin by design) | P7 |
| `demo/` | Instrumented pipeline: one typed event per stage, so the dashboard renders what the modules returned rather than recomputing it | P14 |

### The dashboard — `dashboard/` (Next.js)

Five pages over the demo event stream. The design is one idea: **there is a
line, and real data does not cross it.** A hatched rule runs down the centre
of the screen - inside the building on the left, the provider on the right -
and colour temperature encodes which side a value is on. Warm sand is a real
value and never renders on the right; cold slate is a placeholder and is the
only thing that crosses. The round trip is a temperature journey you can
follow with the sound off.

Transit (the round trip, live) · Profiles (hot-swap, fingerprint, diff) ·
Review (verdict to policy change) · Chain (verify, then tamper) · Measures
(canaries, cost, bias - each with what it cannot tell you).

### Track B — `controlplane/gateway/`, `controlplane/seed/` (teammate)

FastAPI spine (`/v1/chat/completions` streaming and non-streaming,
`/v1/embeddings`, `/healthz`), request context, upstream client behind an
injectable interface, the pipeline that joins the halves, and the deterministic
250-record seed generator.

**Reviewed and verified:** merges with zero conflicts, 384 tests pass, seed
output conforms to CONTRACTS §2 exactly, and the engine matches against their
real data (`customer:44219` fires; the Luhn-valid landmine card does not).
Awaiting PR merge from their fork.

---

## 4. Where the two halves meet

[CONTRACTS.md](CONTRACTS.md) is the only thing keeping them compatible. Neither
side changes it unilaterally.

- **§1 file ownership.** `README.md` moved A-ward on 2026-08-30 after A had been
  editing it for four phases without asking — recorded rather than quietly fixed.
- **§2 seed schema.** Every field carries `role` (identifier / operand — idea #4
  encoded in the data so the engine never guesses at runtime) and `governance`
  (governed / ungoverned, ~70/30 — only governed records enter the store, so we
  can *show* graceful degradation instead of claiming it).
- **§3 the engine API** — the four names Track B may import, plus `RequestScope`.
- **§4 Track A owns the placeholder format.** It is `[[CUST_A]]`. Track B must
  never hardcode it — import `PLACEHOLDER_RE` or `is_placeholder`.

**The pipeline order is the argument, not an implementation detail:**

```
request → scan_inbound → if blocked: refuse at cost 0.00, NEVER dispatch
                       → dispatch placeholders upstream
                       → restore on the way back
```

You are billed the moment tokens are generated. Forwarding first and cancelling
on failure blocks the request *and* still pays for it. Check first, dispatch
second — that is what makes the cost pillar real instead of contradicting the
safety pillar.

---

## 5. What is deliberately **not** built

Not omissions — triaged decisions, in [DRAWBACK.md §0](DRAWBACK.md). The finale
is a 10-minute pitch and 5-minute Q&A, so a weakness that gets *asked about*
needs a good answer, not an implementation.

| Not built | Why |
|---|---|
| Semantic caching (D13) | The similarity threshold is a **correctness** risk, not a cost one — too loose and you serve the answer to a different question. Exact-match prefix hashing instead. |
| NER model (D10) | Non-deterministic and slow on the synchronous path; it would undo the determinism claim that makes our detection tier credible. Gap stated openly in prose. |
| Real-time bias detection (D12) | Structurally impossible on a single response in isolation. |
| Multi-turn state (D4) | Breaks the statelessness positioning, which is idea #1. |
| Envoy / gRPC / Rust | The check costs milliseconds in any language; the model call costs 1–2 seconds. Buys nothing measurable, costs two days. |

---

## 6. The honest weaknesses

Kept in [DRAWBACK.md](DRAWBACK.md), D1–D28, each with severity, status and a
decision to *fix* or *answer*. The ones that shape everything:

- **False positives are measured; false negatives are estimated.** FN comes from
  seeded canaries with a Wilson confidence interval, and the caveat is enforced
  in `__str__` so the number cannot be quoted without it.
- **Over-flagging is tuned, not solved.** We ship a flag budget and say so.
- **The audit log is tamper-evident, not tamper-proof.** Prototype honesty.
- **"One line" is literal for OpenAI-compatible endpoints**, a config block for
  Bedrock (SigV4) and Azure OpenAI (deployment names). Stated, not overclaimed.
- **D23, split in two.** D23a — unmarked stubs in code (Track B). D23b — docs
  asserting what the code or repo does not do (Track A). The second half exists
  because we had a rule for the README lying about the code and none for the
  docs lying about the repo — which is what a new reader hits first.

---

## 7. Phases — done and remaining

| Phase | Parts | State |
|---|---|---|
| 1. Portion 1 | P3 (A) · P1 + P13 (B) | A ✅ · B ✅ *(pending merge)* |
| 2. Policy & Audit | P2, P8 | ✅ |
| 3. Decision & Feedback | P6, P9 | ✅ |
| 4. Measurement & Cost | P10, P11 | ✅ |
| 5. Stream & Quality | P4, P7 | ✅ |
| 6. Surface & Delivery | P12 dashboard | ✅ |
| **6. Surface & Delivery** | **P14 demo cut** | **in progress — the only work left** |

P5 (pre-flight gate) is orchestration over Track B's gateway and lands with
integration rather than as a phase of its own.

---

## 8. How the two of us work

[WORKFLOW.md](WORKFLOW.md). Two rules do most of the work:

**Stay in your lane.** If you need a change in the other person's files, ask
them to make it. A lane crossing is invisible while you are alone on a branch,
so the check has to happen at review time, on the checklist, every time.

**"Can this test fail?"** Portion 1 shipped eight bugs past a green suite; half
were green because of *how the test was written*, not because the code worked.
Four failure shapes are now on the review checklist — built from its own output ·
transport, not logic · no assertion · acceptance script that exits 0 regardless.
The test for a test: **make the code wrong on purpose and watch it go red.**

---

## 9. The fifteen seconds that are the whole pitch

Demo step 3: paste a real customer record, get a correct and useful answer, then
show that the provider only ever saw a placeholder — and that the arithmetic in
that answer is still right.

Everything else in this repo is in service of that moment.

---

## 10. Where to go next

| You want | Read |
|---|---|
| Design and reasoning, 24 sections | [IDEATION.md](IDEATION.md) |
| Every known weakness, with triage | [DRAWBACK.md](DRAWBACK.md) |
| The interface between the tracks | [CONTRACTS.md](CONTRACTS.md) |
| Parts, sizes, dependencies | [BUILD-PLAN.md](BUILD-PLAN.md) |
| How we collaborate | [WORKFLOW.md](WORKFLOW.md) |
| Joining without the design context | [ONBOARDING.md](ONBOARDING.md) |
| Feature list for UI/UX generation | [FEATURE_CONTEXT.md](FEATURE_CONTEXT.md) |
| Per-track build briefs | [TRACK-A.md](TRACK-A.md) · [TRACK-B.md](TRACK-B.md) |
| The dashboard: audit, design, build order | [PHASE-6-PLAN.md](PHASE-6-PLAN.md) |
