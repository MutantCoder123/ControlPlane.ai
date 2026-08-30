# ControlPlane — Build Plan

**Purpose:** break the design into parts small enough to pick up one at a time.
Each part names the drawbacks it owns, the Round 2 solutioning area it
satisfies, and what "done" means. Nothing here is a decision to build
everything — §5 lists what we deliberately do not build.

Companions: [IDEATION.md](IDEATION.md) (what and why) ·
[DRAWBACK.md](DRAWBACK.md) (what is weak) ·
[Implementation.md](Implementation.md) (approach trade-offs per technique).

Last updated: 2026-08-29.

---

## 1. The fourteen parts

| ID | Part | Size | Depends on | Verdict | Drawbacks owned |
|---|---|---|---|---|---|
| **P1** | Gateway spine | M | — | 🔨 Track B | D3 |
| **P2** | Profile engine (control plane) | M | — | ✅ **done** | **D20**, D6 |
| **P3** | Substitution engine | L | *none — library* | ✅ **done** | **D15**, D9, D10, D16 |
| **P4** | Outbound stream guard | M | P1 | **build** | D5, D6 |
| **P5** | Pre-flight gate | S | P1 P2 P3 | **build** | — |
| **P6** | Decision engine (tiers + HITL) | M | P2 | ✅ **done** | **D26** |
| **P7** | Async quality checks | M | P1 | **thin build** | D11, D12, D27 |
| **P8** | Audit log | S | *none — library* | ✅ **done** | D14 |
| **P9** | Feedback loop | M | P6 P8 | ✅ **done** | **D24**, D4 |
| **P10** | Metrics & canaries | M | P8 P13 | ✅ **done** | **D25**, D7 |
| **P11** | Cost ledger | M | — | ✅ **done** | D7 |
| **P12** | Dashboard | L | P8–P11 | **build** | — |
| **P13** | Traffic simulator + seed data | S | *none* | 🔨 Track B | D28 |
| **P14** | Repo, README, demo cut | M | all | **build** | **D22**, **D23** |

**Three parts have no dependencies and can start immediately:** P3, P8, P13.
That is the natural split if more than one person is building.

**Critical path to a demo:** P1 → P3 → P5 → P4 → P14.

---

## 1a. Phase plan for the remaining work

Portion 1 split across two people. Everything after it is sequenced into five
phases, one at a time, with Track B (P1, P13) landing independently.

| Phase | Parts | Drawbacks | State |
|---|---|---|---|
| 1. Portion 1 | P3 (Track A), P1 + P13 (Track B) | D15, D9, D10, D16, D28, D3, D2 | P3 ✅ · Track B 🔨 |
| **2. Policy & Audit** | P2, P8 | **D20** ✅, D6, D14 | ✅ **done** |
| **3. Decision & Feedback** | P6, P9 | **D26** ✅, **D24** ✅, D4 | ✅ **done** |
| **4. Measurement & Cost** | P10, P11 | **D25** ✅, D7 ✅ | ✅ **done** |
| 5. Stream & Quality | P4, P7 | D5, D6, D11, D12, D27 | next |
| 6. Surface & Delivery | P12, P14 | **D22**, **D23**, D17, D18 | |

P5 (pre-flight gate) is orchestration over Track B's gateway and lands with
integration rather than in a phase of its own.

---

## 2. Suggested order

**Phase A — the spine and the differentiator**
P13 (seed data) → P3 (substitution) → P1 (gateway) → P5 (pre-flight) → P4 (stream guard)

Ends with: paste a seeded customer record, get a correct answer, upstream
payload contained only placeholders. That is demo step 3 — the whole pitch.

**Phase B — what makes it a control plane, not a filter**
P2 (profiles) → P6 (decision tiers) → P8 (audit)

Ends with: the same prompt resolving differently under `customer-chat` vs
`internal-assistant`, every decision on a tamper-evident chain. That is demo
step 7 and the Governance solutioning area.

**Phase C — what the Round 2 brief scores that nothing else covers**
P9 (feedback) → P10 (metrics) → P11 (cost)

