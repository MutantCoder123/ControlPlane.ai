# FEATURE_CONTEXT — for designing the ControlPlane UI

**Audience:** a model or designer producing UI/UX for this project, without
reading the codebase. Everything here is drawn from working code — field names,
enum values and example numbers are real, not illustrative.

---

## 1. What the product is

**ControlPlane** is a governance gateway that sits between an organisation's
applications and any LLM provider. Every request and response passes through
it. The application changes one line — its `base_url` — and nothing else.

> The layer that lets a regulated organisation put real company data into a
> third-party model, without the sensitive parts ever leaving the building.

The single most important thing it does: **real customer data goes in, a
correct and useful answer comes back, and the provider only ever saw
placeholders.**

```
User types:      "Refund Priya Sharma on account 5010 0234 5678 90."
Provider sees:   "Refund [[CUST_A]] on account [[ACCT_A]]."
User gets back:  "Dear Priya Sharma, your refund of 45230 is approved."
```

Note the number `45230` passes through **unsubstituted**. Identifiers are
swapped, operands are not, so arithmetic in the answer stays correct.

---

## 2. Who uses the UI

Three distinct users. They want different screens and should probably not share
one dashboard.

| Persona | Cares about | Typical session |
|---|---|---|
| **Compliance officer / DPO** (the buyer) | Proof. Audit trail, what the provider actually received, policy per use case | Weekly. Wants to *show someone else* the evidence |
| **Platform / ops engineer** | Cost, latency, throughput, which team is spending | Daily. Scanning for anomalies |
| **Reviewer** (risk / support lead) | The review queue — decisions escalated to a human | Continuous, in short bursts. Volume must stay low or they stop looking |

There is also a **jury/demo mode**: a 10-minute pitch where a non-user has to
grasp the value in seconds. See §9.

---

## 3. The core concept the UI must convey: route profiles

There is no single configuration. Each **use case** compiles to a named
**profile**, and the same finding resolves differently under each. This is the
central idea — if the UI makes profiles look like a settings page, the product
looks like a filter.

Three profiles ship (they match the three use cases the problem brief names):

| Profile | Use case | Distinguishing behaviour |
|---|---|---|
| `customer-support` | Public-facing chatbot | Blocks earliest (`block_at 0.75`). Toxicity checked synchronously. Cross-tenant checking on |
| `internal-knowledge` | Employee assistant | Most permissive (`block_at 0.90`). Caching enabled. The canonical substitution case |
| `decision-support` | Regulated decision about a person | Reviews **every** response. Counterfactual sampling 100%. Full audit |

**The demo moment:** the same finding at 0.80 confidence →
`customer-support` **BLOCKS**, `internal-knowledge` **REVIEWS**. Public-facing
output justifies stopping earlier.

### Profile shape (real JSON)

```json
{
  "name": "customer-support",
  "description": "Family A. Output reaches the public...",
  "geography": "IN",
  "inbound":   { "substitute_pii": true, "block_credentials": true, "known_value_matching": true },
  "outbound":  { "block_credentials": true, "scan_pii": true, "cross_tenant_check": true },
  "streaming": { "mode": "interactive", "commit_tokens": 40, "commit_ms": 250, "overlap_chars": 50 },
  "decision":  { "block_at": 0.75, "review_band": [0.35, 0.75], "flag_budget_per_100": 5,
                 "always_review": false, "exempt": [] },
  "quality":   { "hallucination_tier": 2, "toxicity_sync": true, "counterfactual_sample_rate": 0.0 },
  "cost":      { "cache_enabled": false, "max_output_tokens": 800, "request_budget_usd": 0.5 },
  "audit_level": "standard"
}
```

Each profile also has a **`fingerprint`** (16-hex content hash, e.g.
`c5d369e56ab46a89`) and belongs to a **bundle** with an integer `version`.
Two checkpoints on the same fingerprint provably run the same policy — worth
surfacing, because it's the question an auditor asks.

---

## 4. Features, screen by screen

### 4.1 Live request inspector — *the flagship screen*

Shows one request in three panes: **what the user typed**, **what the provider
received**, **what came back**. The middle pane is the entire pitch.

Data available per request:

- `ScanResult`: `text` (transformed), `findings[]`, `mapping` (placeholder →
  original, request-scoped), `blocked`, `block_reason`
- `Finding`: `kind` (`known_value` | `pattern`), `category`, `action`
  (`substitute` | `block`), `span` (char offsets into the **original** text),
  `confidence` (float 0–1), `record_ref` (e.g. `"customer:44219"` or `null`),
  `placeholder` (e.g. `"[[CUST_A]]"` or `null`)
