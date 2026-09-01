# PHASE 7 — Brief alignment: session risk and jurisdiction

**Closes:** the two Round 2 complexities we currently answer in prose rather
than code — *"multi-turn conversations and AI agents… introduce compounding
risk"* and *"regulatory expectations differ by geography and industry."*
**Status:** plan · 2026-08-31
**Estimate:** ~4 hours total, both parts low-risk because they extend machinery
that already has tests behind it.

---

## 0 · A correction that shrinks the work

`controlplane/feedback/session.py` is **already built and tested** — 9 tests,
`SessionRiskTracker` tracking `turns`, `agent_steps`, `findings`, `blocks` and
`records_touched` (references, never values), returning a `SessionVerdict` when
cumulative disclosure or agent sprawl exceeds budget. It handles **both** halves
of the brief's complexity: multi-turn compounding *and* agent step sprawl.

It is imported by nothing. Not the orchestrator, not the gateway, not the UI.

So Part A is **wiring, not building**. The hard thinking — how to catch
compounding risk without storing a prompt — is done and defended in that
module's own docstring:

> A session that has touched forty distinct customer records is worth stopping
> regardless of whether any single turn looked alarming.

Similarly, `geography` already exists as a `Profile` field, `_base.json`
already provides one level of policy inheritance, and `compile_profile` already
takes a `base=` argument and merges it. Part B adds a **middle layer** to a
chain that already works.

Neither part invents an architecture. Both make an existing one visible.

---

## 1 · Part A — Session risk on the live path

### A1 · Budgets become policy values *(the connective tissue)*

Today the budgets are constructor arguments on `SessionRiskTracker`, which
makes them global. That is wrong on its own terms: a support bot fielding
hundreds of different customers and a decision-support tool working one case
file obviously need different cumulative caps.

Add a section to `controlplane/policy/profile.py`:

```python
@dataclass(frozen=True)
class SessionPolicy:
    """Cumulative limits across a conversation or an agent run.

    Per-request checking stays stateless (IDEATION section 3). These are
    CONTROL-plane budgets, counted from references rather than content -
    see feedback/session.py.
    """
    max_records_per_session: int = 25
    max_agent_steps: int = 40
```

Register it in `_SECTIONS`, add it to `Profile`, validate non-negative in
`_validate`. It then gets fingerprinting, diffing, hot-swap and compile-time
validation **for free**, because every other section already does.

This is what lets Part B clamp session budgets by jurisdiction, and it is why
the two upgrades are one plan rather than two.

*Demo consequence:* set `internal-knowledge` to `max_records_per_session: 6`
so the budget visibly trips after a handful of turns on camera. 25 is right for
production and useless for a 40-second beat.

### A2 · Wire the tracker into the orchestrator

| Change | File |
|---|---|
| `DemoRuntime.__init__` holds `self.sessions = SessionRiskTracker()` | `demo/orchestrator.py` |
| `run()` gains `session_id: str \| None = None` | `demo/orchestrator.py` |
| After the decision, call `observe()` with the scan's findings | `demo/orchestrator.py` |
| Emit a new `session.risk` event | `demo/events.py` + orchestrator |
| `RunRequest` gains `session_id: str \| None` | `demo/server.py` |
| `GET /demo/session/{id}` and `POST /demo/session/{id}/forget` | `demo/server.py` |

Budgets come from the **profile**, not from the tracker's constructor:

```python
verdict = self.sessions.observe(
    session_id,
    findings=scanned.findings,
    blocked=decision.blocked or scanned.blocked,
    max_records=profile.session.max_records_per_session,
    max_agent_steps=profile.session.max_agent_steps,
)
```

That means a small signature change to `observe()` — per-call limits overriding
the instance defaults. Keep the instance defaults as the fallback so the
existing 9 tests keep passing unchanged.

**The session id is supplied by the caller, never minted by us.** The module is
explicit about why: minting one would make us able to correlate traffic we have
no business correlating. The dashboard generates one client-side and sends it;
that distinction is worth one sentence of narration on camera.

### A3 · The new event

