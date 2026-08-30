# ControlPlane

**Accenture Innovation Challenge 2026 · Problem Track 1: ControlPlane.ai**

A gateway that sits between an organisation's applications and any LLM
provider. Every request and response passes through it. The application changes
one line — its `base_url` — and nothing else.

> The layer that lets a regulated organisation put real company data into a
> third-party model, without the sensitive parts ever leaving the building.

---

## Status — Portion 1 in progress

> **This README is owned by Track B and is deliberately honest about what does
> not exist yet.** On a public repo, a claim the code does not contain reads as
> vapour. See D23 in [DRAWBACK.md](DRAWBACK.md).

| Part | State | Tests |
|---|---|---|
| Substitution engine (P3) | ✅ done | 150 |
| Profile engine / control plane (P2) | ✅ done | 28 |
| Hash-chained audit log (P8) | ✅ done | 25 |
| Gateway spine (P1) | 🔨 Track B | |
| Seed data + traffic simulator (P13) | 🔨 Track B | |
| Decision tiers + HITL (P6) | ✅ done | 24 |
| Feedback loop (P9) | ✅ done | 22 |
| Metrics + canaries (P10) | ✅ done | 22 |
| Cost ledger (P11) | ✅ done | 25 |
| Commit-point buffer (P4) | ✅ done | 28 |
| Async quality checks (P7) | ✅ done (thin) | 22 |
| Dashboard (P12) | ⬜ next | |

Scope and ordering: [BUILD-PLAN.md](BUILD-PLAN.md).

---

## Documents

**New to the project? → [ONBOARDING.md](ONBOARDING.md)**

| File | What it is |
|---|---|
| [ONBOARDING.md](ONBOARDING.md) | **Start here** — context, setup, first day |
| [WORKFLOW.md](WORKFLOW.md) | How the two tracks work together |
| [CONTRACTS.md](CONTRACTS.md) | **The interface between the tracks — read before coding** |
| [TRACK-A.md](TRACK-A.md) | Brief: substitution engine |
| [TRACK-B.md](TRACK-B.md) | Brief: gateway spine + seed data |
| [IDEATION.md](IDEATION.md) | The design — what we are building and why |
| [DRAWBACK.md](DRAWBACK.md) | Internally honest gaps, weaknesses and accepted trade-offs |
| [BUILD-PLAN.md](BUILD-PLAN.md) | The fourteen parts, sized and ordered |
| [Implementation.md](Implementation.md) | Approach trade-offs per technique |

---

## Getting started

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Portion 1 is done when this works from a clean checkout:

```bash
python -m controlplane.seed.generate      # writes seed/data/records.jsonl
python -m controlplane.gateway.app        # serves on :8000
python scripts/demo_roundtrip.py          # prints the proof
```

---

## What works today

```python
from controlplane.policy.store import ControlPlane
from controlplane.audit.chain import AuditLog, attach_to_store
from controlplane.engine.substitute import SubstitutionEngine

cp    = ControlPlane()
store = cp.store(default_profile="internal-knowledge")
log   = AuditLog(); attach_to_store(log, store)
eng   = SubstitutionEngine("tests/test_engine/fixtures/records.jsonl")

scanned = eng.scan_inbound("Refund Priya Sharma on account 5010 0234 5678 90.")
scanned.text
# 'Refund [[CUST_A]] on account [[ACCT_A]].'   <- what the provider receives

# change policy live, no restart; the diff writes itself to the audit chain
store.publish(cp.compile_bundle(overrides={"internal-knowledge": {"cost": {"cache_enabled": False}}}))
log.verify()          # VerificationResult(ok=True, ...)
```

The same finding resolves differently per profile — public-facing output
justifies stopping earlier than an internal assistant does:

```
SAME FINDING (confidence 0.80), THREE PROFILES:
  customer-support     block_at=0.75  ->  BLOCK
  decision-support     block_at=0.85  ->  REVIEW
  internal-knowledge   block_at=0.90  ->  REVIEW
```

And the loop closes — four reviewer overrides retune the policy, and the next
identical request is allowed, with a readable diff on the audit chain:

```
BEFORE feedback : review
override rate   : 100% over 4 reviews
applied         : 4 of 4 reviews overturned pattern:payment_card
AFTER feedback  : allow (exempted by policy)
audit diff      : {'decision.exempt': ['[]', "['pattern:payment_card']"]}
```

And the number at the end of the pitch — gross, our own overhead, and net,
because a saving figure that hides its own cost is not a saving figure:

```
1000 requests | baseline (claude-opus-5) $16.7488 -> actual $5.7006
             | gross $11.0482 - our overhead $0.15 = NET $10.8982
             (prices as of 2026-06-24)

canary catch rate 100.0% (80/80, 95% CI 95.4%-100.0%)
  on seeded distribution {'aadhaar': 10, 'api_key': 20, 'iban': 10, 'payment_card': 40}
  - says nothing about categories we did not seed
```

The credential is never transmitted — not deleted after, never sent. The
stream stops mid-flight, and a secret split across chunk boundaries still
cannot escape:

```
CLEAN STREAM  : Dear Priya Sharma, your refund of 45230 is approved. ...
LEAKY STREAM  : ''  -> blocked: credential in response: api_key
HALLUCINATION : not found in the source material: 2019, 45230, Circular
BIAS PROBE    : same request, name changed (Priya -> Rajesh): reject -> advance
                -> disparity 1.00 across 40 runs
```

---

## Working agreement

Two tracks, strict file ownership, one shared contract.

- **Track A** owns `controlplane/engine/**` and `tests/test_engine/**`
- **Track B** owns `controlplane/gateway/**`, `controlplane/seed/**`,
  `tests/test_gateway/**`, and this README
- **[CONTRACTS.md](CONTRACTS.md)** is edited only by agreement, and always
  *before* the code that depends on the change

Stay in your lane and merge conflicts mostly disappear.

### Branches

```bash
git checkout -b track-a/substitution-engine    # Track A
git checkout -b track-b/gateway-and-seed       # Track B
```

Open a PR into `main` when your half of Portion 1 is green.

---

## Not built, on purpose

Listed here so nobody has to guess whether a gap is an oversight:

- **NER model for unstructured PII** — the prototype uses known-value matching
  plus a pattern+checksum tier. Exact-match only, stated as a limitation (D9, D10).
- **Semantic caching** — the similarity threshold is a correctness risk, not a
  cost one. We ship exact-match prefix hashing instead (D13).
- **Real-time bias detection** — structurally impossible. Bias is a property of
  a distribution, not of one response; we measure it in aggregate (D12).
- **Multi-turn / agentic state** — out of prototype scope; the answer is
  architectural, not a feature (D4).
- **Envoy / Rust hot path** — the check costs milliseconds, the model call costs
  seconds. Buys nothing measurable.

Full reasoning for each: [DRAWBACK.md](DRAWBACK.md).
