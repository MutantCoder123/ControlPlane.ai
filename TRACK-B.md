# TRACK B — Gateway Spine + Seed Data (P1 + P13)

**You own:** `controlplane/gateway/**`, `controlplane/seed/**`, `tests/test_gateway/**`, `README.md`
**Your partner is on:** [TRACK-A.md](TRACK-A.md) — the substitution engine
**Shared interface:** [CONTRACTS.md](CONTRACTS.md) — read it first
**Design background:** IDEATION.md §1, §4, §8 · Drawbacks D28, D3, D2, D23

---

## Why this part matters

Two jobs that look like plumbing and are not.

**The gateway is the entire integration story.** Our pitch is that an enterprise
changes one line — its `base_url` — and nothing else. That claim is either true
in code or it is marketing. If an unmodified OpenAI SDK client works against
your server with only that one change, the claim holds and a judge can verify it
in ten seconds.

**The seed data is load-bearing, not scaffolding.** Track A's engine has nothing
to match against without it, and two later parts (metrics, dashboard) have
nothing to display. It is also where **D28** gets answered: the brief assumes "a
mix of well-governed and loosely governed internal data sources," and your seed
set is how we *demonstrate* graceful degradation instead of claiming it.

---

## Part 1 — Seed data (`controlplane/seed/`)

Do this first. Track A is building against the schema and will want real records
as soon as they exist.

### `seed/generate.py`

Emit `seed/data/records.jsonl` in the CONTRACTS §2 schema. Deterministic —
**seed the RNG with a fixed value** so the demo is reproducible from a clean
checkout. Every number we show a jury must be reproducible from the repo rather
than quoted from a vendor report.

Generate roughly:

- **~200 customer records** — name, email, phone, account number, balance
- **~50 employee records** — name, employee ID, salary, manager
- A handful of **credential-shaped strings** for the block path

### Getting `role` right — this is D16

Every field is `"identifier"` or `"operand"`:

- **identifier** — name, email, phone, employee ID, account number *when it
  identifies*
- **operand** — salary, balance, transaction amount, any number the model may
  need to compute with

This distinction is why our substitution doesn't break arithmetic (IDEATION
§9.4). It lives in the data on purpose: if the engine has to infer it at
runtime, it will get it wrong, and we lose *"break the linkage, preserve the
arithmetic."*

### Getting `governance` right — this is D28

Mark ~70% `"governed"` and ~30% `"ungoverned"`.

Only governed records go into the known-value store. The ungoverned ones exist
so we can show what happens at the edge of governance: the pattern+checksum tier
still catches a card number in an ungoverned record, but there is no
`record_ref`, so the audit line is weaker. **Coverage degrades gracefully rather
than falling to zero** — and being able to *show* that beats asserting it.

Include at least one deliberate landmine: **a test-looking card number
(`4111 1111 1111 1111`) that passes Luhn but belongs to no record.** Track A has
a test asserting it does not fire. That single case is the clearest proof that
known-value matching beats regex.

### `seed/traffic.py` — the simulator

Generate synthetic request traffic across the three profiles the brief names,
at the volume we committed to in IDEATION §24.3:

- **~30,000 interactions/week** — about 3/minute average
- Mix: **~60% internal assistant, ~30% customer support, ~10% decision support**

For Portion 1 this only needs to write a JSONL of plausible prompts — some
clean, some containing seeded records, some containing credentials. Later parts
(metrics, dashboard) will consume it. Keep it boring and deterministic.

---

## Part 2 — Gateway spine (`controlplane/gateway/`)

### `gateway/app.py` — the FastAPI server

- `POST /v1/chat/completions` — streaming **and** non-streaming
- `POST /v1/embeddings` — **D2.** One extra route, about an hour. A RAG rollout
  ships the entire document corpus to the provider through this endpoint at
  ingestion; a chat-only proxy never sees the largest bulk egress in the whole
  deployment. Cheaper to cover than to defend in Q&A, and visible in the repo as
  evidence we thought past chat completions.
- `GET /healthz`

**Wire-compatible with OpenAI.** The test that matters is an unmodified
`openai` Python client pointed at `base_url="http://localhost:8000/v1"`.

### `gateway/context.py` — request context

Per-request object carrying: request id, API key → team, **profile name**,
timestamps, token counts, findings.