```
session.risk   side="inside"
  session_id, turns, distinct_records, agent_steps, findings, blocks,
  over_budget: bool, reasons: [str],
  limits: { max_records_per_session, max_agent_steps }
```

Emitted every request, after `decision`. Carries counters and references only —
never a prompt, never a value. That is checkable on screen, which is the point.

**What happens when it trips** — decide this explicitly rather than by
accident. Recommendation: **the request still runs; the session is flagged, not
severed.** A cumulative-disclosure verdict is evidence about a pattern, not
proof about this request, and killing turn seven of a legitimate investigation
is exactly the over-flagging failure the brief warns about. The verdict routes
to the review queue and surfaces on the dashboard. If a customer wants a hard
stop, that is a profile setting — say so, do not build it now.

### A4 · Frontend — the Session panel

**`dashboard/src/app/page.js`**

- Generate a session id once per browser session:
  `useState(() => crypto.randomUUID().slice(0, 12))`, persisted in
  `sessionStorage` so a page reload continues the same session.
- Send it with every run.
- New panel in the three-up row under the stage — or a fourth card, making it
  `cols-4` on Transit. It needs to be visible *without* scrolling during a
  multi-turn beat, so put it beside `Decision`.

```
┌ THIS SESSION ─────────────────────── a1f3c2e8b904 ┐
│   4          7 / 6          0          0          │
│  turns    records touched  agent    blocks        │
│                            steps                  │
│  ⚠ cumulative disclosure: 7 distinct records      │
│    across 4 turns (limit 6)                       │
│                                                   │
│  counters only — no prompt, no response, no value │
│                              [ New session ]      │
└───────────────────────────────────────────────────┘
```

- `records touched` renders `7 / 6` and turns `--stop` when over budget; the
  card takes a red left edge, reusing the existing `data-role` tint mechanism
  (`.panel[data-role='session']`).
- The `New session` button calls `POST /demo/session/{id}/forget`, mints a new
  id, and clears the panel — which also demonstrates that forgetting is a real
  operation, not a claim.
- The caption *"counters only — no prompt, no response, no value"* stays
  visible permanently. It is the whole argument.

**Multi-turn without multi-turn state:** each click of `Send request` is an
independent stateless request. The counters climb anyway. That contrast is the
demo.

### A5 · A preset that trips it

Add to `PRESETS` in `demo/server.py` — a sequence, not a single prompt. Four
prompts naming four *different* customers from `demo_records.jsonl`, each
individually innocuous:

```
"Summarise the account note for Priya Sharma."
"Now do the same for Rajesh Kumar."
"And Kavya Reddy."
"And Anita Desai."
```

Needs a small frontend affordance: when a preset carries `prompts: [...]`
rather than `prompt: "..."`, the button becomes **Run 4 turns** and fires them
in sequence against one session id, pausing between so a viewer can watch the
counter climb. ~30 lines in `page.js`.

No single turn is flaggable. The session is. That is the brief's sentence,
demonstrated.

---

## 2 · Part B — Jurisdiction as a floor

### B1 · The idea that makes it more than a settings screen

A jurisdiction is a **floor, not a default**. A profile may be *stricter* than
its jurisdiction requires. It may never be looser.

Today `_merge(base, definition)` lets the profile override the base freely.
For a regulatory layer that is backwards, and getting it backwards is how a
governance product ends up letting a team quietly opt out of the law by editing
their own config.

So the chain becomes:

```
_base.json  →  jurisdiction  →  profile        (merge: later wins)
                    ↓
              then clamped     (floor: stricter wins)
```

### B2 · Direction of "stricter" — the table the clamp needs

Not every setting has a strict direction. Only these get clamped:

| Path | Stricter is | Clamp |
|---|---|---|
| `decision.block_at` | lower (blocks earlier) | `min(profile, jurisdiction)` |
| `decision.flag_budget_per_100` | higher (fewer flags suppressed) | `max` |
| `decision.always_review` | `true` | logical OR |
| `quality.hallucination_tier` | higher (more checking) | `max` |
| `streaming.overlap_chars` | higher (more held back) | `max` |
| `session.max_records_per_session` | lower | `min` |
| `session.max_agent_steps` | lower | `min` |
| `audit_level` | `full` > `standard` | rank |
| `outbound.scan_pii`, `outbound.cross_tenant_check` | `true` | logical OR |