- `RestoreResult`: `text`, `restored` (count), `unrestored[]`

**Design notes:**
- `span` offsets let you highlight the exact substituted region inline.
- Two visibly different finding types: `known_value` findings carry a
  `record_ref` and `confidence: 1.0`; `pattern` findings have `record_ref:
  null` and `confidence: 0.9`. The distinction matters — one says *"matched
  customer record 44219"*, the other says *"looks like a card number"*. Do not
  render them identically.
- `unrestored` being non-empty is an **error state**, not a warning. It means a
  placeholder leaked into the final answer.

Placeholder format: `[[CUST_A]]`, `[[EMAIL_B]]`, `[[ACCT_A]]` — a short
category code, underscore, letter index. Treat as opaque tokens.

Categories in use: `customer_name`, `employee_name`, `email`, `phone`,
`account_number`, `payment_card`, `aadhaar`, `iban`, `employee_id`, `api_key`,
`jwt`, `address`.

### 4.2 Streaming view

Responses stream through a **commit-point buffer**: tokens accumulate, get
scanned, and only then release. A credential is *never transmitted* — the
stream simply stops.

- `Release`: `text`, `kind` (`text` | `blocked`), `reason`
- `BufferStats`: `commits`, `released_chars`, `held_chars`, `ttfb_ms`,
  `blocked`, `boundary_catches`

**Design notes:**
- The blocked state is mid-stream: clean sentences appear, then it halts. Show
  *why* (`reason` is e.g. `"credential in response: api_key"`).
- `held_chars` (~50) is text scanned but not yet released — do **not** render
  it as pending/ghost text; it does not exist for the reader yet.
- `ttfb_ms` is the honest cost of the buffer. Surfacing it is a feature.

> **⚠️ Do NOT design a blur-and-reveal effect for withheld content.** It is
> explicitly rejected in the design docs. If a token reached the browser it is
> in the DOM, so blurring only *looks* safe — worse than nothing. Withheld
> content must never be sent to the client at all.

### 4.3 Decision tiers

Every response resolves to one of four tiers. The tier is a function of
**severity × confidence × profile**, never the finding alone.

| Tier | Meaning | User sees |
|---|---|---|
| `allow` | Nothing found, or below threshold | Nothing |
| `annotate` | Reversible harm, evidence available | Response + a marked claim and *why* |
| `review` | Mid-band confidence, or high-stakes profile | Response delivered; a reviewer gets it queued |
| `block` | Irreversible harm, high confidence | Refusal with a reason and a route to exception |

- `Decision`: `tier`, `outcomes[]`, `escalations[]`, `suppressed` (int),
  `sampled` (bool), `profile`, `policy_version`
- `SignalOutcome`: `signal`, `tier`, `reason`

Escalation reasons (real strings): `"confidence in the mid-band"`,
`"profile reviews every response"`, `"policy exception requested"`,
`"pattern has no prior"`.

**Design note:** `annotate` must show *what to check*, e.g.
`"This figure varied across samples: 30 / 45 / 60 days"`. A bare warning icon
is the alert fatigue the product exists to avoid.

### 4.4 Review queue (human-in-the-loop)

Where the `review` tier lands. **This queue holds no conversation content** —
by design. A reviewer sees a category, a confidence and a record reference,
never a prompt.

- `ReviewItem`: `item_id`, `profile`, `category`, `kind`, `confidence`, `tier`,
  `record_ref`, `evidence`, `reason`, `queued_at`
- Reviewer actions → `Verdict`: `confirmed` | `overridden` | `unclear`
- `Resolution`: `item`, `verdict`, `actor`, `note`, `resolved_at`

**Design notes:**
- Three verdict buttons, not two. `unclear` exists because genuinely ambiguous
  cases must not be scored as our success *or* our failure.
- Queue volume is capped by a **flag budget** per profile
  (`flag_budget_per_100`). When exceeded, flags divert to sampling and
  `Decision.suppressed` / `sampled` are set. Surface this — it's the
  anti-fatigue mechanism working, not a failure.

### 4.5 Feedback loop — *"act, not just watch"*

Overrides accumulate and retune policy. The loop is the difference between a
tool that reports and one that improves.

```
detection → review → override → aggregate → threshold/exemption change
          → new policy version → next identical request resolves differently
```

- `SignatureStats`: `confirmed`, `overridden`, `unclear`, `override_rate`
- `Proposal`: `profile`, `path` (e.g. `"decision.exempt"`), `current`,
  `proposed`, `rationale`, `sample_size`