Ends with: an override changing a threshold and moving a measured FP rate.
That is Feedback Loops + Metrics & Monitoring, the two areas we were weakest on.

**Phase D — the surface and the deliverable**
P7 (quality checks, thin) → P12 (dashboard) → P14 (repo + demo)

---

## 3. The parts in detail

### P1 — Gateway spine
FastAPI, OpenAI-compatible `/v1/chat/completions`, streaming and non-streaming,
plus `/v1/embeddings` (D2). Per-request context object; API key → team +
profile. Async upstream client.
**Done when:** an unmodified OpenAI SDK client works against it with only
`base_url` changed, streaming included.
**Note:** D2 is one extra route here, not a separate part.

### P2 — Profile engine (the control plane)
Profile definitions as data, compiled to an in-memory artefact, selected
per-request, hot-swappable without restart. Build exactly the three the brief
names: `customer-support`, `internal-knowledge`, `decision-support`.
**Owns D20** — this is what makes §16's data/control-plane split true in code
rather than asserted in a README.
**Done when:** changing a profile value and re-running the same prompt produces
a visibly different outcome, with no restart.

### P3 — Substitution engine ← *the deep dimension*
Known-value matcher (hash + Bloom filter) over the seeded store; pattern +
checksum tier (Luhn, Verhoeff, mod-97); request-scoped consistent placeholder
map; restore pass on egress; identifier-vs-operand separation.
**Owns D15** — placeholder round-trip fidelity is the one drawback that fails
*live on stage*. Choose the placeholder format for survivability **before**
writing the matcher; test inflection, possessives, casing, and the model
quoting it inside code or JSON.
**Pure library — no gateway needed.** Testable from a script on day one.
**Done when:** round-trip holds across a corpus of adversarial cases, and
arithmetic on substituted records is still correct.

### P4 — Outbound stream guard
Commit-point buffer (sentence / ~40 tokens / ~250 ms), 50-char overlap window,
credential block before release, placeholder restoration inline. Throughput
mode for non-interactive profiles is a flag that skips buffering entirely.
**Owns D5, D6.**
**Done when:** a secret split across two chunks is still caught, and the
interactive stream feels immediate.

### P5 — Pre-flight gate
Orchestration only, once P1–P3 exist: identify → budget → injection → inbound
scan → route. Ordered so refusals cost nothing.
**Done when:** an injection attempt is refused at `cost_usd: 0.0`.

### P6 — Decision engine
Four tiers (allow / annotate / flag for review / block) resolved from
**severity × confidence × profile**. Flag budget per profile with auto-tighten
on overflow. Review queue for the flag tier.
**Owns D26.** Satisfies the brief's Decision Logic area.
**Done when:** the same finding resolves to different tiers under different
profiles, and exceeding the flag budget visibly tightens the threshold.

### P7 — Async quality checks *(thin build — see §5)*
Build only: entity-not-in-source (hallucination tier 0) and **one**
counterfactual bias probe. Toxicity is an off-the-shelf call. Everything else
in §11 is slideware.
**Owns D11, D12, D27** — all three are answered in prose, not code.

### P8 — Audit log
Hash-chained entries, verify endpoint, redacted-text-plus-hashes storage only.
~40 lines. **Pure library.**
**Owns D14.**
**Done when:** editing one row makes verification fail on demand.

### P9 — Feedback loop
Review queue → override/confirm → aggregate → threshold or exception-list
change → recompiled policy artefact → pushed to the data plane.
**Owns D24.** The data plane stays stateless; only the control plane
accumulates. We tune thresholds and exception lists — never retrain on
customer data.
**Done when:** an override visibly changes a policy value and the next
identical request resolves differently.

### P10 — Metrics & canaries
Seeded canary injection as the FN instrument; FP from reviewer disagreement;
override rate; flags per 100 responses; added latency p50/p95/p99; our token
overhead as a share of protected spend. Reported **per profile**.
**Owns D25, D7.**
**Done when:** the dashboard shows a canary catch rate with its seeded
distribution stated, and an override rate we did not hide.