Everything else — `cost.*`, `streaming.mode`, `description` — has no safety
direction and is left to the profile.

**One derived fix:** after clamping `block_at`, set
`review_band = (low, min(high, block_at))`. Otherwise a jurisdiction that
tightens `block_at` from 0.90 to 0.75 leaves a review band whose top half is
dead space above the block threshold.

### B3 · Files and code

```
controlplane/policy/jurisdictions/
  eu.json      strictest — EU AI Act high-risk framing, full audit
  in.json      DPDP framing
  us.json      loosest of the three
```

Each carries a `description` that states plainly what it is:

> Illustrative jurisdictional floor authored by a compliance team. This is a
> mechanism for expressing jurisdiction-specific policy, not an implementation
> of any statute, and not legal advice.

`ControlPlane.compile_bundle(jurisdiction=None, overrides=None)` reads the
jurisdiction file, merges it between base and definition, then applies
`_clamp_to_floor(profile, jurisdiction_floor)` before fingerprinting.

`_clamp_to_floor` lives in `policy/profile.py` beside `_merge`, driven by the
table above as a module-level dict. ~40 lines.

### B4 · Showing the clamp — no new fields needed

To display *which* settings a jurisdiction overrode, the API compiles twice —
once without the jurisdiction, once with — and diffs:

```python
before = ControlPlane().compile_bundle()
after  = ControlPlane().compile_bundle(jurisdiction="eu")
clamped = {n: after.get(n).diff(before.get(n)) for n in after.names}
```

This reuses `Profile.diff()` exactly as the existing `/demo/policy/patch`
route does, needs **no new dataclass field**, and keeps `Profile` frozen and
its fingerprint clean. Compiling twice is free — it is the control plane, off
the hot path, which is itself the point.

### B5 · Routes

```
GET  /demo/jurisdictions          list: code, name, description, floors
POST /demo/jurisdiction           { code } → publish + per-profile diff
```

Publishing goes through the existing `PolicyStore.publish()`, so the change
writes its own entry to the audit chain automatically, via the listener
attached in Phase 2. No new audit plumbing.

### B6 · Frontend — the Profiles page

**`dashboard/src/app/policy/page.js`**

A jurisdiction selector in the page header, above the three profile cards:

```
Jurisdiction   [ India (DPDP) ▾ ]   ← European Union · United States
```

On change:

1. `POST /demo/jurisdiction` → recompile, publish
2. Reload profiles — the three cards' numbers change in place
3. The **existing** diff table renders what moved, with one added column

The added column is the payoff. Rows caused by the floor get marked:

| Path | Was | Now | |
|---|---|---|---|
| `decision.block_at` | 0.9 | **0.75** | ⚑ clamped by jurisdiction floor |
| `session.max_records_per_session` | 25 | **10** | ⚑ clamped by jurisdiction floor |
| `audit_level` | standard | **full** | ⚑ clamped by jurisdiction floor |

And a note beneath, which is the sentence for the video:

> `internal-knowledge` asks to block at 0.90. Under the EU floor it blocks at
> 0.75. A profile can be stricter than its jurisdiction demands; it cannot be
> looser. The fingerprint changed, so two checkpoints running this policy can
> prove they are running the same one.

Add a fourth red-outline button to the existing *"Why the compiler refuses
things"* card: **Try to loosen below the jurisdiction floor** — patch
`internal-knowledge` to `block_at: 0.95` under the EU jurisdiction, and watch
the compiler refuse with its own message. That reuses the refusal panel that
already exists and makes the floor provable rather than asserted.

---

## 3 · Tests

Both parts extend tested modules, so the new tests are small and each must be
checked against WORKFLOW's four failure shapes.

