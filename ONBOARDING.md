# ONBOARDING — start here

Written for whoever joins without having been in the design conversation.
Right now that means **Track B**. Read this once, end to end, before writing
code. It is about twenty minutes and it will save you a day.

---

## 1. What this is

**ControlPlane** — our entry for the Accenture Innovation Challenge 2026,
Problem Track 1.

A gateway that sits between an organisation's applications and any LLM
provider. Every request and response passes through it. The application changes
one line — its `base_url` — and nothing else.

> The layer that lets a regulated organisation put real company data into a
> third-party model, without the sensitive parts ever leaving the building.

**Who buys it:** the person currently *blocking* AI adoption — the compliance
officer, the CISO, the data protection lead. We turn their "no" into a "yes."
That framing matters, because Accenture's actual business is helping large
regulated organisations adopt technology, and a judge from that world
recognises "legal won't sign off" instantly.

### What we are being judged on

- **Round 2** wants a working prototype, a README documenting architecture, a
  demo video, and a **public GitHub repo with source code**. The code is
  judged, not just the demo.
- **The Grand Finale** is a **10-minute pitch plus 5-minute Q&A** in Bengaluru.
- **Round 3** puts us in front of Accenture practitioners who deploy into
  regulated enterprises for a living.

Two consequences shape every decision in this repo: a weakness that gets *asked
about* needs a good answer rather than an implementation, and anything the
README claims that the code does not contain reads as vapour to a reviewer who
opens it.

---

## 2. The five ideas you should not accidentally break

These came out of a long design process. Each has a reason that is not obvious
from the code, and each is easy to undo by being helpful.

**1 — We are stateless, and that is the positioning, not a limitation.**
We store no conversation history, no user context. Our value is "we retain
nothing, and you can verify that" — it is what earns a light security review and
lets us sit in the request path at all. A gatekeeper that fails is *degraded*;
a memory store that leaks is *catastrophic*. **Do not add a database of
requests.** (IDEATION §3)

**2 — Checks are split by whether the harm can be undone, not by how fast they
are.** Credentials and PII are irreversible once rendered — someone can screen
record them — so they are checked *synchronously, before release*. Hallucination
and bias are reversible, so they are annotated afterwards, asynchronously. This
dissolves the usual safety-vs-latency argument. (IDEATION §6)

**3 — Substitution, not redaction.** We swap real values for consistent
placeholders before dispatch and swap them back on the way out. The provider
never receives real personal data *at all* — a much stronger compliance claim
than "we redact when we detect" — and the answer stays complete and useful.
(IDEATION §9.3)

**4 — Substitute identifiers, never operands.** Sensitivity lives in the
*linkage*, not the value. `₹45,230` alone is meaningless; *"Priya's salary is
₹45,230"* is sensitive because of the name. Swap the name, let the number
through, and the model's arithmetic is still correct. *Break the linkage,
preserve the arithmetic.* (IDEATION §9.4)

**5 — Known-value matching is the differentiator.** Regex asks "does this look
like a secret?" We ask "is this **our** secret?" — because the organisation
already knows its own sensitive data. That flips every weakness of regex at
once, and the audit line becomes *"matched customer record 44219"* instead of
*"matched a regex."* Everything else in ControlPlane exists in other products.
This does not. (IDEATION §9.2)

---

## 3. What to read, in what order

| Order | File | Why | Time |
|---|---|---|---|
| 1 | this file | context | 20 min |
| 2 | [WORKFLOW.md](WORKFLOW.md) | how we work together | 10 min |
| 3 | [CONTRACTS.md](CONTRACTS.md) | **the interface — non-negotiable** | 15 min |
| 4 | [TRACK-B.md](TRACK-B.md) | your build brief | 20 min |
| 5 | [BUILD-PLAN.md](BUILD-PLAN.md) | where your part sits in the whole | skim |

Reference as needed, not up front:

- [IDEATION.md](IDEATION.md) — the full design, 24 sections. Read §1, §5, §9 now;
  the rest when something references it.
- [DRAWBACK.md](DRAWBACK.md) — every known weakness, with severity and a
  decision about whether we fix it or answer it. **§0 is the triage** and
  explains why we deliberately do not build several obvious things.

---

## 4. Setup

```bash
git clone https://github.com/MutantCoder123/ControlPlane.ai.git
cd ControlPlane.ai

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
pytest                          # should collect cleanly

git checkout -b track-b/gateway-and-seed
```