Real rationale string:
`"4 of 4 reviews overturned pattern:payment_card on internal-knowledge"`

**Design notes:**
- A proposal needs ≥3 independent reviews. Show `sample_size` — the
  conservatism is a feature.
- We tune **thresholds and exception lists**, never model weights. The UI
  should present changes as a readable **diff**, e.g.
  `decision.exempt: [] → ["pattern:payment_card"]`.
- Credentials can never be exempted. If a UI offers that toggle it will fail
  validation — don't offer it.

### 4.6 Audit log

Hash-chained. Editing any record breaks verification from that point on.

- `AuditEntry`: `seq`, `timestamp` (ISO8601 UTC), `event`, `payload`,
  `prev_hash`, `entry_hash` (64-hex)
- `VerificationResult`: `ok`, `entries`, `broken_at`, `reason`
- Event types: `"scan"`, `"policy_change"`, `"feedback_applied"`

Failure reasons: `"entry contents altered"`, `"chain link broken"`,
`"sequence number altered"`.

**Design notes:**
- A verify action with a clear pass/fail state; on failure, point at
  `broken_at` and show every entry after it as compromised.
- The log holds **references, never values** — `customer:44219`, never
  "Priya Sharma". Show that this is true; it's a selling point.
- `policy_change` entries carry a `changes` diff per profile.

### 4.7 Cost dashboard — *the closing number*

- `SavingsReport`: `protected_spend`, `baseline_spend`, `overhead_spend`,
  `requests`, `overhead_requests`, `baseline_model`, `prices_as_of`
  → derived: `gross_saving`, `net_saving`, `overhead_share`
- `LedgerEntry`: `request_id`, `team`, `profile`, `usage`, `cost_usd`,
  `purpose` (`protected` | `overhead`), `prefix_hash`, `latency_ms`,
  `baseline_cost_usd`
- `CachingOpportunity`: `prefix_hash`, `occurrences`, `repeated_tokens`,
  `estimated_saving_usd`

Real output:

```
1000 requests | baseline (claude-opus-5) $16.7488 -> actual $5.7006
             | gross $11.0482 - our overhead $0.15 = NET $10.8982
             (prices as of 2026-06-24)
```

**Design notes — important:**
- **Never show gross saving alone.** Gross, our own overhead, and net always
  appear together. A saving figure that hides its own cost is not a saving
  figure, and this is a deliberate credibility move.
- Always render `prices_as_of`. A number without a date can't be checked.
- Attribution views: by team, by profile. Biggest spender first.

### 4.8 Trust / metrics report

The hardest screen to design honestly.

- `ProfileMetrics`: `profile`, `decisions`, `flags`, `blocks`, `reviews`,
  `suppressed`, `latencies_ms` → derived `flags_per_100`, `added_latency`
  (`p50`/`p95`/`p99`)
- `CanaryReport`: `catch_rate`, `estimated_miss_rate`,
  `confidence_interval_95`, `seeded_distribution`, `by_category`, `caveat`,
  `not_measured[]`
- `TrustReport`: `per_profile`, `canary`, `cost`, `method`

Real output:

```
canary catch rate 100.0% (80/80, 95% CI 95.4%-100.0%)
  on seeded distribution {aadhaar: 10, api_key: 20, iban: 10, payment_card: 40}
  - says nothing about categories we did not seed
```

**Design notes — these are non-negotiable product positions:**
- **No single "trust score" and no gauge/dial.** Anyone can average six numbers
  onto a dial; the dial hides which input moved. The design explicitly rejects
  this.
- **Metrics are per profile, never globally aggregated.** One FP number across
  `customer-support` and `internal-knowledge` averages two unrelated things.
- **The catch rate cannot be shown without its caveat** — the seeded
  distribution and the confidence interval travel with it. This is enforced in
  code; the UI must not strip it.
- **Show override rate prominently.** It's the metric we look worst on, and
  publishing it is what makes the others believable.
- `not_measured[]` must be visible: dual-detector disagreement, downstream
  incident correlation, unknown-unknowns.
- False positives are *measured*; false negatives are *estimated*. Label them
  differently — never put them side by side as equivalent numbers.

### 4.9 Session risk (multi-turn / agentic)

Cumulative disclosure tracked from **counters only**, no content.

- `SessionCounters`: `turns`, `agent_steps`, `findings`, `blocks`,
  `records_touched` (a set of record *references*), `first_seen`
- `SessionVerdict`: `over_budget`, `reasons[]`, `counters`

Real reason strings: `"cumulative disclosure: 6 distinct records across 6
turns (limit 5)"`, `"agent sprawl: 11 steps (limit 10)"`.