### P11 — Cost ledger
Token accounting, per-team and per-profile attribution, budget enforcement,
prompt-prefix hashing to surface caching opportunities. **No semantic
caching** (D13 is moot — see §5).
**Done when:** demo step 9 — their traffic, what it cost, what it would have
cost — renders from real ledger data.

### P12 — Dashboard
The surface for P8–P11, plus the incident→action loop. This is where §23's
"measurable business impact" becomes visible.
**Done when:** a judge can see a finding, act on it, and watch the number move.

### P13 — Traffic simulator + seed data
Synthetic CRM/HR store (the ground truth P3 matches against), plus a traffic
generator across the three profiles at the stated volume (~30k/week, §24.3).
**Owns D28** — the seed data must include both well-governed records (in the
known-value store) and loosely-governed text (not in it), or we cannot
demonstrate graceful degradation.
**Small, unglamorous, and load-bearing:** P10 and P12 have nothing to show
without it.

### P14 — Repo, README, demo cut
Architecture README; **every stub labelled as a stub in code and README**
(D23); demo cut from nine steps to the four-step spine (D22).
**Owns D22, D23.**

---

## 4. Coverage check

| Round 2 solutioning area | Parts |
|---|---|
| Detection techniques | P3, P7 |
| Decision logic | P6 |
| Architecture | P1, P2, P4, P5 |
| Governance | P2, P8 |
| Feedback loops | P9 |
| Metrics & monitoring | P10 |

| Demo step (post-cut) | Parts |
|---|---|
| Substitution round trip | P3, P5, P8, P13 |
| Credential block | P3, P4 |
| Live policy change | P2, P6, P9 |
| The number | P11, P12, P13 |

---

## 5. Deliberately not built

Per D23, each of these must be labelled as absent in both code and README —
an unmarked gap reads as vapour to a reviewer with repo access.

| Not built | Why | Where it is answered |
|---|---|---|
| Semantic caching | D13 is a drawback of a feature we chose not to ship | §15.3 as reasoning |
| NER model for unstructured PII | Prototype uses known-value + pattern tiers | D10, D27 |
| Claim-shape routing (full) | Stronger as an explanation than an implementation | §11.4 |
| Bias classifier of our own | Explicitly rejected | §19 "do not build" |
| Multi-turn / agentic state | Out of prototype scope; answer is architectural | D4 |
| Envoy / Rust hot path | Buys nothing measurable at this scale | §19 "do not build" |
| Real CRM / Vault connectors | Simulated scope is explicitly permitted by the brief | §24.3 |

**Drawbacks owned by no part — these are answered, never built:**
D1, D3 (partly), D4, D5 (accepted), D8, D11, D12, D13, D16, D17, D18, D19,
D21, D27, D28. Keeping them out of the build is the point of the triage;
if one starts growing a task, re-read DRAWBACK.md §0 before spending hours.

---

## 6. Where to start

**P13 → P3.** Seed data first because P3 needs something to match against, then
the substitution engine because it is the differentiator, it fails live rather
than in Q&A (D15), and it is a pure library that needs no gateway to exist yet.

If splitting across people: **P3**, **P8**, and **P13** have no dependencies and
can begin at the same time.

---

## 7. Changelog

- **2026-08-29** — Created, fourteen parts.
- **2026-08-30** — P3 done and merged (Track A, 150 tests). Phase plan added.
  Phase 2 done: P2 policy engine and P8 audit log, 203 tests total. D20
  resolved; D6 mitigated in code; D14 built with its limitation named in the
  API.
- **2026-08-30** — Phase 3 done: P6 decision tiers and P9 feedback loop, 249
  tests total. D26 and D24 resolved; D4 mitigated via counter-only session
  tracking. Four of the brief's six solutioning areas are now implemented.
- **2026-08-30** — Phase 4 done: P10 metrics/canaries and P11 cost ledger, 296
  tests total. D25 and D7 resolved. Five of the brief's six solutioning areas
  implemented; only Detection's async half (P7) remains.