**`tests/test_policy/test_jurisdiction.py`**
- a jurisdiction floor tightens a profile that asked to be looser
- a profile *already stricter* than the floor is left alone *(the guard — a
  clamp that always overwrites is not a floor, it is a default)*
- `review_band` high follows a clamped `block_at`
- an attempt to loosen below the floor fails to compile, with a reason
- the fingerprint differs between the same profile under two jurisdictions
- fields with no safety direction (`cost.max_output_tokens`) are untouched

**`tests/test_feedback/test_session.py`** *(extend)*
- per-call limits override the instance defaults
- the existing 9 tests still pass with the defaults unchanged

**`tests/test_demo/test_orchestrator.py`** *(extend)*
- `session.risk` is emitted every request, after `decision`
- counters climb across several `run()` calls sharing a session id
- **the event carries no prompt and no mapped value** — the same assertion
  shape already used for the audit entry
- crossing the budget sets `over_budget` and does **not** block the request
- two different session ids do not contaminate each other

Then the mutation check on the two that matter: break the clamp direction and
watch the floor test go red; drop the `observe()` call and watch the counters
test go red.

---

## 4 · Order of work

| # | Step | Est. | Verify |
|---|---|---|---|
| 1 | `SessionPolicy` section + validation | 20m | existing policy tests green |
| 2 | `observe()` per-call limits | 15m | existing 9 session tests green |
| 3 | Wire tracker + `session.risk` event | 40m | `curl` shows counters climbing |
| 4 | Session panel + id + New session button | 45m | counters climb in the browser |
| 5 | Multi-turn preset + `Run 4 turns` | 30m | budget trips on camera |
| 6 | `_clamp_to_floor` + floor table | 45m | new floor tests, incl. the guard |
| 7 | Three jurisdiction files + `compile_bundle(jurisdiction=)` | 30m | fingerprints differ per jurisdiction |
| 8 | Routes + double-compile diff | 30m | diff marks clamped rows |
| 9 | Jurisdiction selector + diff column + refusal button | 45m | full pass in the browser |
| 10 | Update DEMO-SCRIPT.md, DRAWBACK.md, CONTEXT.md, README | 30m | — |

Steps 1–5 are Part A and independently shippable. If time runs short, **ship
Part A and stop** — it closes the complexity the brief names most directly, and
it is the one where the code already exists.

---

## 5 · Demo script impact

Two new beats for `DEMO-SCRIPT.md`, and the total goes from nine to eleven —
which breaks the 10-minute budget (D22). So this is a **swap, not an addition**:

- **New beat, ~45s: "No single turn looks wrong"** — run four turns, watch the
  counter climb past the limit, point at *counters only, no prompts stored*.
  Slots in after the current beat 5.
- **New beat, ~40s: "The same policy, three jurisdictions"** — change the
  selector, watch `internal-knowledge` clamp from 0.90 to 0.75, then try to
  loosen it and get refused. Folds into the existing beat 6 (Profiles), which
  is already about policy — extending it is cheaper than a new beat.

To stay inside ten minutes, cut beat 5 (*the edge of governance*) as the script
already flags it as the first thing to drop, and fold its one sentence into
beat 4.

---

## 6 · What we must never claim

- **Not** that we implement GDPR, the DPDP Act, or the EU AI Act. We implement
  the *mechanism* by which a compliance team expresses jurisdictional policy,
  shipped with three illustrative examples. The jurisdiction files say so in
  their own `description`, so it is visible to anyone who opens the repo.
- **Not** that we do multi-turn *analysis*. We cannot tell you that turn 3
  contradicted turn 1, because we did not keep turn 1. We track the aggregate,
  which is the half that can be done without becoming the thing we protect
  against. `session.py`'s docstring already says this; the UI should not
  quietly imply more.
- **Not** that agent tool calls are gated. Step *sprawl* is budgeted; individual
  tool calls are not inspected. The honest answer stays: the reversibility axis
  already generalises to actions — `send_email` is irreversible and would gate
  before dispatch, `search_docs` is reversible and would annotate after — and we
  drew the prototype boundary before building it. That answer is deeper than a
  shallow implementation would be, and D19 is the reason to keep it that way.