**Design note:** the interesting story is that no single turn looked alarming.
A timeline showing individually-innocuous turns crossing a cumulative threshold
communicates this better than a counter.

### 4.10 Quality checks (async, annotate-only)

- `QualityFinding`: `check`, `detail`, `evidence`, `confidence`
- `CounterfactualPair`: `attribute`, `variant_a`, `variant_b`, `outcome_a`,
  `outcome_b`, `prompt_a`, `prompt_b`, `diverged`

Real evidence strings:
- `"not found in the source material: 2019, 45230, Circular"`
- `"same request, name changed (Priya -> Rajesh): reject -> advance"`

**Design note:** the counterfactual is **evidence, not a score**. Show both
transcripts side by side. "Same CV, two names, two outcomes" is not arguable;
a bias percentage is. There is deliberately no per-response bias score to
render — bias is measured in aggregate via outcome distribution and
`disparity`.

---

## 5. States the UI must handle

| State | Where | Notes |
|---|---|---|
| Nothing found | Inspector | The common case. Should feel fast and unremarkable |
| Blocked before dispatch | Inspector | Show `cost_usd: 0.00` — refusing cost nothing. This is a feature |
| Blocked mid-stream | Streaming | Partial text then a hard stop |
| `unrestored` non-empty | Inspector | **Error.** A placeholder leaked into the answer |
| Flag budget exceeded | Decision / queue | `suppressed > 0`, `sampled = true` |
| Empty review queue | Queue | Good state, not an empty-state apology |
| Audit chain broken | Audit | Alarm state; everything after `broken_at` is suspect |
| Unknown profile requested | Any | Hard error — never silently falls back to something permissive |
| Ungoverned record matched | Inspector | Pattern-tier finding, `record_ref: null`, lower confidence. Coverage degrading gracefully |

---

## 6. Scale and shape of the data

- ~30,000 interactions/week across three use cases (~3/min average, assume 10× peaks)
- Mix: ~60% internal assistant, ~30% customer support, ~10% decision support
- Confidence values cluster at `1.0` (known-value), `0.9` (checksum-verified
  pattern), and `0.55–0.9` (quality findings)
- Latency added by the gateway is single-digit milliseconds; the model call is
  1–2 seconds. Do not design as if the gateway is the bottleneck

---

## 7. Tone and visual posture

The buyer is a compliance officer who is currently blocking AI adoption. The UI
should feel like **evidence**, not like a security console.

- Favour *showing the artefact* over *scoring it*. The strongest screen is a
  side-by-side of what the user typed and what the provider received.
- Avoid threat-dashboard clichés: no red/amber/green risk gauges, no
  "security score", no dial.
- Numbers appear with their method and their caveat attached.
- Restraint reads as confidence. The product's whole argument is that it is
  honest about its own limits.

---

## 8. Things the design explicitly must NOT include

These are rejected in the project's design documents. A UI model would
plausibly reach for all of them.

1. **Blur-and-reveal for withheld content.** Not a security control — if the
   token reached the browser it is in the DOM. Looks safe, isn't.
2. **A single trust/security score, or any gauge.** Hides which input moved.
3. **Globally aggregated FP/FN numbers.** Per profile only.
4. **A gross-savings figure on its own.** Always with overhead and net.
5. **A real-time bias meter.** Bias is a property of a distribution; a
   per-response bias score cannot exist.
6. **Raw sensitive values anywhere** — in the audit log, the review queue, the
   session tracker, or any log line. References only (`customer:44219`).
7. **A toggle to exempt credentials from blocking.** Refused by validation.

---

## 9. The demo (what the UI is judged on)

10-minute pitch, 5-minute Q&A. Four moments, in this order:

1. **Substitution round trip** — paste a real customer record, get a correct
   answer, show the provider only saw placeholders. *This is the whole pitch in
   fifteen seconds; it deserves the best screen.*
2. **Credential block** — the model tries to emit a live key; the stream stops.
   Never sent, not deleted after.
3. **Live policy change** — flip a profile, rerun the same prompt, get a
   different outcome. Shows the control plane is real.
4. **The number** — their traffic, what it cost, what it would have cost.

If a screen doesn't serve one of those four, it is secondary.

---

## 10. Naming

The product is **ControlPlane**. The architecture splits into a **data plane**
(the checkpoint — stateless, fast, holds compiled policy in memory) and a
**control plane** (policy authoring, budgets, dashboard, audit log). That split
is where the name comes from and is worth reflecting in the information
architecture: authoring and evidence live in one place, live traffic in
another.
