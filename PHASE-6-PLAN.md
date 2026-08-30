# PHASE 6 — Surface & Delivery: implementation plan

**Parts:** P12 (dashboard) · P14 (demo cut) · **Drawbacks:** D22, D23a/b, D17, D18
**Status:** stages 0-4 **built** · stage 5 (demo cut) remaining · 2026-08-30
**Supersedes:** `context_updated.md` (the previous tool's handoff), audited in §1.

The goal is narrow and it is not "a nicer dashboard." It is: **a ten-minute
video in which every number on screen was computed by a module in this repo,
during that take.** Anything on screen that a judge cannot trace to running
code is D23 on camera, and D23 is the drawback that a public repo makes
checkable.

---

## 1. Audit of the current state

I read every file the handoff names, diffed the three modified backend files,
and ran the engine and decision engine directly against the fixtures. Results
per claim.

### A. Ollama integration — ✅ works

`llama3.2:1b` is pulled and `127.0.0.1:11434` answers. The mutated prompt is
genuinely what gets forwarded. No issue.

### B. Real-time streaming server — ⚠️ works, but bypasses six of nine packages

The SSE server streams and restores correctly. But it re-implements, in three
lines each, things this repo already built and tested:

| In `simulate_realtime.py` | What exists and is unused |
|---|---|
| `if "[[" in buffer and "]]" not in buffer: continue` | `stream/buffer.py` — `CommitPointBuffer`, real commit points (sentence / 40 tokens / 250 ms), a 50-char overlap window, `BufferStats`, all profile-driven (P4, D5/D6) |
| `if "sk-" in restored.text:` | `engine.scan_outbound()` — checksum tiers, known-value matching, `Finding` objects |
| nothing | `audit/chain.py` — hash-chained entries (P8, D14) |
| nothing | `cost/ledger.py` — gross / overhead / net (P11, D7) |
| nothing | `metrics/registry.py` — flags per 100, added latency percentiles (P10) |
| nothing | `quality/checks.py` — `entity_not_in_source`, the counterfactual probe (P7) |
| nothing | `feedback/loop.py` — review queue → aggregator → policy diff (P9, D24) |

So the demo currently exercises **3 of 9** packages. The pitch says "we built a
governance plane"; the video would show a substitution proxy. Worse, the
hand-rolled buffer is *visibly* a buffer on screen — we would be filming an
imitation of our own P4 while the real one sits in the repo passing 30 tests.

**This is the single biggest gap and most of the work below is closing it.**

### C. `controlplane/gateway/app.py` was overwritten — 🔴 must revert

The file was replaced with a near-duplicate of `scripts/simulate_realtime.py`.
Three problems, in order of severity:

1. **It is Track B's lane** (CONTRACTS §1), and Track B has a real
   implementation of that exact file in their fork, awaiting merge. This is a
   guaranteed conflict on the one file that carries the integration claim —
   and it is the same lane-crossing failure WORKFLOW §2 records happening
   once already with `README.md`.
2. **It deleted the OpenAI-compatible routes.** `/v1/chat/completions`,
   `/v1/embeddings`, `/healthz` are gone, replaced by a bespoke
   `/v1/chat/simulate`. "Change one line — your `base_url`" now has no code
   behind it. That claim is the entire integration story (TRACK-B.md §2).
3. It duplicates a script that already exists, so the two will drift.

**Action: `git checkout controlplane/gateway/app.py`.** The demo server moves
to a new Track A lane, `controlplane/demo/`, added to CONTRACTS §1 the same way
`policy/`, `audit/`, `decision/` and the rest were — a new lane, nothing of
B's moved.

### D. The 4-step visualiser — ⚠️ works, one live D15 bug

The four panes are the right idea and the raw-vs-restored split (pane 3) is a
genuinely good addition — it is the first time the demo shows the model
*reasoning in placeholders*, which is the thing that makes substitution
believable rather than asserted.

But:

- **`/(\[\[[A-Z_]+\]\])/` hardcodes the placeholder format**, which CONTRACTS
  §4 forbids in exactly these words. It is also already wrong: the engine's
  core pattern is `[A-Z][A-Z0-9]{1,7}_[A-Z]{1,4}\d*`, so the 27th customer in
  a request becomes `[[CUST_A2]]` and this regex silently stops highlighting
  it. Live D15.
- **The punchline is not drawn.** Nothing visually connects `[[CUST_A]]` in
  pane 2 to "Priya Sharma" in pane 4. The judge has to do the substitution in
  their head — which is the one thing we should never make them do.
- No findings, no confidence, no `record_ref`, no policy fingerprint, no
  latency, no cost. The *"matched customer record 44219"* audit line — idea #5,
  our only real differentiator — never appears.
- Panes 1 and 4 are static after the run; there is no sense of transit.

### E. The `exempt` fix — 🔴 wrong fix, and it half-works

The diagnosis was right: `signals_from_findings` marks every finding
`reversible=False`, so a confidence-1.0 known-value match hits
`block_at=0.90` and blocks. Reproduced.

But the fix is wrong three ways, and I verified each:

```
Charge Meera Nair card 4539578763621486
  -> substituted to: Charge Meera Nair card [[CARD_A]]
  WITH the exempt list: tier = BLOCK        <- still broken
```

1. **It does not fix the bug.** `payment_card` is not in the exempt list, so a
   successfully-substituted card still blocks. The bug returns the moment the
   demo uses a card number — which demo step 2 does.
2. **It corrupts the meaning of `exempt`.** The field is documented in
   `policy/profile.py` as *"values a reviewer has judged not worth flagging
   here… this is what the feedback loop writes to."* It is the **only output
   of P9**. Using it as an architectural switch means the policy diff we show
   in demo step 7 no longer reads as reviewer decisions.
3. **It disables the D28 floor.** Exempting `customer_name` also allows an
   *ungoverned* name that could not be substituted — the case our seed split
   exists to demonstrate. It turns "coverage degrades gracefully" into
   "coverage is switched off."

**The correct fix** is one field, in Track A's lane, in `decision/tiers.py`:

```python
@dataclass(frozen=True)
class Signal:
    ...
    mitigated: bool = False    # the harm was neutralised before dispatch
```

set from `f.action == "substitute"` in `signals_from_findings`, and handled
first in `_tier_for`:

```python
if signal.mitigated:
    # Substitution IS the mitigation (IDEATION 9.3). The provider never
    # receives the value, so there is nothing left to block. The finding
    # still reaches the audit line and the metrics - it happened, and we
    # say so - it just does not drive the tier.
    return Tier.ALLOW, "mitigated by substitution"
```

This fixes every category at once, leaves `exempt` meaning what it says, keeps
the finding visible to the UI and the audit chain, and — checked — breaks none
of the 356 existing tests, because `test_engine_findings_are_irreversible`
asserts `reversible` and `record_ref`, not the tier.

Then **revert** `controlplane/policy/profiles/internal-knowledge.json`.

### F. Fixture edit — 🟡 right data, wrong file

`{"record_id": "customer:99999", ... "Indranil"}` was added to
`tests/test_engine/fixtures/records.jsonl`. That is a **test** fixture, in
Track A's lane, and coupling it to demo needs means a demo tweak can turn the
engine suite red. Move demo records to `controlplane/demo/data/demo_records.jsonl`
and point the demo server there. Keeps `pytest` and the video independent.

### G. Hallucination clarification — ✅ correct, but the conclusion is backwards

The reversibility reasoning is exactly right and matches IDEATION §6. But
"therefore hallucination is not shown in the simulation" is what makes the
demo look thin. The async path is *more* interesting on camera, not less: an
annotation that **arrives after the answer has already finished streaming** is
a visible demonstration of the reversibility split. Nobody else's demo does
that, because everyone else blocks everything.

### H. What can and cannot honestly be shown for bias and toxicity

You asked for bias and toxicity with real calculated confidence. Here is what
the code can actually back, because a fabricated number on a public repo is
the exact failure D23 names:

| | Status | What the UI shows |
|---|---|---|
| **Hallucination** | ✅ real | `entity_not_in_source` — real invented-entity list, real confidence `min(0.9, 0.55 + 0.1n)`, shown with the arithmetic |
| **Bias** | ✅ real, but **aggregate only** | `CounterfactualProbe` + `OutcomeDistribution` over N real Ollama runs, showing disparity. **There is no per-response score and D12 says there never will be** — a model favouring one group 70% of the time produces no individually-detectable response |
| **Toxicity** | ⛔ labelled stub | `toxicity()` returns `[]` on purpose — off-the-shelf in production, on the do-not-build list here |

The design turns two of these into assets rather than gaps. The bias panel is
captioned **"there is no per-response bias score, and that is a property of
bias, not a limitation of this build"** — which is a sentence no competing
demo can say, and it pre-empts the Q&A question. The toxicity panel shows the
hook with a `NOT BUILT` chip and the one-line reason. Honesty is cheaper than
being caught, and D23 is the drawback a public repo makes checkable.

---

## 2. Architecture: one orchestrator, one event stream

The rule that makes everything else fall out:

> **The UI renders events. It never computes anything the backend can compute.**

Today the frontend re-derives placeholders with a regex and the server
re-implements the buffer. Both are the same mistake. Instead, one orchestrator
drives the real modules and emits a typed event per stage; the dashboard is a
renderer.

```
controlplane/demo/
  __init__.py
  records.py       loads demo_records.jsonl (own file, not the test fixture)
  orchestrator.py  the pipeline - async generator of DemoEvent
  events.py        the event schema, one dataclass per stage
  server.py        FastAPI + SSE + the non-streaming control routes
  data/demo_records.jsonl
```

`controlplane/gateway/app.py` reverts to Track B's file and stays theirs.
CONTRACTS §1 gains one row: `controlplane/demo/**` → **A**.

### The event schema

Every event carries `seq`, `t_ms` (ms since request open), and `stage`.

| Event | Payload | Backed by |
|---|---|---|
| `request.open` | request_id, profile name + **fingerprint**, policy version, streaming mode, commit_tokens/ms | `PolicyStore`, `Profile` |
| `scan.inbound` | original, substituted, `findings[]` (kind, category, action, confidence, record_ref, span, placeholder), scan_ms | `SubstitutionEngine.scan_inbound` |
| `decision` | tier, per-signal `{tier, reason}`, escalations, flag-budget rate, suppressed | `DecisionEngine.decide` |
| `dispatch` | the exact string sent upstream + `leak_check` (assert no mapping value occurs in it) | orchestrator |
| `stream.raw` | one raw model chunk | Ollama |
| `buffer.hold` | held_chars, why still held | `CommitPointBuffer` |
| `buffer.release` | released text, commit reason (boundary / tokens / timeout), `BufferStats` | `CommitPointBuffer` |
| `restore` | text after restore, restored count, **`unrestored[]`** | `SubstitutionEngine.restore` |
| `block` | side (inbound/outbound), reason, category, `cost_usd: 0.0` | engine + decision |
| `answer.done` | full restored answer, ttfb_ms, total_ms | — |
| `quality.finding` | check, detail, evidence, confidence — **emitted after `answer.done`** | `quality/checks.py` |
| `cost` | gross, overhead, net, model, prices_as_of | `CostLedger` |
| `audit.append` | seq, event, entry_hash, prev_hash, payload | `AuditLog` |
| `done` | — | — |

`leak_check` is worth naming: before dispatch the orchestrator asserts that no
value in `scanned.mapping` appears in the outgoing string, and the event
carries the result. It is a one-line assertion that turns *"the provider never
sees real data"* from a claim into something the UI can display as a passed
check, live, on the take.

### Control routes (not streamed)

```
GET  /demo/profiles                 names, fingerprints, key thresholds
POST /demo/profile                  hot-swap; returns the Profile.diff()
GET  /demo/audit                    the chain
POST /demo/audit/verify             real AuditLog.verify()
POST /demo/audit/tamper             flips one byte -> chain breaks on screen
GET  /demo/queue                    real ReviewQueue.pending()
POST /demo/queue/{id}/resolve       -> FeedbackAggregator -> PolicyTuner.propose()
POST /demo/canary                   real CanarySuite.run() + Wilson interval
GET  /demo/metrics                  MetricsRegistry.report()
POST /demo/bias                     counterfactual sweep -> OutcomeDistribution
```

Two of these are demo moments nobody expects: **`/demo/audit/tamper`** breaks
the hash chain live and the UI shows exactly which entry failed — that is
"tamper-evident" proved rather than asserted (D14). And resolving a queue item
produces a **real policy diff**, which is the answer to *"how does it learn
without retraining?"* (D24) shown as a diff a regulator could read.

---

## 3. Design direction

The current dashboard is a generic SaaS shell — floating sidebar, rounded
cards, acid-green accent. It looks like every AI-generated dashboard, and it
tells the viewer nothing about what the product does.

### The concept: **the boundary line**

The product's entire claim is that there is a line, and real data does not
cross it. So the line is the layout.

A vertical hatched rule runs down the centre of the screen. **Left is inside
the building. Right is the provider.** Real values are rendered left of it and
literally never render right of it. Placeholders are the only tokens that
cross. When a credential is blocked, the token visibly stops at the line and
stays there.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ CONTROLPLANE          internal-knowledge · fp a91c4e… · policy v3        │
├────────────────────────────────┬─┬───────────────────────────────────────┤
│  INSIDE THE BUILDING           │▚│      OUTSIDE · openai-compatible      │
│                                │▚│                                       │
│  ① what you sent               │▚│  ② what the provider received        │
│  ┌───────────────────────────┐ │▚│  ┌──────────────────────────────────┐│
│  │ Refund Priya Sharma 45230 │─┼▚┼─▶│ Refund ⟦CUST_A⟧ 45230            ││
│  └───────────────────────────┘ │▚│  └──────────────────────────────────┘│
│         warm = real            │▚│         cold = placeholder            │
│                                │▚│      leak check ✓ 0 real values       │
│  ④ what you read               │▚│  ③ what the model wrote              │
│  ┌───────────────────────────┐ │▚│  ┌──────────────────────────────────┐│
│  │ Hi Priya Sharma, your …   │◀┼▚┼──│ Hi ⟦CUST_A⟧, your refund of      ││
│  │ refund of 45230 clears …  │ │▚│  │ 45230 clears in 3 days…          ││
│  └───────────────────────────┘ │▚│  └──────────────────────────────────┘│
├────────────────────────────────┴─┴───────────────────────────────────────┤
│ scan 4ms · decide allow · dispatch · commit ×6 · restore 3 · net $0.0021 │
└──────────────────────────────────────────────────────────────────────────┘
```

Data flows **clockwise**: out across the line, down, and back. The round trip
is a literal circuit, which is exactly the pitch.

### Colour encodes side of the boundary

Not decoration — a rule:

| Token | Hex | Means |
|---|---|---|
| `--inside` | `#F0D9A8` warm sand | a real value. Only ever appears left of the line |
| `--outside` | `#8FB8DE` cold slate-blue | a placeholder. The only thing allowed right of the line |
| `--held` | `#E8A33D` amber | text the buffer is holding, not yet released |
| `--stop` | `#C8453C` oxide | blocked |
| `--ground` | `#141A24` deep navy-slate | the bench |
| `--rule` | `#2A3444` | hairlines, the hatched boundary |

The round trip is therefore a **temperature journey**: warm → cold at the line
→ cold → warm again. A viewer with the sound off can follow it. This is the
signature, and it is the one place the design spends boldness.

Deliberately *not*: near-black + acid green (what the current build uses, and
the default look of every AI dashboard right now), and not cream + serif +
terracotta either.

### Type

- **Display / labels:** Space Grotesk — technical, slightly odd, not Inter.
- **Body:** IBM Plex Sans — institutional, which is the register a compliance
  officer reads in.
- **Payload:** JetBrains Mono — the panels literally show wire content; mono is
  correct, not a style choice.

### Motion, used once

One orchestrated moment, not scattered effects: on dispatch, each substituted
span **travels** from its position in pane ① to its placeholder position in
pane ②, crossing the hatched line, cooling from sand to slate as it goes. On
restore, the reverse. Everything else is still. `prefers-reduced-motion`
replaces the travel with a cross-fade.

---

## 4. Pages

| Route | Name | What it proves | Demo step |
|---|---|---|---|
| `/` | **Transit** | the round trip, live, with the leak check | 1–3 |
| `/policy` | **Profiles** | same prompt, different profile, different tier — profiles are load-bearing | 4 |
| `/queue` | **Review** | mid-band escalation, then resolve → real policy diff | 5, 7 |
| `/verify` | **Chain** | hash chain, verify, then tamper and watch it break | 6 |
| `/trust` | **Measures** | canary sweep with Wilson interval + caveat, cost, flags/100 | 8 |

Plus a **Run demo** control that fires the scripted sequence hands-free, so
the video does not depend on typing accurately on the take (D22 — 10 minutes
against 9 steps is ~40 seconds each with no slack).

### `/` Transit — the panels in detail

- **① what you sent.** Your text. Each detected span underlined in `--inside`,
  hovering shows `known_value · customer_name · conf 1.00 · customer:44219`.
  That tooltip is idea #5 made visible — *"matched customer record 44219"*, not
  *"matched a regex."*
- **② what the provider received.** Placeholder chips, `--outside`. Below it a
  live **leak check**: `0 of 3 real values present ✓`, computed server-side.
- **③ what the model wrote.** Raw stream, placeholders intact — proof the model
  reasoned on placeholders. Held text renders in `--held` with a dotted
  underline and a `holding 34 chars · waiting for sentence boundary` caption,
  driven by real `CommitPointBuffer` events. When it releases, the caption
  says which rule fired.
- **④ what you read.** Restored. Restored spans flash warm once. A persistent
  `unrestored: 0` counter — the D15 alarm, on screen, all the time.
- **Under the fold: the tape.** Every event as a row: `t_ms · stage · one
  line`. This is the "everything on screen is traceable" guarantee made
  literal, and it is what a judge scrolls when they are being sceptical.
- **After the answer completes:** quality annotations slide in beneath ④, with
  a caption that says how many ms *after* delivery they arrived. That
  timestamp is the reversibility split, demonstrated.

### The three canned prompts

1. **The round trip** — `Draft a refund note for Priya Sharma; her balance is
   45230 and confirm to priya.sharma@example.com.` → substitutes three
   identifiers, leaves the operand, arithmetic survives. *Idea #3 and #4.*
2. **The block** — a prompt containing `sk-…`. Token stops at the line.
   `cost_usd 0.00` displayed next to it, because we never dispatched. *The
   ordering argument: check first, dispatch second.*
3. **The landmine** — `4111 1111 1111 1111`, Luhn-valid, in no record. Does
   not fire. Side by side with a real seeded card that does. *This is the
   clearest fifteen seconds we have and it currently appears nowhere.*

---

## 5. Build order

Each stage ends somewhere demoable, so we are never mid-refactor.

| # | Stage | Work | Done when |
|---|---|---|---|
| **0** | ✅ **Repair** | reverted `gateway/app.py` and `internal-knowledge.json`; added `Signal.mitigated`; moved demo records out of the test fixture; CONTRACTS §1 row added | 360 tests; a substituted card no longer blocks; mutation check confirms the new tests go red |
| **1** | ✅ **Orchestrator** | `demo/events.py`, `demo/orchestrator.py`, `demo/server.py` — all nine packages on the live path | every stage on the wire with real `BufferStats`; 14 tests drive it with a fake model |
| **2** | ✅ **Transit page** | design tokens, the boundary layout, four quadrants as a clockwise circuit, the tape | round trip and block both narrate end to end, verified in a browser |
| **3** | ✅ **Async quality** | quality events after `answer.done`, confidence with its formula beside it | a test asserts every quality event's `seq` exceeds `answer.done`'s |
| **4** | ✅ **Control pages** | `/policy` hot-swap + diff + compiler refusals, `/verify` verify + tamper, `/queue` resolve → proposal, `/trust` canary + cost + real bias probe | all verified in a browser against the live backend |
| **5** | 🔨 **Demo cut** | ~~README status table~~ ✅, ~~`PITCH.md`~~ ✅ — remaining: rehearse the nine steps against the 10-minute budget and record | one clean take, under time |

Stage 0 is small and unblocks everything; stages 1–2 are the bulk; stage 5 is
D22 and needs a rehearsal, not just code.

---

## 6. What this plan deliberately does not do

- **No new detection.** No NER (D10), no toxicity classifier, no semantic cache
  (D13). Phase 6 is surface and delivery; adding detectors here is the scope
  drift WORKFLOW §6 exists to stop.
- **No per-response bias score**, ever. D12.
- **No fabricated metrics.** Every number is computed on the take or the panel
  says `NOT MEASURED`. The current dashboard hard-codes `canary_catch_rate:
  100.0` and a `$16.7488` baseline in `simulate_dashboard.py`; both get
  replaced by real calls, and where a real call cannot produce a number, the
  panel says so.
- **No touching Track B's lane.** `gateway/**` and `seed/**` stay theirs
  through the whole phase.
