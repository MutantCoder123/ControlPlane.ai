# Gap closure plan — making the code and the claims agree

**Source of the gap list:** [EXPLAINED.md](EXPLAINED.md) §8, produced by reading
the code on 2026-09-02 rather than the docs.

**The governing principle of this plan:** every gap gets closed in one of three
directions, and choosing the direction correctly matters more than the code.

| Direction | When it is right |
|---|---|
| **WIRE** | The setting is legitimate, the machinery exists, it just is not called |
| **NARROW** | The setting is legitimate but its stated meaning is bigger than anything we can honestly deliver — redefine it to what we can, and say so |
| **DELETE** | The only honest implementation would create a footgun, or the feature was already decided against for a written reason |

A settings page that shows eight switches and honours two is not fixed by
honouring all eight. Two of these switches, if honoured, would let someone turn
off the protection the product exists to provide. Those get deleted, and the
deletion is defended by the same argument the compiler already makes when it
refuses to exempt a credential.

---

## 1. Triage — every gap, and its direction

### 1.1 Profile fields declared but unread (EXPLAINED §8.2)

| Field | Direction | Reasoning | Phase |
|---|---|---|---|
| `inbound.known_value_matching` | **WIRE** | Legitimate: a route may want the pattern tier only (no record store access) | 2 |
| `inbound.substitute_pii` | **DELETE** | The only thing this can do when `false` is ship real PII to the provider. Nothing in this product legitimately disables its core protection, and a switch that would is a liability — the same argument that makes the compiler refuse credential exemptions | 1 |
| `inbound.block_credentials` | **DELETE** | Directly contradicts `_validate`'s refusal to compile a profile that exempts credentials. Two mechanisms, opposite answers, one of them silent | 1 |
| `outbound.block_credentials` | **DELETE** | Same | 1 |
| `outbound.scan_pii` | **WIRE** | Legitimate: outbound scanning costs latency and only some routes need it (D21's inverted threat model) | 2 |
| `outbound.cross_tenant_check` | **NARROW → WIRE** | There is no tenant in the data model, so "cross-tenant" cannot be implemented as stated. It *can* be implemented exactly as **cross-record**: flag when the response references a record that was not in the request. Rename the field to `cross_record_check` and implement that | 2 |
| `quality.hallucination_tier` | **WIRE (0/1), document 2** | Tier 0 and tier 1 are buildable now; tier 2 needs the entailment machinery IDEATION 11.2 describes and is not built | 4 |
| `quality.toxicity_sync` | **BUILD** | D31 parked this because the classifier is trained on whole comments and the buffer releases fragments. That is solvable: score the *cumulative* text at each commit point, not the fragment | 4 |
| `quality.counterfactual_sample_rate` | **WIRE** | The probe works on arbitrary prompts since D32; only the sampling trigger is missing. Doubles token cost per sampled request, so it must be cost-attributed, not hidden | 4 |
| `cost.cache_enabled` | **NARROW → WIRE** | Semantic caching stays unbuilt (D13). Exact-match prefix caching is a different thing, is safe, and the ledger already detects the opportunities — wire that and rename the field `exact_cache_enabled` | 5 |
| `cost.max_output_tokens` | **WIRE** | Verified: Ollama honours `num_predict`, capping generation at exactly the limit | 2 |
| `cost.request_budget_usd` | **WIRE** | `CostLedger.check_budget` exists and is tested; nothing calls it on the live path | 2 |
| `audit_level` | **WIRE** | `standard` vs `full` should change what the audit entry carries | 2 |

### 1.2 Structural gaps

| Gap | Direction | Phase |
|---|---|---|
| Gateway ships as stubs; Track B's ~1,900 lines unmerged | **MERGE** | 0 |
| Demo lane and gateway lane enforce different things (§8.4) | **EXTRACT a shared core** — not copy-paste | 3 |
| `sources=""` hardcoded, so hallucination is checked against the question only | **WIRE a sources channel** | 2 |
| Audit chain in memory only (D14) | **WIRE persistence** | 5 |
| `demo/server.py`: 883 lines, 20 routes, 0 tests | **SPLIT + TEST** | 5 |
| `RESTORE` event declared, never emitted | **DELETE** | 1 |
| Quote-mark false positive in `_starts_a_sentence` | **FIX** | 1 |
| numpy unpinned under a pickled model | **PIN** | 1 |
| Current branch 4 commits ahead, plus uncommitted work | **COMMIT + PUSH** | 0 |

---

## 2. Architectural decisions

Four decisions shape every phase below. Each is written as a decision, not a
preference, because the alternatives were considered and rejected for reasons.

### ADR-1 — Policy reaches the engine as *options*, never as a `Profile`

**Problem.** Three of the fields to wire (`known_value_matching`, `scan_pii`,
`cross_record_check`) change what the *engine* does. The engine currently knows
nothing about profiles, and `EngineConfig`'s docstring says so explicitly:
per-profile configuration "is NOT here — that is the compiled policy artefact".

**Rejected: pass `Profile` into the engine.** It inverts the layering, makes
`engine/` depend on `policy/`, and breaks CONTRACTS §3 for Track B.

**Rejected: one engine instance per profile.** Each instance loads the whole
record store and Bloom filter. Wasteful, and the store is the same for all
profiles anyway.

**Decision.** Add a small frozen `ScanOptions` to `engine/api.py` and accept it
as an optional keyword-only argument:

```python
@dataclass(frozen=True)
class ScanOptions:
    """Per-request switches the CALLER derives from its policy profile.

    The engine still knows nothing about `Profile` - the orchestrator maps
    profile -> options. Every default reproduces today's behaviour exactly,
    so existing call sites are unaffected.
    """
    known_value_matching: bool = True   # inbound: use the record store
    scan_pii: bool = True               # outbound: scan the response for PII
    cross_record_check: bool = False    # outbound: flag records not in the request

def scan_inbound(self, text, scope=None, *, options: ScanOptions | None = None) -> ScanResult
def scan_outbound(self, text, *, options: ScanOptions | None = None) -> ScanResult
```

**Why this is safe for Track B:** keyword-only, defaulted, backward compatible.
Their existing calls compile and behave identically. This follows the exact
precedent of the `RequestScope` amendment already recorded in CONTRACTS §3.

**Contract action.** CONTRACTS §3 gains a second amendment block, agreed before
the code lands — not after.

### ADR-2 — One enforcement core, two transports

**Problem.** `demo/orchestrator.py` enforces decision tiers, audit, cost,
session risk and quality. Track B's `gateway/pipeline.py` enforces none of
them. Two request paths, different guarantees — and the one a real application
would hit is the weaker one.

**Rejected: copy the orchestrator's logic into the pipeline.** Two
implementations of the same enforcement sequence will drift, and the drift will
be silent because each has its own tests.

**Rejected: make the gateway call the demo orchestrator.** The orchestrator is
a generator that yields display events; the gateway would be importing a
presentation concern to get enforcement.

**Decision.** Extract the enforcement sequence into
`controlplane/pipeline/core.py` — transport-agnostic, no HTTP, no SSE, no event
formatting. Both lanes become thin adapters:

```
                    pipeline/core.py  (RequestPipeline)
                    scan -> decide -> audit -> session -> budget
                          -> dispatch -> buffer -> restore -> cost -> quality
                             |                                |
        demo/orchestrator.py                      gateway/pipeline.py
        wraps it, emits typed events              wraps it, speaks OpenAI JSON
```

The core reports progress through a small **observer** interface, so it never
learns what SSE is:

```python
class PipelineObserver(Protocol):
    def on_stage(self, stage: str, **payload) -> None: ...
```

`demo/` implements it by emitting events. `gateway/` implements it as a no-op,
or by writing structured logs.

**Why it is worth the refactor:** it is the only way "the app changes one line"
is true in the sense a judge will test it — the OpenAI-compatible endpoint gets
the same guarantees the video shows.

### ADR-3 — Settings that could disable the core protection are deleted, not implemented

`inbound.substitute_pii: false` means "send real customer data to the provider".
`block_credentials: false` means "send passwords". Neither is a legitimate
configuration of *this* product, and the compiler already refuses the analogous
request at the decision layer (a profile may not exempt credentials).

Leaving them declared-but-unread is dishonest. Implementing them is worse than
dishonest. **They are removed from the schema, with the compiler raising a
clear `PolicyError` if an old profile JSON still carries them** — so a stale
config fails loudly instead of being silently ignored.

### ADR-4 — Every new check declares its cost

Three items in this plan add model calls or latency: tier-1 hallucination
re-asking, live counterfactual sampling, and synchronous toxicity. Each one
must register its spend in `CostLedger` under an `overhead` category, so the
gross/overhead/net report stays true. A safety feature that quietly makes the
cost number worse is exactly what D7 exists to prevent.

---

## Phase 0 — Unblock (no new features)

**Goal.** Make the public repository contain the work that already exists.
Nothing here is new code, and everything after this phase depends on it.

**Effort:** 2–3 hours. **Risk:** low, but it is the highest-value phase in the
plan.

### 0.1 Commit and push the current branch

Uncommitted right now: the toxicity classifier (D31), the bias generalisation
(D32), the hallucination depth work (D33), plus the documentation for all
three. `phase-6/dashboard-and-demo` is also 4 commits ahead of `origin/main`.

```bash
pytest -q                       # expect 442 passed
cd dashboard && npm run build   # expect a clean production build
cd .. && git add -A && git commit    # message: the D31/D32/D33 pass
git push -u origin phase-6/dashboard-and-demo
```

**Done when:** `origin/main` (or an open PR from this branch) contains the
dashboard, and a fresh `git clone` + `pip install -r requirements.txt` +
`pytest` passes on another machine.

### 0.2 Merge Track B

```bash
git fetch trackb
git diff --stat main trackb/track-b/gateway-and-seed   # ~1,900 insertions, 20 files
git merge trackb/track-b/gateway-and-seed
pytest -q                       # expect ~442 + Track B's gateway tests
```

Known collision points to check by hand, not by trusting a clean merge:

| File | Why it needs a look |
|---|---|
| `DRAWBACK.md` | Both tracks edited it heavily; the merge will succeed textually and may still lose an entry |
| `tests/test_engine/test_substitute.py` | Their branch deletes 31 lines — confirm what and why before accepting |
| `tests/test_cost/test_ledger.py` | 9 lines changed on their side |
| `requirements.txt` | Append-only rule; confirm nothing of ours was dropped |

**Done when:** `controlplane/gateway/app.py` is a real FastAPI app,
`tests/test_gateway/` is non-empty and green, and an unmodified `openai` client
with only `base_url` changed can complete a request against it.

### 0.3 Update the counts everywhere

`README.md`, `CONTEXT.md` and `EXPLAINED.md` all carry a test total. After the
merge it changes. Re-derive it, do not estimate it.

---

## Phase 1 — Honesty (make the UI stop over-promising)

**Goal.** Nothing on screen claims a behaviour the code does not have. This is
the cheapest phase and the one a judge is most likely to test by grepping.

**Effort:** 3–4 hours. **Risk:** low. **Cut line:** do not skip this phase.

### 1.1 Delete the three footgun switches (ADR-3)

- Remove `substitute_pii` and `block_credentials` from `InboundPolicy`, and
  `block_credentials` from `OutboundPolicy` in `policy/profile.py`.
- Remove them from `policy/profiles/_base.json`.
- In `compile_profile`, raise `PolicyError` naming the field if a profile JSON
  still contains one — a stale config must fail loudly, not be ignored.
- Remove the two rows from the `/demo/profiles` payload in `demo/server.py` and
  the corresponding rows on the Profiles page.

**Tests:** `test_profile.py::test_a_profile_that_tries_to_disable_substitution_is_refused`,
and a mutation check that deleting the guard turns it red.

**Say this on stage if asked:** "There is no switch to turn off substitution or
credential blocking, for the same reason there is no switch to exempt a
credential from the decision engine. If it can be turned off at five o'clock on
a Friday, it is not a control."

### 1.2 Label everything that is not yet enforced

Until its phase lands, every remaining unwired field gets an explicit marker in
the `/demo/profiles` payload and a visible chip on the Profiles page:

```python
"enforced": True | False,
"note": "declared, not yet enforced - see GAP-CLOSURE-PLAN.md phase 4",
```

The Profiles page renders unenforced rows greyed with a `declared only` chip.
This is the same discipline as the `NOT BUILT` panel on Measures: a labelled
gap reads as scope control, an unlabelled one reads as vapour (D23).

### 1.3 Three small corrections

| Fix | File | Change |
|---|---|---|
| Quote-mark false positive | `quality/checks.py` | `_starts_a_sentence` should treat `"`, `'`, `(`, `[` and `*` as sentence-initial. Test: `"Hey team, ..."` must not flag `Hey` |
| Dead event | `demo/events.py` | Delete `RESTORE` — it is declared in the event contract and emitted nowhere |
| Unpinned numpy | `requirements.txt` | Pin `numpy==2.5.2`. The toxicity model is an unpickled artefact and already emits a NumPy 2.5 deprecation warning on load; an unpinned float could break it on a clean install at the worst moment |

**Done when:** `grep`ping any profile field in `controlplane/` finds it either
read by code or explicitly marked `enforced: False`, and `pytest` is green.

---

## Phase 2 — Real enforcement on the demo path

**Goal.** Six settings stop being decorative. Every change here is on the
request path, so every change here gets a mutation-checked test.

**Effort:** 1.5–2 days. **Risk:** medium — this touches the hot path.

### 2.1 `ScanOptions` (ADR-1)

**`engine/api.py`** — add the frozen `ScanOptions` dataclass exactly as in
ADR-1. **`engine/substitute.py`** — accept it, and honour two switches:

- `known_value_matching=False` → `_candidates()` skips the store lookup and
  returns pattern hits only. Findings then carry no `record_ref`, which is
  already how the ungoverned path behaves (D28), so nothing downstream needs
  to change.
- `scan_pii=False` (outbound) → `scan_outbound` returns credential findings
  only, skipping PII candidates.

**`demo/orchestrator.py`** — map profile to options once per request:

```python
opts = checks_free_map(profile)   # policy/adapters.py, ~10 lines
scanned = self.engine.scan_inbound(prompt, scope=scope, options=opts.inbound)
```

Put the mapping in a new `policy/adapters.py` so neither `engine/` nor
`policy/` imports the other.

**Tests** (`tests/test_engine/`): a record-store hit with matching disabled
falls through to the pattern tier; the same text with matching enabled carries
a `record_ref`; outbound with `scan_pii=False` still blocks a credential.
**Mutation check:** ignore the option inside the engine — the first two tests
must go red.

**CONTRACTS:** amend §3 in the same commit.

### 2.2 Cross-record check (the narrowed `cross_tenant_check`)

**What it means now:** after the response is restored, if it references a known
record that was *not* in the request, that is a record boundary crossing — the
customer-support failure mode D21 names (customer X shown customer Y's data).

**Implementation** — no new detection machinery is needed, only a comparison:

```python
inbound_refs  = {f.record_ref for f in scanned.findings if f.record_ref}
outbound_refs = {f.record_ref for f in outbound.findings if f.record_ref}
crossed = outbound_refs - inbound_refs
```

Emit a finding per crossed ref, category `cross_record`, **irreversible**
(it is a disclosure, not an annotation), so the decision engine can block it on
`customer-support` and merely review it on `internal-knowledge` — the same
finding, two outcomes, which is the profile argument made concrete.

**Rename** `cross_tenant_check` → `cross_record_check` in the schema, the
jurisdiction clamp table, `_base.json` and the dashboard. Say plainly in
DRAWBACK that the field was renamed because "tenant" claimed a data model that
does not exist.

**Tests:** a response naming a second customer on `customer-support` blocks; the
same response on `internal-knowledge` reviews; a response naming only the
requested customer produces nothing.

### 2.3 Cost enforcement

Two calls, both on machinery that already exists and is already tested:

```python
# before dispatch - refusing here costs zero, which is the whole ordering argument
self.ledger.check_budget(
    team=team,
    estimate=self.ledger.estimate(PRICED_AS, scanned.text, profile.cost.max_output_tokens),
    request_budget_usd=profile.cost.request_budget_usd,
)
```

Catch `BudgetExceeded` and emit the existing `ev.BLOCK` with
`where="budget"`, `cost_usd=0.0`. This is the P5 pre-flight gate's budget step,
finally on the live path.

And cap generation, verified working against Ollama 0.33.2:

```python
"options": {..., "num_predict": profile.cost.max_output_tokens}
```

**Tests:** a profile with a tiny `request_budget_usd` refuses before dispatch
and never calls the model (assert the fake model was not invoked — that is the
assertion that matters, not the error message); `num_predict` is present in the
payload and reflects the profile.

**Demo value:** a fourth refusal button — "send an over-budget request" — that
refuses at `$0.00` for a *different* reason than the credential does. Two
refusals with two different causes reads as a system, not a special case.

### 2.4 `audit_level`

`standard` (today's behaviour) versus `full`, which adds: the resolved decision
tier and reasons, the policy fingerprint, session counters, and per-finding
spans. Never the prompt, never a value — `full` means more *decision* detail,
not more *content*. `decision-support` already asks for `full` and the EU
jurisdiction floor already forces it, so this makes an existing clamp visible.

Implement in `audit/chain.py::record_scan` with a `level: str = "standard"`
argument; the orchestrator passes `profile.audit_level`.

**Tests:** a `full` entry carries the fingerprint and tier; a `standard` one
does not; **neither ever contains the prompt or a mapped value** — assert that
by searching the serialised entry for the real customer name, which is the test
that would have caught a regression here at any point in this project.

### 2.5 Give the hallucination check real sources

`sources=""` is hardcoded, so an answer is only ever compared against the
question. Any correct-but-new fact is indistinguishable from an invented one —
this is the single largest source of hallucination false positives today.

- `RunRequest` gains `sources: str | None = None`.
- The orchestrator threads it into `entity_not_in_source` and
  `find_unsupported_causal_claims`.
- The Transit composer gains a collapsed **"Reference material (optional)"**
  textarea.
- A new preset, **"Grounded in a document"**, pastes a short policy extract as
  sources and asks a question answerable from it — the same claim that flags
  without sources goes quiet with them.

**Why this matters beyond accuracy:** it turns a weakness into a demo beat.
"Here is the same answer judged against nothing, and judged against the
document it was supposed to use" is a better ninety seconds than either alone.

---

## Phase 3 — One pipeline, two doors (ADR-2)

**Goal.** The OpenAI-compatible endpoint enforces exactly what the demo shows.
Largest single piece of work here, and the one that most changes what the
product *is*.

**Effort:** 2–3 days. **Risk:** high — it refactors a green, tested path.
**Prerequisite:** Phase 0.2 (the merge) and Phase 2.

### 3.1 Extract, do not rewrite

Work in small steps, keeping `pytest` green after each. The orchestrator's
public signature (`async def run(...)`) never changes, so its 33 tests stay as
the safety net for the whole extraction.

1. Create `controlplane/pipeline/core.py` with `RequestPipeline` and the
   `PipelineObserver` protocol from ADR-2.
2. Move one stage at a time out of `demo/orchestrator.py`: scan, decide, audit,
   session, budget, dispatch, buffer, restore, cost, quality. After each move
   the orchestrator calls the core and translates the observer callback into
   its existing event. Run the suite after every single move.
3. When done the orchestrator should be roughly 150 lines instead of 604, and
   every stage test should still pass **untouched**. If a test needed editing
   to stay green, the extraction changed behaviour — stop and find out why.

### 3.2 Adapt the gateway

`gateway/pipeline.py` is Track B's file, and CONTRACTS §1 says ask rather than
edit. With their agreement it delegates to the same `RequestPipeline` with a
no-op or logging observer, and gains for free: decision tiers, the audit chain,
session risk, the budget gate and the quality pass.

| Concern | Approach |
|---|---|
| Streaming | The core already yields commit-point releases; the gateway maps them to OpenAI SSE deltas instead of dashboard events |
| Blocking mid-stream | OpenAI's schema has no "cancelled" state. Finish with `finish_reason: "content_filter"` plus a final chunk carrying the reason — the same information, in the vocabulary the client already speaks |

### 3.3 Prove parity, do not assert it

`tests/test_pipeline/test_parity.py`: same prompt, same profile, same fake
model, run through both adapters. Assert both produced the same decision tier,
the same audit entry count, the same block/allow outcome, the same quality
findings.

**This test is the deliverable.** Without it the two lanes drift again, and the
drift is silent because each lane has its own tests.

**Done when:** the parity test is green and EXPLAINED §8.4's table has no "no"
left in the gateway column.

---

## Phase 4 — The three genuinely new capabilities

**Goal.** Build what was parked for real reasons, now that the reasons can be
addressed.

**Effort:** 2–3 days. **Risk:** medium. **Cut line:** ship 4.1 and 4.3 before
4.2 if time is short.

### 4.1 `toxicity_sync` — the fragment problem, solved

D31 parked this correctly: the classifier is trained on whole comments, the
buffer releases sentence fragments, and scoring a fragment is unvalidated.

**The fix is to score the right text.** At each commit point the cumulative
released text is available, so score that rather than the fragment:

```python
# in the outbound scan the buffer already performs, when toxicity_sync is on
score = toxicity_score(released_so_far + candidate_release)
if score >= profile.quality.toxicity_block_at:    # new field, default 0.95
    return blocked("toxicity above the synchronous threshold")
```

Three non-negotiable honesty requirements:

- **A far higher threshold than the async one** (0.95 vs 0.5). A synchronous
  block driven by a probabilistic classifier will sometimes be wrong; only
  near-certainty justifies stopping a response.
- **Earlier sentences are already out.** This truncates, it does not retract —
  say so in the UI, exactly as the credential path already does.
- **Cost it** (ADR-4): one classifier call per commit point, single-digit
  milliseconds, recorded as overhead.

**Tests:** a reply that turns abusive mid-stream truncates at the crossing
commit point; a merely rude reply is delivered and annotated instead; a profile
without `toxicity_sync` behaves exactly as today.

### 4.2 `counterfactual_sample_rate` — bias probing on live traffic

Today the probe runs only when a human clicks. The field says
`decision-support` should sample at 100%.

**Design.** After delivery (never on the hot path), for a sampled fraction of
requests whose prompt has a detectable subject (`find_subject`), replay with
paired names and record into a long-lived `OutcomeDistribution` keyed by
profile.

Three things that make it honest rather than merely impressive:

1. **It doubles token cost per sampled request.** Register it as overhead
   (ADR-4) and show it in the cost panel. A bias monitor that hides its own
   bill is the same failure as a saving figure that hides its overhead.
2. **The rate is a policy value, not a constant** — which is what the profiles
   already say.
3. **Aggregate only, forever.** No per-response score exists at any point (D12).

**Tests:** rate `0.0` never replays; rate `1.0` replays once per eligible
request; a prompt with no subject is skipped and **not** counted as a clean
result — silence is not evidence of fairness.

### 4.3 `hallucination_tier` — 0 and 1, with 2 labelled

| Tier | What runs | Cost |
|---|---|---|
| **0** | Entity-not-in-source only (today's default) | Free — pure set comparison |
| **1** | Tier 0 + overclaim + causal checks + **narrow re-ask** of the highest-confidence flagged claim | One extra short model call |
| **2** | Shape-specific techniques from IDEATION 11.4 | **Not built** — needs an entailment model, the same argument as D10's NER decision. Labelled, not silently absent |

**Tier-1 re-ask**, per IDEATION 11.3: take the flagged claim, ask the model a
narrow question about just that claim, compare. Retrieval from memory is
stable; improvisation is not. Divergence is corroboration; **agreement is not
proof**, and the UI must say so — a re-ask can raise confidence, never clear a
flag.

`internal-knowledge` is already tier 0; the other two are set to tier 2.
Retune them to 1 and mark 2 unbuilt in the same commit, so no profile claims a
tier that does nothing.

---

## Phase 5 — Hardening

**Goal.** The things that make this a prototype rather than a demo. None of it
is visible on stage, which is exactly why it comes last.

**Effort:** ~2 days. **Risk:** low.

| # | Task | Detail |
|---|---|---|
| 5.1 | **Persist the audit chain** (D14) | Append each entry as one JSON line to `audit/data/chain.jsonl`; on load, re-walk the hashes to verify. A chain that cannot survive a restart is not an audit log. Keep the in-memory log as the default for tests |
| 5.2 | **Split `demo/server.py`** | 883 lines, 20 routes → `demo/routes/{run,policy,audit,queue,measures,bias}.py`, one `APIRouter` each. Mechanical, no behaviour change |
| 5.3 | **Test the routes** | FastAPI `TestClient` plus the existing fake model. Cover all 20, and specifically the bias route's tier selection (`forced_choice` / `free_text` / `not_probeable`), which now carries real logic |
| 5.4 | **`exact_cache_enabled`** | The ledger already computes prefix-hash collisions. Wire an exact-match response cache behind the renamed field. Semantic caching stays unbuilt (D13); the rename is what keeps that honest |
| 5.5 | **Backpressure limits** | The buffer holds unbounded text per request. Cap held bytes and total generation time; on breach, flush and mark the response truncated |
| 5.6 | **Show the false-positive rate beside the false-negative estimate** | Both exist in `metrics/`; only the canary side reaches the screen today. The asymmetry (FP measured, FN estimated) is the honest part and deserves to be visible |
| 5.7 | **Cover `[[CUST_A2]]` in the highlighter** | Placeholder numbering runs past `Z`. The span logic looks correct; it needs the test that proves it, on the same footing as the other D15 guards |
| 5.8 | **Contradiction vs absence** | Split `entity_not_in_source` findings into "absent from source" and "contradicts source" once 2.5 gives the check real sources. Contradiction is a much stronger signal and deserves a higher tier |

---

## 6. Sequencing, effort and cut lines

```
Phase 0  Unblock            2-3 h    <- do today, blocks everything
Phase 1  Honesty            3-4 h    <- never cut; cheapest credibility in the plan
Phase 2  Real enforcement   1.5-2 d  <- the "make the UI true" phase
Phase 3  One pipeline       2-3 d    <- the architectural fix
Phase 4  New capabilities   2-3 d
Phase 5  Hardening          2 d
```

**If the deadline is a week away:** Phases 0, 1, 2 and record the video. That
combination leaves nothing on screen that the code does not do, which is the
only property that actually has to hold on stage.

**If the deadline is two weeks:** add Phase 3. It is the difference between "a
demo that proves a pipeline" and "a gateway an application can point at".

**Do not start Phase 4 before Phase 3.** Adding capabilities to a lane that the
real gateway does not share widens the very gap this plan exists to close.

**Never cut:** Phase 0.1 (push the work), Phase 1.1 (delete the footguns),
Phase 1.2 (label what is not enforced), and the parity test in 3.3 if Phase 3
is attempted at all.

---

## 7. Definition of done, per phase

Each phase is done when its own line is true, verified by running it — not by
reading the diff.

| Phase | The one check that proves it |
|---|---|
| 0 | A fresh clone on another machine runs `pytest` green and `npm run build` clean, and `controlplane/gateway/app.py` is not a stub |
| 1 | Grepping any profile field finds it either read by code or marked `enforced: false`; a profile JSON with `substitute_pii` fails to compile with a named error |
| 2 | Six settings change observable behaviour, each with a mutation-checked test; the over-budget refusal shows `$0.00` on screen |
| 3 | `test_parity.py` passes: identical decision, audit and quality outcomes through both doors |
| 4 | Each of the three fields changes behaviour, and each new model call appears in the cost report as overhead |
| 5 | The audit chain verifies after a server restart |

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The Track B merge is not as clean as reported | Medium | Blocks Phases 3–5 | Do 0.2 first, on a throwaway branch, before committing to any schedule |
| Phase 3's extraction changes behaviour subtly | Medium | High — it is the request path | Move one stage at a time; any test that needs editing is a red flag, not a chore |
| Deleting profile fields breaks a teammate's config | Low | Low | The compiler raises a named `PolicyError` rather than ignoring the field |
| Sync toxicity blocks a legitimate response on stage | Low | High | 0.95 threshold, and `toxicity_sync` stays off for the recorded demo profiles |
| Live counterfactual sampling doubles the bill unnoticed | Medium | Medium | ADR-4: it is registered as overhead and visible in the cost panel |
| A preset drifts because local model output is not bit-reproducible | Medium | High on the day | A fixed seed reduces variance, it does not remove it. Re-verify every preset the morning of recording, three runs each, and keep the reworded fallbacks |
| The plan crowds out recording the video | **High** | **Highest** | The video is the deliverable. Phases 0–2 and record; everything after is upside |

---

## 9. What this plan deliberately does not do

| Not doing | Why |
|---|---|
| Semantic caching | D13 — the similarity threshold is a correctness risk, not a cost one |
| An NER model | D10 — non-deterministic on the synchronous path, undercuts the determinism claim |
| Per-response bias scores | D12 — structurally impossible; bias is a distribution property |
| Consistency sampling | D11 — catches only random fabrication, scores systematic failure as reliable |
| Prompt injection detection | D30 — the provider does it better, and the variant that would be ours has no target |
| Multi-turn content memory | D4 — breaks statelessness; counters do the job without the liability |
| Hallucination tier 2 | Needs an entailment model; labelled unbuilt rather than faked |
| An LLM judging another LLM's output | D11/D12/D30/D32 — it measures a second guess, not ground truth |

Every row above is a decision with a written reason behind it. That list is not
a backlog; keeping it short and defended is part of the product.

---

## 10. Phase 6 — beyond the hackathon

Not scheduled, and deliberately so: none of it is visible in a ten-minute
pitch, and all of it is real work a production deployment would need. Recorded
here so the boundary between "prototype" and "product" is stated rather than
implied.

| # | Task | Why it is a real gap, not a nice-to-have |
|---|---|---|
| 6.1 | **Multi-tenancy** | Every store, profile and session assumes one organisation. Records, policy bundles and session counters would each need a tenant key, and the known-value store would need per-tenant isolation — a cross-tenant match is the worst possible bug in this product |
| 6.2 | **Key management** | Teams are identified by API key with no rotation, revocation or scoping. The audit chain attributes decisions to a team, so a shared or stale key silently corrupts attribution |
| 6.3 | **Horizontal scale** | The policy store, flag budget, session counters and audit chain are all in-process. Two instances behind a load balancer would disagree about all four |
| 6.4 | **Provider fan-out** | One upstream today. Real deployments route by cost and capability, which is where `PriceBook.cheapest` finally earns its place |

Phase 6.1 and 6.3 together are the honest answer to "how does this scale?" —
the architecture supports both (nothing on the request path holds state that
could not be keyed), but neither is built, and saying so is better than
implying a distributed system exists.
