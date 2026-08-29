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

| Part | State |
|---|---|
| Substitution engine (P3) | 🔨 Portion 1 — Track A |
| Gateway spine (P1) | 🔨 Portion 1 — Track B |
| Seed data + traffic simulator (P13) | 🔨 Portion 1 — Track B |
| Profile engine / control plane (P2) | ⬜ not started |
| Commit-point buffer (P4) | ⬜ not started |
| Decision tiers + HITL (P6) | ⬜ not started |
| Async quality checks (P7) | ⬜ not started |
| Hash-chained audit log (P8) | ⬜ not started |
| Feedback loop (P9) | ⬜ not started |
| Metrics + canaries (P10) | ⬜ not started |
| Cost ledger (P11) | ⬜ not started |
| Dashboard (P12) | ⬜ not started |

Scope and ordering: [BUILD-PLAN.md](BUILD-PLAN.md).

---

## Documents

| File | What it is |
|---|---|
| [IDEATION.md](IDEATION.md) | The design — what we are building and why |
| [DRAWBACK.md](DRAWBACK.md) | Internally honest gaps, weaknesses and accepted trade-offs |
| [BUILD-PLAN.md](BUILD-PLAN.md) | The fourteen parts, sized and ordered |
| [CONTRACTS.md](CONTRACTS.md) | **The interface between the two tracks — read before coding** |
| [TRACK-A.md](TRACK-A.md) | Brief: substitution engine |
| [TRACK-B.md](TRACK-B.md) | Brief: gateway spine + seed data |
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