Every module you will touch already exists as a labelled stub telling you which
brief section covers it.

---

## 5. Your first day

Three tasks, in this order. **The order is deliberate** — the first one unblocks
your teammate.

### Task 1 — `controlplane/seed/generate.py`

Your partner's engine has nothing to match against until this exists, and they
are currently working against a hand-written five-record fixture. This is your
critical path even though it looks like scaffolding.

Write `seed/data/records.jsonl` in the [CONTRACTS.md §2](CONTRACTS.md) schema.
Fix the RNG seed — every number we show a jury must reproduce from a clean
checkout, not be quoted from a vendor report.

Two fields carry real design decisions, both explained in TRACK-B.md:

- **`role`** — `identifier` or `operand`. This is idea #4 above, encoded in the
  data so the engine never has to guess at runtime.
- **`governance`** — `governed` or `ungoverned`, roughly 70/30. Only governed
  records enter the known-value store. The ungoverned ones exist so we can
  *show* that coverage degrades gracefully at the edge of governance instead of
  claiming it.

Include the landmine: `4111 1111 1111 1111` — a card number that passes the Luhn
check but belongs to no record. Track A has a test asserting it does **not**
fire. That single case is the clearest proof that known-value matching beats
regex.

**Tell Track A the moment this file exists.**

### Task 2 — `controlplane/seed/traffic.py`

Synthetic prompts across the three use cases at the volume we committed to:
~30,000/week, ~60% internal assistant / ~30% customer support / ~10% decision
support. Some clean, some containing seeded records, some containing
credentials. Boring and deterministic is correct here.

### Task 3 — the gateway

`gateway/app.py`, `context.py`, `upstream.py`, `pipeline.py`. Full detail in
[TRACK-B.md](TRACK-B.md).

The test that matters: an **unmodified** `openai` Python client works against
your server with only `base_url` changed. That is our entire integration claim,
either true in code or just marketing.

---

## 6. The drawbacks you own

Every part of this project carries named weaknesses. Yours:

| ID | What | What you do about it |
|---|---|---|
| **D23** | A public repo makes unmarked stubs a liability | Label every gap in code *and* README, same words. You own the README |
| **D28** | "Loosely governed sources" undercut our inherit-their-classification story | The governed/ungoverned split in your seed data is the answer |
| **D2** | Embeddings bypass a chat-completions proxy | Add `/v1/embeddings`. ~1 hour, and it covers the largest bulk egress in a RAG rollout |
| **D3** | "One line" is not literal for Bedrock/Azure | Build the OpenAI-compatible path; say so honestly in the README. Do not overclaim |

Read their full entries in [DRAWBACK.md](DRAWBACK.md) before you start — the
reasoning is the useful part.

---

## 7. Things that will feel wrong but are deliberate

You will hit these and want to fix them. Don't — each was decided with reasons.

- **No buffering in Portion 1.** The commit-point buffer is P4, and it only
  makes sense once route profiles exist, because buffering is a *per-profile*
  property rather than a global one. Stream straight through and leave the seam.
- **`profile` is just a string.** The real policy engine is P2. Passthrough
  label for now.
- **No audit log yet**, even though the design leans on it heavily. That is P8.
- **No semantic caching, ever.** The similarity threshold is a *correctness*
  risk, not a cost one — too loose and you serve the answer to a different
  question. We ship exact-match prefix hashing instead. (D13)
- **No NER model.** It would be non-deterministic and slow on the synchronous
  path, and it undoes the "deterministic" claim that makes our detection tier
  credible. The gap is stated openly in prose. (D10)

The full reasoning for all of these is [DRAWBACK.md §0](DRAWBACK.md).

---

## 8. Where to push back

This design has been reworked several times, including a significant reordering
when the Round 2 brief arrived. It is not settled scripture.

Push back — loudly — if:

- The contract does not fit what you actually need. That is a **CONTRACTS.md
  change, agreed together, before the code.**
- Something in the "do not build" list looks genuinely necessary. Make the case;
  the triage has changed before.
- A claim in the docs is not true of the code. That is D23 and it is the single
  most damaging thing on a public repo.

What must not happen is you silently working around a bad contract. That is how
two halves stop fitting together.

---

## 9. The one thing to remember

Demo step 3 is fifteen seconds long and it is the entire pitch: paste a real
customer record, get a correct and useful answer, then show that the provider
only ever saw a placeholder.

Your seed data and your gateway are two of the four parts that moment depends
on. Everything else in this repo is in service of it.