Read the profile from a header (`X-ControlPlane-Profile`) with a config default.
**Do not build the profile engine** — that is P2, a later portion. For now a
plain string that gets recorded and passed through. Leave a labelled stub:

```python
# Portion 1: profile is a passthrough label only.
# The compiled policy artefact + hot-swap lands in P2 — see BUILD-PLAN.md.
```

### `gateway/upstream.py` — the provider client

Async HTTP client to the real provider. Keep the provider behind a small
interface so a fake can be injected in tests — **your test suite must not
require a live API key or network.**

**D3, stated honestly:** "one line" is literal for OpenAI-compatible endpoints
and a config block for Bedrock (SigV4) and Azure OpenAI (deployment names).
Build the OpenAI-compatible path; put the other two in the README as a config
concern. Do not overclaim in code comments or README.

### `gateway/pipeline.py` — where the two tracks meet

The one function that joins your half to Track A's:

```
request → engine.scan_inbound(prompt)
        → if blocked: refuse at cost_usd 0.0, NEVER dispatch
        → dispatch scanned.text upstream
        → engine.restore(response, scanned.mapping)
        → return to caller
```

**The refusal must happen before dispatch, and this is the point of the whole
ordering** (IDEATION §8). You are billed the moment tokens are generated, so
forwarding first and cancelling on failure means you block the request *and*
still pay. Check first, dispatch second — that is what makes the cost pillar
real instead of contradicting the safety pillar.

Import **only** the four names in CONTRACTS §3. In particular: **never hardcode
Track A's placeholder format.** If you need to recognise one, import
`PLACEHOLDER_RE` or `is_placeholder`. Hardcoding it is a live D15 bug even on
the day it happens to work.

### `scripts/demo_roundtrip.py`

The acceptance artefact. For a prompt containing a seeded customer, print:

1. the prompt **as the upstream provider saw it** — placeholders only
2. the final answer returned to the caller — real values restored
3. any arithmetic in the answer, still correct

That is demo step 3, *"the whole pitch in fifteen seconds,"* proved from a
terminal.

---

## Part 3 — README.md (yours to own)

Round 2 requires a public repo with a README documenting approach and
architecture. **D23 is your drawback:** on a public repo, anything the README
claims that the code does not contain reads as vapour to a reviewer who opens
it.

So: stubs are fine, **unmarked stubs are not.** Every part we have not built yet
gets a line saying so, in the README and in the code, in the same words. An
honest `# not implemented in Portion 1 — see BUILD-PLAN.md P8` scores better
than an empty function where a feature was promised. Costs an hour, removes a
whole class of reviewer suspicion.

Include: what it is, the one-line integration claim, how to run it, the
architecture sketch, and an explicit **"not built yet"** section pointing at
BUILD-PLAN.md.

---

## Done when

```bash
pytest tests/test_gateway/ -v            # green, no network needed
python -m controlplane.seed.generate     # writes records.jsonl
python -m controlplane.gateway.app       # serves on :8000
python scripts/demo_roundtrip.py         # prints the proof
```

Plus: an unmodified `openai` client works against it with only `base_url`
changed, streaming included.

---

## Do not build

- **The profile engine** (P2) — passthrough string only for now.
- **The commit-point buffer** (P4). Stream straight through in Portion 1 and
  leave the labelled seam where it will go. Buffering is a *route-profile
  property*, not a global one (D6), and that only makes sense once P2 exists.
- **Audit log, decision tiers, metrics, cost ledger, dashboard** — P8, P6, P10,
  P11, P12. Later portions.
- **Envoy, gRPC, Rust, C++.** The check costs milliseconds in any language; the
  model call costs 1–2 seconds. Buys nothing measurable, costs two days.

---

## Where you meet Track A

- **They consume** your `records.jsonl`. Get the schema right early and tell
  them the moment the first real file lands — they are working against a
  hand-written fixture until then.
- **They implement** the four names in CONTRACTS §3; you call exactly those.
- **They own the placeholder format** and may change it. That is why you must
  never hardcode it (CONTRACTS §4).
- **They cannot start restoration testing properly** without realistic records,
  so seed data genuinely is your critical path — do it before the gateway.

**Tell them immediately if** the schema needs a field, or `ScanResult` doesn't
give you what the pipeline needs. Change CONTRACTS.md together first, then code.
