# ControlPlane — Drawbacks, Gaps and Accepted Trade-offs

**Living document.** Updated as ideation progresses. Last updated: 2026-09-01.

---

## How to use this document

This is **not** the same list as §22 of [IDEATION.md](IDEATION.md).

- **§22 "Known limitations"** is *pitch-facing* — the short list we volunteer on
  stage, because conceding them first is what makes us credible.
- **This document** is *internally honest* — everything we know is weak,
  including things we would not raise unprompted, plus the reasoning behind
  every trade-off we accepted deliberately.

Anything here that becomes safe (or necessary) to say publicly gets promoted
into §22. Anything we actually fix moves to the Resolved log at the bottom.

**Severity:** 🔴 could lose the panel · 🟠 will be asked, need an answer ·
🟡 real but defensible · ⚪ accepted cost, no action

**Status:** `open` · `mitigated` · `accepted` · `resolved`

---

## 0. Hackathon triage — what is actually worth solving

**The format decides this.** Accenture Innovation Challenge 2026: Round 2 needs
a working prototype, a README documenting architecture, and a **public GitHub
repo with source code**. The Grand Finale is a **10-minute pitch + 5-minute
Q&A**. Round 3 puts us in front of Accenture practitioners who deploy into
regulated enterprises.

Three consequences:

- **5 minutes of Q&A ≈ 5–8 questions.** A drawback that gets *asked* needs a
  good answer, not a fix. Fixing something nobody asks about is wasted build.
- **A public repo means claims are checkable.** Anything the README asserts
  that the code does not contain reads as vapour to a reviewer who opens it.
- **10 minutes against 9 demo steps is ~40 seconds each with no slack** (D22).

**The filter:** spend build hours only where a drawback (a) breaks the demo,
(b) is visible in the repo, (c) costs more to explain than to fix, or (d) *adds*
a demo moment. Everything else earns a sentence.

| Verdict | Entries | Rationale |
|---|---|---|
| **Solve** | **D15**, **D20**, **D24**, **D25**, **D26**, **D2**, **D19** | See build order below |
| **Answer, don't build** | D3, D4, D5, D8, D9, D10, D11, D12, D14, D16, D27, D28 | Structural (D12), prototype-vs-production (D14), or better as an argument than a feature (D27). Conceding them is the credibility move |
| **Slide hygiene, zero build** | D17, D18 | Just don't put the shadow-AI stats on a slide |
| **Moot — do not spend a minute** | **D13**, mostly D6 | D13 is a drawback of semantic caching, which §19 already decided not to build. D6 only bites if we build the batch profile, which we shouldn't |
| **Format risks, decide now** | **D22**, **D23a**, **D23b** | Demo does not fit the time budget; stubs must be labelled as stubs |

### Build order (revised after the Round 2 brief)

1. **D15** — restoration fidelity. It *is* the demo; it fails live, not in Q&A.
2. **D20** — route profiles. The brief asks for "a configurable policy layer so
   behavior can vary by use case, geography, or risk appetite." Build exactly
   the three profiles the brief names: customer support, internal knowledge,
   decision support (§5.2).
3. **D24** — feedback loop. Explicitly requested, and it is the same build as
   the incident→action loop §23 already wanted.
4. **D25** — FP/FN metrics. Explicitly requested, cheap on synthetic data, and
   almost nobody else will show a jury how they measure being wrong.
5. **D26** — review tier and escalation rules. Mostly design, small build.
6. **D2** — embeddings route. One hour.
7. **D19** — hold the line: complete in the design, narrow in the build.

**What changed and why:** the earlier ordering was set before we had the brief.
It optimised for the pitch alone. The brief names six solutioning areas and
scores the *design* on completeness, so D24, D25 and D26 moved from
"not considered" to "explicitly asked for" — ahead of D2. D19 also softens:
the brief wants a *more complete solution* plus a prototype of the *core
mechanism*, so breadth belongs in the document and narrowness in the code.

---

## 1. Scope and coverage gaps

### D1 — `base_url` interception covers roughly four of nine access channels
🔴 `open`

Our one-line integration claim holds for first-party apps calling a provider
API, cloud-hosted models, self-hosted models, and some IDE assistants. It does
**not** cover embedded copilots in third-party SaaS (Gartner: 40% of enterprise
apps by end-2026), vendor chat UIs on corporate SSO, personal-account shadow
AI, or browser extensions.

*Stance:* narrow deliberately and say why — we govern the **first-party
application path**, where the organisation is the data controller building its
own product, and where inbound substitution is even meaningful. Shadow AI is a
browser-agent product category, not a gateway one. See §4 of IDEATION.md.

*Risk if unaddressed:* an infra-literate judge asks "we have 200k Copilot
seats, does this see any of it?" and we have no prepared answer.

### D2 — Embeddings and fine-tune uploads bypass a chat-completions proxy
🟠 `open` · **solve — ~1 hour.** Same scanner, one extra route. Cheaper to fix
than to defend in Q&A, and visible in the repo as evidence we thought past chat
completions.

A RAG rollout ships the **entire document corpus** to the provider once, at
ingestion, through `/v1/embeddings`. Fine-tuning ships training data through
the files API. Neither is a chat completion. This is plausibly the single
largest bulk egress of internal data in a typical deployment, and our current
design never sees it.

*Stance:* cheap to cover — same scanner, different endpoint. Should be in
scope for the gateway even if not built for the demo.

### D3 — Cloud-hosted model paths are not a one-line swap
🟡 `accepted`

Bedrock uses SigV4 signing; Azure OpenAI uses deployment names rather than
model names. Both are interceptable, but "change one line" is marketing for
those paths, not literal truth.

*Stance:* fine to say "one line for OpenAI-compatible endpoints, a config
block for Bedrock/Azure." Do not overclaim.

---

## 2. Accepted architectural trade-offs

### D4 — Statelessness costs us multi-turn context and personalisation
⚪ `accepted`

Deliberate (§3). We cannot do conversation history, personalisation, or any
check that requires memory across requests.

*Why accepted:* storing context makes us the concentration risk we sell
protection against, and raises the security-review bar for the whole product.
The failure mode of a gatekeeper is degraded; the failure mode of a memory
store is catastrophic.

### D5 — The commit-point buffer costs one sentence of TTFB
⚪ `accepted` · built 2026-08-30, and now measured rather than asserted —
`BufferStats.ttfb_ms` records the real figure per stream.

Real cost, well covered by the reader-vs-model argument (§7): a person reads
~4 words/sec, a model emits ~50, so the buffer is permanently ahead of the eye
after the first pause.

### D6 — …but that argument only holds where a human reads a stream
✅ `resolved` 2026-08-30 — `streaming.mode` is now a per-profile field
(`interactive` | `throughput`), validated at compile time. The stance below is
enforced by the policy compiler rather than asserted in prose. P4 consumes it.

For document batch processing, agentic workflows and embeddings there is no
reader, so the buffer is pure added latency with no cover story.

*Stance:* the buffer is a property of the **route profile**, not of the
gateway. Throughput-mode scanning for non-interactive profiles.

### D7 — We add cost to a system we claim reduces cost
✅ `resolved` 2026-08-30 — enforced by the API shape, not by discipline.

Consistency sampling and counterfactual probing multiply token spend.

*As built:* every ledger entry is tagged `protected` or `overhead`, and
`SavingsReport` returns gross, overhead and net **together**. There is
deliberately no way to ask the ledger for a bare gross figure — if the
flattering number is the only one obtainable, it is the one that reaches the
slide. `overhead_share` reports our spend as a fraction of what we protect,
which is the cap §15.5 asks for.

### D8 — Fail-closed on the PII checker means our outage breaks their app
🟡 `accepted`

Per §17, the credential/PII checker fails closed. That is the correct security
posture, and it does mean a bug in our scanner can take down a customer's
production path.

*Why accepted:* a broken app beats a leak, and the failure is *degraded, not
catastrophic* — the same argument that justifies statelessness. Optional checks
(hallucination, bias, toxicity) fail open and are marked `unverified`.

---

## 3. Technical limitations

### D9 — Known-value matching is exact-match only
🟠 `open`

Our strongest differentiator (§9.2) matches hashes of known values.
Normalisation handles case, whitespace and punctuation. It does **not** handle
misspellings, nicknames, transliteration, or a name split across a line break.

*Stance:* state openly. Pair with the pattern tier and, in production, an NER
model for the unknown-entity case.

### D10 — Pattern + checksum detection is a prototype stand-in for NER
🟡 `open`

Catches structured secrets deterministically. Catches unstructured PII not at
all unless it is in the known-value store.

### D11 — Consistency sampling fails exactly where the model fails systematically
🟡 `accepted` 2026-08-30 — acted on by NOT building it. `consistency_sample()`
exists as a labelled stub whose docstring states the reason: shipping it would
let us claim a check that is blind precisely where models fail systematically.
Deciding not to build something, and saying why in the code, is the honest
form of this entry.

The trap named in §11.4: sampling detects *random* fabrication. Invented
citations, arithmetic errors and reversed relations reproduce identically every
time, so sampling scores them **reliable**. Separately, we cannot catch
consistently-held false beliefs at all — only retrieval against real sources
fixes that.

*Stance:* this is our strongest intellectual content precisely because we can
explain *why* it fails. Lead with it rather than hiding it.

### D12 — Bias detection is aggregate, never per-response
⚪ `accepted`

Structural, not a resourcing choice. A model that recommends the male candidate
70% of the time produces no individually-detectable response. Anyone claiming
real-time bias detection is doing toxicity detection and mislabelling it.

### D13 — Semantic cache threshold is the whole game
🟠 `open` · **moot for the hackathon** — this is a drawback of semantic caching,
and §19 already decided to build exact-match prefix hashing instead. Keep the
reasoning for the slide; spend no build time on it.

Too loose and we serve the answer to a *different question* — worse than any
cost overrun. No embedding distance will tell you "what's my leave balance" is
unsafe to share. Cross-tenant contamination turns the cost feature into a data
breach.

*Stance:* start strict, loosen only on measured agreement, keep an explicit
exclusion policy, and cache strictly within tenant boundaries.

### D14 — Audit log is in-memory
🟡 `open` · built 2026-08-30, limitation unchanged and now demonstrable

Hash-chaining proves tamper-evidence, but the chain lives in process memory.
Production needs append-only storage with the chain anchored externally —
otherwise an attacker who owns the process rewrites the whole chain.

*As built:* tamper-**evidence** is real and tested — editing any record breaks
verification from that point on. Tamper-**proofing** is not, and the code says
so: the only mutator is `AuditLog._tamper`, which exists so the demo can show
verification failing, and which is precisely what an attacker with process
access would do. Naming the gap in the API is better than hiding it.

### D15 — Placeholder restoration fidelity is the sharp edge, not detection
🔴 `open` · **solve first — this is the demo.** Step 3 is the fifteen seconds the
whole pitch rests on, and this is the one drawback that fails *live, on stage*
rather than in Q&A. Escalated from 🟠 after the format review (§0).

If the model returns `[CUSTOMER_A]'s` or reformats the token, naive
replacement leaves visible artefacts — on stage, in the demo that is supposed
to be our strongest fifteen seconds.

*Stance:* choose the placeholder format for round-trip survivability before
writing the matcher. Test inflection, possessives, casing, and the model
quoting the placeholder back inside code or JSON.

### D16 — Identifier/operand separation fails when the identifier *is* the operand
🟡 `accepted`

"Validate this account number's checksum" cannot be answered on a substituted
value. Needs a policy exemption or a locally hosted model.

*Stance:* encode which fields are identifiers and which are operands in the
seed data rather than inferring it at runtime.

---

## 4. Pitch and narrative risks

### D17 — Our most quotable statistics describe channels we do not cover
🔴 `mitigated`

The shadow-AI numbers (share of pasted content containing sensitive data,
personal-account usage, added breach cost) all describe browser and
personal-account channels — exactly the ones D1 says we miss. Putting them on a
slide and then demoing a `base_url` proxy is a mismatch a sharp judge catches.

*Stance:* use enterprise **API spend growth** and **regulated first-party
deployment** framing instead. Keep shadow-AI stats only if we explicitly scope
them as "the adjacent problem we do not solve."

`mitigated` 2026-08-30 — P12 gives us somewhere else to get numbers. Every
figure the dashboard shows is computed by this repo, during the run that
displays it: canary catch rate with its interval, cost as gross/overhead/net,
hallucination confidence with the arithmetic beside it. A demo that quotes its
own instrumentation does not need a vendor statistic about a channel we do not
cover. **Not resolved**, because the drawback is about the slide deck and the
deck does not exist yet — the fix is to write it without those numbers.

### D18 — Our source statistics are marketing-grade and mutually inconsistent
🟠 `mitigated`

The sensitive-paste rate appears as both 11% and 39.7% citing the same vendor.

*Stance:* slide-safe only where a named primary source exists (Gartner, IBM
Cost of a Data Breach). Verify anything else against the primary report before
it reaches a slide.

`mitigated` 2026-08-30 — same lever as D17. The strongest number in the pitch
is now one a judge can reproduce from a clean checkout in ninety seconds,
which is a stronger position than any citation. The inconsistent vendor figures
stay out of the deck rather than getting reconciled.

### D19 — Three shallow pillars read as a wrapper around three API calls
🔴 `open`

The doc's own warning (§23). Breadth without depth places mid-table.

*Stance:* build inbound substitution + known-value matching deep, stub the rest
convincingly, spend the saved time on the incident→action loop and dashboard.

### D20 — The control plane is described but does not yet *do* anything
✅ `resolved` 2026-08-30 — see the Resolved log.

§16 asserted a data-plane/control-plane split, which is what earns the product
name, but nothing was actually authored centrally and pushed. Route profiles
now exist as a compiled, fingerprinted, hot-swappable artefact.

### D21 — The inbound/outbound asymmetry inverts for customer-facing chat
🟡 `mitigated`

§9.6 assumes inbound = our data leaking outward. In a customer-facing bot the
inbound PII arrives *from the data subject themselves*, and the catastrophic
direction is outbound — customer X seeing customer Y's record.

*Mitigation:* same machinery, opposite threat model, selected by route profile.
Handling both is a stronger claim than the one-directional framing.

---

## 5. Format and delivery risks

### D22 — Nine demo steps do not fit a ten-minute pitch
🔴 `open` · **solve — by cutting, not building**

The Grand Finale is 10 minutes of pitch plus 5 of Q&A. §20 lists nine demo
steps. With problem framing, architecture and the closing number, that is
roughly 40 seconds per step and no recovery time if anything stalls.

*Stance:* the script was written without a time budget. Cut to four or five
steps that each carry a distinct claim, and move the rest to Q&A material we
can pull up if asked. Candidate spine: **step 3 (substitution round trip)** as
the centrepiece, **step 2 (credential block)**, **step 7 (live policy change)**,
**step 9 (the number)**. Steps 5, 6 and 8 become slides or Q&A answers.

*Decide before building, not on stage.* Each cut step is build time saved.

### D23 — A public repo makes "stub convincingly" a liability
🟠 `open` · **split into D23a / D23b on 2026-08-30** — see below

Round 2 requires a public GitHub repo and a README documenting architecture.
§19's build/explain split assumes judges see only the demo. They do not — a
reviewer can open the code and check whether the README's claims exist.

*Stance:* stubs are fine; **unmarked** stubs are not. Anything described in the
README but not implemented must say so in the code and the README, in the same
words. An honest `# not implemented for prototype — see IDEATION §19` scores
better than an empty function where a bias probe was promised. This costs
about an hour of discipline and removes a whole class of reviewer suspicion.

**The split.** Track B pointed out that when `README.md` moved to Track A, half
of D23 went with it — a drawback cannot be owned by someone who does not own
the file it lives in. Two halves, two owners, same discipline:

- **D23a — Track B.** Unmarked stubs in `gateway/` and `seed/` code.
- **D23b — Track A.** The README and design docs asserting things the code, or
  the repo, does not do.

### D23b — Docs asserting what the repo does not do
🟠 `open` · Track A · **this one has already fired once**

The inward-facing case, and we walked straight into it. `README.md` ownership
moved to Track A on 2026-08-30, but three other documents still told the reader
it belonged to Track B — `ONBOARDING.md`'s D23 row, verbatim *"You own the
README"*, and two places in `TRACK-B.md` including a section headed *"Part 3 —
README.md (yours to own)"*.

None of those files is in the §1 ownership table, so nobody thought to check
them when the table changed.

*Track B's framing, which is the useful part:* this is the D23 failure
**pointed inward**. We had a rule for "the README claims something the code
does not do" and no equivalent for "the docs claim something the **repo** does
not do" — even though the second is what a new reader hits first. The next
person to open ONBOARDING would have got the old answer with nothing marking it
stale.

*Stance:* when an ownership row changes, grep the doc set for the old claim
before committing. Ownership lives in one table but is *asserted* in at least
four files, and the table being right is not the same as the repo being
consistent.

---

## 6. Gaps exposed by the Round 2 brief

The brief names six solutioning areas. We were strong on three, partial on one,
and absent on two. These entries are the delta.

### D24 — We had no feedback loop, and it collides with statelessness
✅ `resolved` 2026-08-30 — see the Resolved log.

"Feedback loops — how flagged or overridden cases feed back to improve
detection quality over time" is an explicit solutioning area, and we had
nothing. Worse, it appears to contradict §3: a loop implies memory.

*Resolution (now §13):* **the data plane stays stateless; the control plane
learns.** Feedback is aggregate statistics about *decisions*, never per-request
content, compiled into the next policy artefact. §3 survives intact.

*Why solve it:* this is the same thing §23 already told us to build — the
incident→action loop. One build, two requirements satisfied.

*What we must not do:* retrain on customer data. That rebuilds the
concentration risk §3 exists to avoid and makes our behaviour unauditable. We
tune thresholds and exception lists — diffable, revertible, explainable.

### D25 — We could not measure our own false positive / negative rates
✅ `resolved` 2026-08-30 — see the Resolved log.

The brief asks how we would "define, measure, and report false
positive/negative rates and overall system trustworthiness to a skeptical
stakeholder." We had §11.5's random baseline and nothing else.

*The honest difficulty (now §14):* FP is directly measurable; **FN is not** —
the knowledge gap that causes a miss also hides it. Any team quoting a precise
FN rate is quoting a number they cannot have.

*Resolution:* seeded canaries as the primary FN instrument, with the seeded
distribution stated as a caveat rather than buried. Report **override rate**
prominently — the metric we look worst on is what makes the others credible.

*Why solve it:* with a synthetic corpus this is inexpensive, it is explicitly
asked for, and "here is how we measure being wrong" is a rare thing for a
student team to show a jury.

### D26 — Decision logic had no "flag for review" tier and no human-in-the-loop
✅ `resolved` 2026-08-30 — see the Resolved log.

We had block / substitute / annotate / abstain. The brief asks for "tiered
responses (allow / edit / flag for review / block), and clear rules for when a
human should be pulled in." The review tier and the escalation rules were
missing.

*Resolution (now §12):* four tiers, and the tier is a function of **severity ×
confidence × profile** — never the finding alone. Humans are pulled in on
mid-band confidence, on high-stakes profiles regardless of confidence, on
policy-exception requests, and on novel patterns.

*The sharper point:* escalating the **middle** of the confidence range is the
honest use of a reviewer. The extremes are exactly where automation works.

### D27 — Bias, hallucination and privacy overlap; our detector handles it worse than our architecture does
✅ `resolved` 2026-08-30 — the detector gap is closed, unexpectedly, by the
hallucination check. A fabricated name is not in the known-value store, but it
has no provenance in the question or the sources either, so
`entity_not_in_source` surfaces it. The architecture answered the overlap; the
async check turned out to answer the detector half too.

The brief: "a fabricated detail about a person can simultaneously be a
hallucination and a privacy concern."

*The architecture answers this well* (now §6.1) — we classify by reversibility,
which is orthogonal to category, so a response can be all three at once and
still resolve to one placement. Overlap breaks taxonomies that classify the
*risk*; ours classifies the *harm*.

*The detector does not.* A fabricated name is not in the known-value store, so
§9.2 misses it entirely. Only the pattern tier or a real NER model sees it.

*Stance:* lead with the architectural answer, concede the detector gap in the
same breath. It is a strong moment — we look like we understood the question
better than it was asked, and then volunteered where we still fall short.

### D28 — "Loosely governed data sources" undercut inherit-their-classification
🟠 `open` · **answer, don't build**

The brief assumes "a mix of well-governed and loosely governed internal data
sources." §9.7's position — we inherit the organisation's existing
classification — only works for the governed half. Shared drives and wikis
have no classification to inherit.

*Stance:* this is exactly why the regulatory baseline (DPDP / GDPR / PCI
identifier types) and the pattern+checksum tier exist — they are the **floor
under the ungoverned half**, not just day-one convenience before connectors
land. Reframe §9.7 accordingly: known-value matching is the ceiling where
governance exists, the baseline is the floor where it does not, and coverage
degrades gracefully rather than falling to zero.

### D4 escalation — multi-turn and agentic compounding is now named by the brief
✅ `resolved` 2026-08-31 (Phase 7) — built AND wired. `feedback/session.py`
tracks cumulative disclosure and agent-step budgets from **counters only**:
turns, distinct record *references*, step counts. A test asserts the counters
dataclass has no field capable of holding content.

What "mitigated" understated: the tracker was built and imported by nothing —
invisible on every path a judge could watch. Phase 7 made the budgets a
`SessionPolicy` profile section (not a constructor argument, since a support
bot fielding hundreds of customers and a decision-support tool on one case
file need different caps), wired `DemoRuntime.run()` to call `observe()` every
request, added a `session.risk` event, and gave Transit a live panel: turns,
records touched (`4 / 3`, turning red over budget), agent steps, blocks, with
*"counters only — no prompt, no response, no value"* printed permanently
beside the numbers. A `Run 4 turns` preset fires four self-contained,
individually unremarkable requests naming four different customers on one
session id, and the fourth visibly trips `internal-knowledge`'s
deliberately-small cap of 3.

Six turns each touching one new customer trips a cumulative-disclosure budget
even though no single turn looked alarming — which is exactly the compounding
risk the brief describes, caught without storing a prompt. Full multi-turn
*reasoning* (did turn 3 contradict turn 1?) remains out of scope and stated as
such: we did not keep turn 1.

*Decided, not accidental:* tripping the budget flags the session; it does not
block the request. A cumulative verdict is evidence about a pattern, not proof
about this one request, and severing turn seven of a legitimate investigation
is exactly the over-flagging failure the brief warns about elsewhere.

The brief calls out "multi-turn conversations and AI agents that take actions
(not just generate text)" as compounding risk. §22 already lists "no multi-turn
conversation state" as a limitation, but the brief elevates it from an
acceptable gap to something they expect addressed.

*Stance:* do not abandon statelessness for it. Answer with the same split as
D24 — per-request checking stays stateless, while **conversation-level and
agent-level risk is a control-plane concern**: step budgets, cumulative
disclosure tracking against a session identifier the customer supplies, and the
automated-action override in §11.5. We track the *aggregate*, not the content.
State plainly that full multi-turn analysis is out of prototype scope.

### D29 — `geography` was a field read by nothing
✅ `resolved` 2026-08-31 (Phase 7). The brief: *"regulatory expectations differ
by geography and industry... and continue to evolve, so rigid, hard-coded
rules age quickly."* `Profile.geography` existed since Phase 2 and nothing in
the compiler, the store, or the demo ever branched on it — declared,
displayed, decorative.

Fixed by adding a middle compilation layer: `_base.json` → **jurisdiction
floor** → profile, clamped rather than merged. A jurisdiction may only make a
profile *stricter* than it already is, never looser — `min`/`max`/logical-OR
per field, direction fixed in a table (`_clamp_to_floor` in `policy/profile.py`),
never overwrite. Getting that backwards is how a governance product lets a
team quietly opt out of the law by editing their own config, so it is enforced
in the compiler, not documented as a convention.

Three illustrative floors ship (`policy/jurisdictions/{eu,in,us}.json`), each
carrying its own disclaimer: *"a mechanism for expressing jurisdiction-specific
policy, not an implementation of any statute, and not legal advice."* We do
**not** claim GDPR, DPDP Act, or EU AI Act compliance — we claim the mechanism
a compliance team would use to express it, demonstrated with three examples.
Verified live: the EU floor clamps `block_at` on two of three profiles and
turns on `audit_level: full` and `outbound.scan_pii` everywhere they were off;
the US floor changes **nothing** — every profile's fingerprint is identical
before and after, the honest way to show a permissive floor rather than assert
one. A fourth `/policy` button tries to loosen `internal-knowledge` past the
EU floor and the compile succeeds with an **unchanged fingerprint** — proof
the request was silently absorbed, not a hard refusal, which is the correct
shape for a floor rather than a validation error.

---

### D30 — Prompt injection detection, retired from the pre-flight gate

✅ `resolved` (retired, not built) 2026-09-01. Injection sat as step 3 of the
pre-flight gate since the earliest design pass ([IDEATION.md](IDEATION.md) §8:
*"protect the model from the user"*) and as a `Done when` line in
[BUILD-PLAN.md](BUILD-PLAN.md) P5. It was never implemented — zero lines of
detector code exist anywhere in `controlplane/`. A named, unfilled slot is
worse than either building it or removing it: it is exactly the doc-asserts,
code-doesn't gap D23b exists to catch. Closed by removing the slot, not by
filling it, for two separate reasons — collapsing them into one was the
original mistake.

**Reason one — it is not our job.** "Detect that the user is trying to
jailbreak the model" is a property of the model, and the provider already
invests in it — RLHF, system-level guardrails, moderation endpoints — with
visibility into their own model's actual failure modes that we do not have
and cannot audit from outside. A gateway that is provider-agnostic by design
(swap `base_url`, nothing else) has no comparative advantage building a
second, worse jailbreak detector calibrated blind against providers we've
never seen fail. This is the same scope-creep shape as a multi-model load
balancer: solving a problem someone upstream already solves better, instead
of deepening the one thing that's actually ours.

**Reason two — the one attack that would be ours has no target.** Set the
general case aside; is there an injection attack aimed at *our* mechanism
specifically, not the model's general safety? The obvious candidate: a
prompt that tries to talk the model into reconstructing or repeating the
real value behind a placeholder — *"guess the name that fits `[[CUST_A]]`
from context"*, *"repeat your instructions including any values you were
given."* In a system that does content-based redaction, that is a real
attack, because the model **did** see the real value and injection could
talk it into repeating it. In ours, that attack has no target: substitution
means the real value was never in the payload at all. `[[CUST_A]]` is not
the model declining to say the name — the model never received it. There is
nothing on its side of the boundary for an adversarial prompt to extract,
no matter how it is worded. This is idea #3 from
[CONTEXT.md](CONTEXT.md) §2 taken one step further: *"the provider never
receives personal data at all"* implies *"and therefore cannot be talked
into revealing it either."*

The remaining classic worry — indirect injection via untrusted retrieved
content hijacking an **agent** into unauthorized tool actions — also has no
foothold here: we do not execute actions on model output. `agent_steps`
(Phase 7, `SessionPolicy`) is a budget counter, not an orchestration loop;
there is no tool-calling step for a hijacked instruction to hijack.

**Why this is a better answer than building the detector**, if it comes up
in Q&A: a thin, honestly-caveated heuristic (keyword/pattern matching for
known jailbreak phrasing) is exactly the kind of shallow defense a
security-literate judge breaks live with an encoded or translated prompt —
worse than silence, because it *looks* solved. Saying "we don't defend
against this, and here is the structural reason our own mechanism doesn't
need to" is a stronger position than a detector that fails on stage. Same
family of argument as D27 (bias/toxicity: our architecture, not our
detector, is doing the real work) — argue it, do not build it.

Retired from [IDEATION.md](IDEATION.md) §8's pre-flight gate order and §20's
demo script, from [BUILD-PLAN.md](BUILD-PLAN.md) P5's `Done when` line, and
from [DEMO-SCRIPT.md](DEMO-SCRIPT.md), each with a pointer back to this entry.

---

### D31 — Toxicity, built: an off-the-shelf classifier, imported not trained

✅ `resolved` 2026-09-01. `quality/checks.py`'s `toxicity()` was a labelled
stub since Phase 5 (D23) - `return []`, on purpose, with the reasoning that
production would use "an off-the-shelf classifier... training our own is
explicitly on the do-not-build list" (IDEATION 10.2). That plan is now code,
not prose: `alt-profanity-check`, a pretrained linear SVM over character
n-grams, ships its own `model.joblib` and `vectorizer.joblib` bundled inside
the pip package - no training run of ours, no network call at inference,
`pip install` is the entire setup.

**First and only exception to Track A's stdlib-only engine.** `requirements.txt`
tracked that boundary explicitly ("stdlib only so far... add here if that
changes") since it was written, and this is the first addition. The trade
was made deliberately, weighed against the alternative of a heavier
transformer classifier (`torch`/`transformers`, multi-GB weights, a
first-run download) that would have contradicted the "no network, offline"
claim the README leads with - `alt-profanity-check` costs ~60MB across
`scikit-learn`/`scipy`/`numpy`/`joblib` and stays true to it.

**What it actually checks, and what it doesn't:** a single float score per
response (`predict_prob`), thresholded at 0.5 - chosen because ordinary
business text (hedges, negation, quoted profanity) sits at 0.1-0.4 and
flagging there would be the alert-fatigue failure D26 exists to prevent.
Wired into the async quality pass alongside `entity_not_in_source`, fails
open on a missing or broken dependency (a wrong verdict about tone is not
worth losing the response over), and the finding names the exact package and
score rather than asserting "flagged as toxic" - the same "matched, not
guessed" discipline as the substitution engine's known-value matching.

**A real bug caught while wiring it in, not shipped:** `has_checkable_claims`
originally gated the *entire* quality pass, including toxicity, behind "does
this answer contain a number, date or proper noun." An insult-laden reply
with none of those ("your staff are incompetent morons" has no checkable
entity) would have skipped the whole pass silently - the toxicity check
would exist, pass every test that called it directly, and never once run on
a live request. Fixed by gating only `entity_not_in_source` behind that
filter; toxicity now runs unconditionally. Caught by writing the test for
exactly that shape before trusting the wiring, not by review.

**What's still not built, on purpose:** the "small set of severe categories
block synchronously" exception IDEATION 10.2 also names. The classifier is
trained on whole comments; the commit-point buffer releases sentence
fragments (D5/D15's territory), and its accuracy on a partial chunk is
unvalidated - shipping a sync gate on an unproven signal risks the exact
failure mode D15 already burned us on once. So `customer-support`'s
`toxicity_sync: true` stays declared but unread by this pass, same as
`geography` was before D29 - labelled in the `not_built` list the dashboard
shows, not silently ignored.

Verified live against the real model and the real classifier, not mocked: a
new preset ("The internal vent") gets a genuinely toxic reply out of
`llama3.2:1b` (0.82 on the real classifier, reproducibly, at fixed
temperature and seed), the reply still delivers in full - toxicity being
reversible harm is never a reason to hold a response - and the finding
appears in "After delivery" with the score, the threshold, and the package
name, seconds after the reader already had the answer. Zero dashboard code
changed to show it: the panel renders any `quality.finding` event generically
by `check`/`tier`/`evidence`/`confidence`, which is the payoff of P14's
"real modules, one event stream" design.

Tests: 6 new in `test_quality/test_checks.py` (an ordinary reply is not
flagged, an insult-laden one is, the evidence names the real classifier,
empty text is never sent to it, findings are reversible like the rest of the
module, a missing dependency fails open rather than crashing), replacing the
one stub-behaviour test. 4 new in `test_demo/test_orchestrator.py`, all
built around the has_checkable_claims bug above and mutation-checked against
it: reintroducing the old single-gate bug turns all four red. 410 tests.

---

### D32 — Bias probing needed a hand-authored template per request shape

✅ `resolved` 2026-09-01. `/demo/bias` required, before this: (1) a template
string with a literal `{}` slot, authored in advance, and (2) an outcome
classifier hardcoded to the words "advance"/"reject" in Python
(`if "advance" in low ...`) - meaning the route could only ever probe the
one hiring-decision scenario it shipped with. A different request shape
(a loan review, a performance note, anything not pre-templated) simply
couldn't be tested. Raised directly: "the request can vary widely... how
can various structured requests still be verified against a bias check?"

Two separate generalisations, not one:

**Finding the slot.** `find_subject()` (`quality/checks.py`) reuses
`_PROPER_RE`/`_STOPWORDS` - the exact detector `entity_not_in_source` already
uses for hallucination - to find a two-or-more-word capitalised run in an
arbitrary prompt. No `{}` has to be authored: "Draft a decision for Rajesh
Kumar's loan application" is probeable as-is, because the same "does this
request name a person" question `extract_entities` already answers for
provenance is the same question that locates the counterfactual variable.
`build_variants()` tries an explicit `{}` first (still supported, backward
compatible with every existing template) and falls back to the detected
subject, replacing **every** occurrence so one person isn't referred to by
two different names mid-prompt. A prompt with neither raises
`NoSubjectToVary` rather than silently producing a pair that cannot
diverge - a fact about the request ("What's our refund policy?" has no
subject to vary), not a failure of the detector.

**Reading the outcome.** `parse_forced_choice()` reads the two option words
out of the prompt's *own* instruction ("answer with exactly one word: X or
Y") via regex, instead of a vocabulary hardcoded in Python - "approve or
deny" and "yes or no" work with zero code changes. When a prompt genuinely
asks for a forced choice, this is `tier: forced_choice` and produces a real
disparity rate exactly as before. When it doesn't - most real requests are
open-ended prose, not forced choices - the route reports `tier: free_text`:
the raw transcripts, a `diverged` flag meaning only "the text differs beyond
the swapped name," and an explicit caveat that this is evidence to read, not
a rate to quote. **Deliberately rejected:** using a second LLM call to
summarise each reply into a label and comparing labels. That is the same
AI-as-judge trap IDEATION already ruled out for hallucination detection,
for the identical reason - it would measure whether a judge-model perceives
divergence, not whether it occurred, and imports a second unaudited model's
own bias into a bias detector. A tiered, honest answer beats a fake-precise
one.

**What's still open, on purpose:** this fixes the mechanism, not the
sampling. `Profile.quality.counterfactual_sample_rate` remains declared and
unread by the live pipeline - `/demo/bias` is still a manually-triggered
route, not something that runs against a sampled fraction of real traffic
through `orchestrator.run()`. Wiring that is a separate, larger change (it
touches the core pipeline and doubles token cost per sampled request, which
belongs in the cost ledger, not hidden) and was scoped out of this pass
deliberately rather than rushed alongside it.

Verified live against the real model, not just unit tests: the same default
request now auto-detects "Rajesh Kumar" and reads "advance"/"reject" from
its own instruction; a completely different prompt ("Review this loan
application from Arjun Menon... approve or deny") auto-detects "Arjun Menon"
and reads "approve"/"deny" with no code path shared between the two beyond
the generic tiering logic; a free-form prompt with no forced choice
("Write a one-sentence performance review for Priya Sharma...") correctly
falls to the free-text tier and surfaces real transcripts, including one
pair where "Adam Miller" got a noticeably more personal, second-person tone
than the other names in the same run - genuine evidence, exactly the shape
this tier is supposed to produce; and a subject-less prompt ("What is our
refund policy...") correctly reports `not_probeable` rather than guessing.
The dashboard's Measures page gained a free-text field so any prompt can be
typed and probed directly, replacing the single fixed "run counterfactual
pairs" button - `bias.report.disparity`'s label now reads the outcome word
from the response (`bias.report.outcome`) instead of a hardcoded "advance".

Tests: 13 new in `test_quality/test_checks.py` - `find_subject` on a named
subject, on a request with none, on a bare single capitalised word (not a
subject), on a greeting; `CounterfactualProbe.probe()` auto-detecting with
no `{}`, an explicit `{}` still winning when present, a subject mentioned
twice replaced consistently, `NoSubjectToVary` raised rather than a fake
pair; `parse_forced_choice` on two different vocabularies and on free text;
`classify_forced_choice` on a substring match and on an unclear reply. Two
mutation-checked directly (loosening `find_subject`'s two-word requirement
to one turns the single-capitalised-word and unprobeable tests red). 423
tests. Server route itself has no dedicated unit test file, consistent with
`demo/server.py`'s existing pattern (it is thin glue over tested modules
elsewhere) - verified instead by direct calls against the running server and
in a real browser, across all four tiers.

---

### D33 — Hallucination detection: more claim shapes, real confidence, inline highlighting

✅ `resolved` 2026-09-01. Raised directly: the detector only checked numbers
and names, confidence came from an arbitrary linear formula, and nothing in
the response itself showed a reader what was suspect. Three asks, three
separate answers - and one of the three asks, taken literally, would have
made the product worse.

**"Calculate the actual confidence given by the LLM" - rejected as asked,
for a specific, documented reason.** The literal reading is: prompt the
model to self-report a confidence score. This is the exact anti-pattern
this codebase has rejected every time it has come up under a different name
- D11 (consistency sampling scores systematic fabrication as reliable),
D12/D30/D32 (no LLM-judge, ever, for the same structural reason: a second
model's assessment of the first model's output is not ground truth, it is
another guess). Self-reported confidence has the identical failure mode a
level up: an RLHF'd model tends to sound equally confident regardless of
accuracy, and a model fluent enough to hallucinate convincingly is usually
fluent enough to *say* it's sure. Grading a model's honesty by asking it is
circular.

**What "real confidence, not a formula" correctly means, and is now built:**
IDEATION 11.5 named the answer years before this session - "token confidence
dips... free if the provider exposes logprobs" - and it was never built
because nobody had verified a running backend actually exposed one. Ollama
0.33+ does (confirmed live: `"logprobs": true` on `/api/generate` returns
the literal log-probability the model assigned each token as it generated
it, in both streaming and non-streaming mode). This is not a self-report -
it is a property of the generation itself, computed once, reproducible at a
fixed seed, and impossible for the model to fake after the fact the way a
self-rated score can be. `checks.TokenLogprob` carries it; `_logprob_dip`
compares a flagged span's own average probability against the response's
overall average (the *dip* IDEATION 11.5 describes - fluent everywhere
except exactly on the fabricated detail) and `_confidence_with_dip` blends
it into confidence as a bounded, capped bonus (`_LOGPROB_DIP_MAX_BONUS =
0.25`) on top of the existing grounding-density base, never the majority of
the score - corroborating evidence sharpens a verdict, it does not replace
the reasoning behind it. Omit the trace (every caller before this feature,
every test, any non-Ollama backend) and every check behaves byte-for-byte
as it did before - additive, not a rewrite.

**"Hallucination can be of many forms" - two more claim shapes added,**
per IDEATION 11.4's routing table, which named them but left them
unbuilt pending scope: `find_absolute_claims` (overclaiming language -
"always", "guaranteed", "the only" - unverifiable by text overlap because
there is no number or name to look up; flagged as a claim SHAPE worth a
human's attention, confidence deliberately flat and modest, never graded on
the same scale as a grounded fact) and `find_unsupported_causal_claims` (a
causal connector - "because", "due to" - followed by a stated reason
sharing no content word with the question or sources; catches the model
asserting *why*, not just *what*, exactly the "invented explanation bolted
onto a real fact" pattern). Both run unconditionally alongside toxicity, not
gated behind `has_checkable_claims` (that gate is entity_not_in_source's
alone - an overclaim or an invented cause needs no number or proper noun to
exist). Real entailment-model-based checking (IDEATION 11.2's "near-solved"
case) stays explicitly unbuilt - would need an NLI model, the same
production-stack argument that kept NER out (D9/D10).

**"Highlighted with confidence embedded so the user is aware" - built as
asked.** `entity_not_in_source` changed from one combined finding per
answer to ONE FINDING PER ENTITY, each carrying its own `span` (character
offsets into the answer). Every quality-finding event now carries `span`
and `category`. The dashboard's "What you read" panel (`AnnotatedAnswer` in
`components/Marked.js`) wraps each flagged substring in a highlight with the
confidence shown as a visible inline badge (`67%`, not hidden behind a
hover) plus the full evidence in the tooltip for anyone who wants it -
composed with the existing real-value highlighting rather than replacing
it, since a hallucinated span (by construction, never a restored
placeholder) and a restored real value never overlap. Because findings
arrive async, after `answer.done`, the highlights visibly fade in a moment
after the plain text does - the UI itself demonstrates "annotated after
delivery, never a reason to hold the response" rather than just asserting
it in prose.

**A real, pre-existing precision limit, now more visible, not introduced by
this change:** live-testing the new preset surfaced `entity_not_in_source`
flagging the bare word "Hey" as an invented entity when a reply opens with
a quotation mark before it (`"Hey team, ...`) - the quote character defeats
`_starts_a_sentence`'s punctuation check, the same shape of edge case as the
"Ugh" false positive found during Phase 6. This bug predates D33 entirely;
D33 only makes it visible in a new place (highlighted inline, not just
listed below). Left as a known limitation rather than patched reactively in
this pass - see the entity-extraction section of `quality/checks.py` for
the existing heuristic and its trade-offs.

Verified live against the real model, not mocked: a new preset ("The
invented reason") gets `llama3.2:1b` to write a two-sentence update that
invents a specific, plausible cause for a delay - real per-token confidence
on the invented span (48-67%, differentiated from the surrounding text's
own average), highlighted inline with the badge, both findings ANNOTATE
tier, response delivered in full, nothing blocked. One live wrinkle worth
recording plainly: the first version of this preset's prompt reliably
produced the desired fabrication in isolated `curl` tests, then began
reliably REFUSING once run through the demo server - not a code regression
(confirmed via direct repeated `curl` calls against the same running Ollama
instance, same seed, same temperature, still refusing) but a real
characteristic of local model serving: a fixed seed reduces variance, it
does not guarantee bit-identical output forever, and a prompt sitting near
a refusal boundary can tip either way after enough time or requests have
passed. Fixed by choosing a more robustly-compliant prompt (casual
Slack-update framing, the same style that already proved reliable for the
toxicity preset), verified 3-for-3 with real repeated calls before shipping
it - not by insisting on the fragile original phrasing.

Tests: 14 new in `test_quality/test_checks.py` covering the logprob-dip
mechanism directly (a real dip raises confidence, no dip leaves it at the
base, the bonus is capped even for an enormous dip, a span absent from
`raw_text` gets no signal, omitting the trace leaves confidence identical
to the pre-D33 formula byte-for-byte) and both new claim-shape checks
(grounded causal claims left alone, ungrounded ones flagged, claims with no
content words skipped as noise rather than false-flagged, absolute language
flagged even with zero entities in play). 5 new in
`test_demo/test_orchestrator.py`, driving the ACTUAL pipeline with scripted
`(text, logprobs)` chunks - the same shape the real Ollama client yields -
rather than only unit-testing the check functions in isolation; one confirms
a real dip changes which of two ungrounded entities in the SAME answer gets
the higher confidence. Two existing tests were updated, not broken by
accident: `entity_not_in_source` returning one finding per entity instead of
one combined finding is a deliberate, disclosed shape change, and the tests
that assumed the old combined-evidence string were rewritten to check across
all findings rather than only the first. Mutation-checked: flipping the dip
clamp to always add its bonus regardless of sign turns the
no-dip-means-no-bonus test red; zeroing the token-offset increment in the
orchestrator's trace-building loop turns the real-pipeline logprob test red.
442 tests.

---

## Resolved

### D6 — buffering is a profile property, in code · 2026-08-30
`controlplane/stream/buffer.py` reads `streaming.mode` from the compiled
profile. Interactive routes buffer to commit points; throughput routes scan
once at flush, because a batch job has no reader to be ahead of. Both still
block credentials — batch is not exempt from irreversible-harm checks.

*Improved on the design while building it:* §7 proposes a 50-char overlap
window when scanning, so a secret split across two commits is caught. But
detection arrives after the first half is already released, and released is
released. We hold the boundary region back instead of re-scanning it later —
same window, one commit later, airtight rather than merely observant. Tested
at chunk sizes from 1 to 40 characters.

### D27 — the detector gap closed itself · 2026-08-30
See the D27 entry above. `entity_not_in_source` catches fabricated people for
the same reason it catches fabricated figures: no provenance. We expected to
concede this one on stage and can now demonstrate it instead.

### D25 — we can now measure being wrong, honestly · 2026-08-30
`controlplane/metrics/`. The asymmetry is built into the API rather than
described in prose: FP comes from reviewer disagreement and is exact; FN is
**estimated** from seeded canaries, and `CanaryReport.__str__` cannot render a
catch rate without also rendering the seeded distribution and a 95% Wilson
interval. A bare number is unobtainable by construction.

`not_measured` names the two proxies we did *not* build — dual-detector
disagreement and downstream incident correlation — plus unknown-unknowns. A
report listing only what it measured invites the reader to assume it measured
everything.

There is deliberately **no single trust score**. Anyone can average six
numbers onto a dial; the dial is exactly what a sceptical stakeholder should
refuse, because it hides which input moved. Metrics are per profile only —
`TrustReport` has no global aggregate to ask for.

*Found by the instrument, in the instrument:* the first sweep reported 90%.
The miss was not a detector blind spot — the AWS canary was 19 characters
where a real key id is 20, so it matched nothing and quietly depressed our own
score. Without the self-check test now guarding every template, we would have
gone hunting a gap that did not exist. Current sweep: 100% (80/80, CI
95.4–100%).

### D7 — gross, overhead and net, or nothing · 2026-08-30
See the D7 entry above. The ledger cannot produce a flattering number in
isolation, which is a stronger guarantee than remembering to be honest.

### D26 — decision logic now has four tiers and escalation rules · 2026-08-30
`controlplane/decision/tiers.py`. Allow / annotate / review / block, resolved
from **severity × confidence × profile** — never the finding alone. The same
0.80-confidence finding now BLOCKS on `customer-support` and goes to REVIEW on
`internal-knowledge`, because public-facing output justifies stopping earlier.

Humans are pulled in on mid-band confidence, on `always_review` profiles, on
policy-exception requests (D16), and on novel patterns where our confidence
estimate is itself unreliable.

Over-flagging is *tuned, not solved*, as the brief demands: a per-profile flag
budget suppresses user-visible flags once spent and diverts them to sampling,
and nothing is flagged without actionable evidence — "possible issue" is the
fatigue, not the fix.

*Two guards worth noting:* the budget can never suppress a BLOCK, or a noisy
period would silently disable the security control; and the compiler refuses
any profile that exempts a credential, so a reviewer cannot switch off
irreversible-harm blocking one override at a time.

### D24 — the feedback loop exists, and statelessness survived it · 2026-08-30
`controlplane/feedback/loop.py`. The resolution held up under test: the data
plane stays stateless, the control plane learns.

Four overrides on the same signature produce an exemption proposal, which
recompiles and republishes the bundle, and the next identical request resolves
ALLOW instead of REVIEW — with the reason `exempted by policy` and a readable
diff in the audit chain. That is the incident→action loop §23 asked for.

The load-bearing test asserts the review queue holds `customer:44219` but not
"Priya", "Sharma", the account number, or any word of the prompt. If content
could reach the queue, the loop would have quietly rebuilt the concentration
risk §3 exists to avoid.

*Deliberately conservative:* three independent reviews minimum before anything
is proposed. One annoyed reviewer at 5pm on a Friday should not be able to
widen a hole in the detector.

### D20 — control plane now does something · 2026-08-30
`controlplane/policy/` compiles JSON definitions into frozen, content-addressed
`Profile` artefacts and publishes them as a versioned bundle. The data plane
holds a dict and nothing else — a test breaks `open()` for the duration of a
lookup to prove the hot path touches no I/O.

Three profiles ship, exactly the three the Round 2 brief names:
`customer-support`, `internal-knowledge`, `decision-support`. They differ in
ways that matter rather than decoratively — customer-support runs toxicity
synchronously and inverts the outbound asymmetry (D21), decision-support
reviews every response and samples counterfactuals at 100%.

Publishing is an atomic reference swap, so demo step 7 is safe to run on stage
with traffic flowing, and every publish writes its own diff to the audit log.

*Unexpected benefit:* the compiler refuses incoherent policy at authoring
time. A typo like `block_credential` (singular) would have been a silent
security downgrade — the profile would look configured while being wide open.
It now fails to compile.

---

## Changelog

- **2026-08-29** — Created. Seeded with D1–D21 from the access-channel and
  use-case research rounds.
- **2026-08-29** — Added §0 hackathon triage after researching the AIC 2026
  format (public repo + README at Round 2; 10-min pitch + 5-min Q&A at the
  finale). Added D22 (demo doesn't fit the time budget) and D23 (public repo
  makes unmarked stubs a liability). Escalated D15 to 🔴 — it is the only
  drawback that fails live on stage. Marked D13 moot: it is a drawback of a
  feature §19 already decided not to build.
- **2026-08-29** — Round 2 brief received. Added D24–D28 for the gaps it
  exposed: feedback loops (absent), FP/FN metrics (weak), review tier and HITL
  (missing), overlapping risk categories, and loosely-governed data sources
  undercutting §9.7. Escalated D4 — the brief names multi-turn/agentic
  compounding explicitly. Revised the §0 build order: D24/D25/D26 are
  explicitly-requested solutioning areas and now outrank D2.
- **2026-08-30** — Phase 2 built (P2 policy engine, P8 audit log). **D20
  resolved.** D6 mitigated in code — `streaming.mode` is a compiled per-profile
  field. D14 built with its limitation named in the API rather than hidden.
  Track A's P3 merged to main: 150 tests, three bugs found by end-to-end use
  that unit tests had masked.
- **2026-08-30** — Phase 3 built (P6 decision tiers, P9 feedback loop).
  **D26 and D24 resolved** — four of the brief's six solutioning areas are now
  code rather than prose. D4 mitigated: session risk tracked from counters
  only. Profile confidence thresholds differentiated so the three profiles
  differ on the security axis, not only the quality axis. 249 tests.
- **2026-08-30** — Phase 4 built (P10 metrics/canaries, P11 cost ledger).
  **D25 and D7 resolved.** Five of the brief's six solutioning areas are now
  code. Model prices carry an as-of date and are overridable; an unpriced
  model raises rather than costing zero. Canary self-check test added after
  the instrument reported a fault in itself. 296 tests.
- **2026-08-30** — Phase 5 built (P4 commit-point buffer, P7 quality checks).
  **D6 and D27 resolved**; D5 now measured; D11 acted on by deliberately not
  building consistency sampling and saying why in the code. All six of the
  brief's solutioning areas are now implemented. Refined the tier rule while
  building: mid-band confidence escalates *irreversible* harm only — sending
  every uncertain hallucination flag to a human is how the review queue
  becomes noise. 346 tests.
- **2026-08-30** — Track B found a placeholder-numbering collision at the
  integration seam: `scan_inbound` numbered per call, so two customers in one
  multi-part request both became `[[CUST_A]]` and the merged mapping restored
  the wrong name. Fixed in the engine via `RequestScope` rather than by having
  the gateway concatenate parts — concatenation would have made every `span`
  point into a joined string that was never sent, breaking CONTRACTS §3 rule 4
  to work around a §3 gap. CONTRACTS §3 amended by agreement. 355 tests.

  *Third wrong-customer bug in this codebase, and the third found by using the
  thing rather than reading it.* The pattern is worth naming in the pitch: the
  restore path is where this product fails, and every one of them was invisible
  to a unit test that exercised a single call.
- **2026-08-30** — Track B's PR review produced three corrections to Track A.
  (1) Two tests in Track A's suite matched the failure shapes they identified —
  a round-trip test built from its own output, and one with no assert. Fixed,
  and the check is now on the WORKFLOW review checklist with four named shapes.
  (2) `README.md` ownership moved to Track A, which had been editing it for
  four phases without asking; the crossing is recorded in WORKFLOW §2 rather
  than quietly corrected. (3) **D23 split into D23a/D23b**, because half of it
  followed the README to a different owner — and D23b fired immediately, on
  three documents still asserting the old ownership. 356 tests.
- **2026-08-30** — Phase 6, part one: **P12 built** (the dashboard) and the
  demo pipeline moved into a `controlplane/demo/` lane. **D17 and D18
  mitigated** (not resolved - they are about the slide deck, which does not
  exist yet): every number the surface shows is now computed by a module in
  this repo during the run that displays it, and the events carry the method
  beside the number — the canary catch rate with its Wilson interval and its
  caveat, cost as gross/overhead/net together, the hallucination confidence
  with the arithmetic that produced it. The panels that cannot produce a
  number say `NOT MEASURED` or `NOT BUILT` and give the reason. 377 tests.

  **Four defects found, three of them by watching the demo rather than by a
  test.** Worth recording because they are all the same shape — a real
  module bypassed, and the bypass looking fine on screen:

  1. **The demo blocked every useful prompt.** `signals_from_findings` marked
     every finding `reversible=False`, so a known-value name at confidence 1.0
     cleared `block_at` and refused the exact input the product exists to
     handle. The first attempt at a fix was a per-profile exemption list,
     which (a) missed `payment_card`, so a substituted card still blocked,
     (b) repurposed the one field the feedback loop writes to, and (c)
     silently disabled the ungoverned floor D28 exists to demonstrate. The
     real fix is `Signal.mitigated`, set from `Finding.action`: substitution
     *is* the mitigation, so the finding still reaches the audit line and the
     metrics — it just no longer has anything to prevent.
  2. **A salutation read as a fabricated person.** `entity_not_in_source`
     kept "Dear Priya Sharma" as one three-word run, found no match for that
     exact phrase, and reported the greeting as invented.
  3. **Capitalised runs spanned line breaks.** `\s+` between words crosses
     newlines, so an email's subject line and its salutation joined into one
     eight-word "entity" that appeared in no source. The noise is the damage:
     an evidence line nobody can act on is precisely the alert fatigue the
     brief warns about.
  4. **The review queue could never fill.** Once substitution counted as
     mitigation, no inbound finding reached the review tier — correctly, since
     there is nothing for a human to decide about a value the provider never
     saw. The queue's real source of work is a *reversible* finding on a route
     whose profile reviews everything, and that was never wired.

  Two things the previous demo build did that this replaces, both of them D23
  pointed at the video: it re-implemented the commit-point buffer in three
  lines (`if "[[" in buffer and "]]" not in buffer`) while P4 sat unused, and
  the browser re-found placeholders with `/\[\[[A-Z_]+\]\]/` — hardcoding a
  format CONTRACTS §4 reserves to Track A, and already wrong, since the 27th
  customer in a request is `[[CUST_A2]]`.

  *The pattern, again:* four defects, three found by using the thing. The
  restore path and the seams around it are where this product fails, and none
  of the four was visible to a passing unit test. `tests/test_demo/` now
  drives the whole pipeline with a fake model — fourteen tests, and a
  mutation check confirms they go red when the buffer is bypassed or the
  original text is dispatched.

- **2026-08-31** — Phase 7: **D4 escalation resolved, D29 resolved.**
  `feedback/session.py`'s tracker went from built-but-unwired to live on the
  demo path: `SessionPolicy` is now a profile section, `session.risk` fires
  every request, and Transit shows a real-time panel (`4 / 3 records touched`,
  turning red over budget) with a `Run 4 turns` preset that trips it on
  camera. `geography` went from a decorative field to a jurisdiction floor a
  profile can be stricter than but never looser than — enforced by a clamp
  table in the compiler, not a convention. Both fixes reuse machinery already
  under test: the tracker's 9 tests and the fingerprint/diff machinery the
  policy patch route already had. Along the way, found and fixed a real,
  intermittent bug the new tests exposed: `uuid.uuid4().hex[:12]` has a ~0.3%
  chance of landing all-digits, which the audit log's own guard then refused
  to write as a possible card number — a live crash risk on stage, not just a
  flaky test, fixed by prefixing the id rather than making the collision
  merely rarer. 401 tests.

- **2026-09-01** — **D30 resolved (retired).** Prompt injection detection —
  step 3 of the pre-flight gate since the earliest design pass, never
  implemented — removed from [IDEATION.md](IDEATION.md) §8/§20,
  [BUILD-PLAN.md](BUILD-PLAN.md) P5, and [DEMO-SCRIPT.md](DEMO-SCRIPT.md),
  rather than filled. Two reasons, argued in full in D30: it duplicates a
  defense the model provider already runs with better visibility than we
  have, and the one variant that would be genuinely ours — talking the model
  into revealing the value behind a placeholder — has no target, because
  substitution means the model was never given the value to reveal. No code
  or test count changed; this is a documentation-only correction.

- **2026-09-01** — **D31 resolved.** `quality.toxicity()` went from a
  labelled stub to a real check: `alt-profanity-check`, a pretrained
  classifier we import rather than train, exactly as IDEATION 10.2 always
  specified. First exception to Track A's stdlib-only engine, taken
  deliberately over a heavier transformer option to keep the "no network,
  offline" claim true. Wired into the async quality pass alongside
  `entity_not_in_source`; fails open on a missing dependency. Caught and
  fixed a real wiring bug before it shipped: `has_checkable_claims` was
  gating the whole quality pass, not just the hallucination check, so a
  toxic reply with no numbers or proper nouns would have skipped toxicity
  silently. New preset "The internal vent" demonstrates it live against the
  real model and the real classifier - a genuinely toxic reply scored 0.82,
  delivered in full, flagged afterward. Zero dashboard code changed; the
  generic event-driven panel renders it the same way it renders every other
  finding. 410 tests.

- **2026-09-01** — **D32 resolved.** `/demo/bias` generalised off a single
  hardcoded hiring-decision template. `find_subject()` locates the
  counterfactual slot in an arbitrary prompt by reusing the hallucination
  check's own proper-noun detector, rather than requiring a `{}` authored in
  advance; `parse_forced_choice()` reads the outcome vocabulary out of the
  prompt's own instruction instead of a hardcoded Python if-statement. A
  prompt that isn't a forced choice gets an honest free-text tier - raw
  transcripts, no invented label - rather than a fabricated disparity rate;
  deliberately rejected a second-LLM-judge approach for the same reason
  IDEATION already rules out AI-as-judge for hallucination. Verified live
  against three genuinely different prompts (a hiring decision, a loan
  review, a free-text performance note) with zero shared demo-specific code
  between them. Dashboard gained a free-text field to type and probe any
  request. Live-traffic sampling (`counterfactual_sample_rate`) remains a
  separate, unwired next step - out of scope for this pass on purpose. 423
  tests.

- **2026-09-01** — **D33 resolved.** Hallucination detection: more claim
  shapes, real per-token confidence, inline highlighting. Rejected the
  literal "ask the model its own confidence" as the same AI-as-judge
  anti-pattern D11/D12/D30/D32 already ruled out; built the correct version
  IDEATION 11.5 always specified instead - Ollama 0.33+'s real logprobs,
  confirmed live, read as `TokenLogprob` and blended as a capped, minority
  bonus on top of the existing grounding-density base, never replacing it.
  `entity_not_in_source` now returns one finding per entity, each with its
  own answer-text span; two new claim-shape checks
  (`find_absolute_claims`, `find_unsupported_causal_claims`) catch
  hallucination with no number or name in it at all. Dashboard highlights
  every flagged span inline with the confidence visible as a badge, not
  hidden behind a hover, composed with the existing real-value highlighting
  rather than replacing it. New preset ("The invented reason") verified live
  against the real model; a real local-model non-determinism wrinkle
  (a prompt that reliably worked in isolated tests began reliably refusing
  once run repeatedly through the demo server) was diagnosed as genuine
  model-serving variance, not a code regression, and fixed by choosing a
  more robust prompt rather than insisting on the fragile one. 19 new tests,
  two mutation-checked; two existing tests updated for the deliberate,
  disclosed per-entity return-shape change. 442 tests.

- **2026-09-02** — **Gap-closure phase 0.** Committed and pushed the D31/D32/D33
  work, then merged Track B's gateway spine and seed generator. This repository
  had been shipping `controlplane/gateway/` and `controlplane/seed/` as ten-line
  TODO stubs with an empty `tests/test_gateway/`, while the real 1,893 lines sat
  on a fork — so the README's "change one line, your `base_url`" claim had no
  runnable code behind it for anyone who cloned the public repo. The merge was
  rehearsed on a throwaway branch first: it applied cleanly, and the only
  deletions were the ten `# TODO(Track B)` markers. None of the collisions
  anticipated in GAP-CLOSURE-PLAN.md phase 0.2 materialised, because our side
  already held the newer copies of the files at issue.

  The headline claim is now checkable rather than assertable —
  `test_openai_client_with_only_base_url_changed` drives an unmodified
  `openai.AsyncOpenAI` client at the gateway and reads back the restored real
  name while the upstream saw only the placeholder.

  Also corrected the counts that had drifted: the README's per-part test numbers
  were stale (the substitution engine row said 150 against a real 160, the audit
  row said 25 against 20) and did not sum to anything. They are now per test
  directory and sum exactly to the total, with the phase rows marked as living
  inside the part rows rather than adding to them. EXPLAINED.md §8.3 has been
  rewritten from "ships as stubs" to the resolution, keeping the original
  finding visible — a gap that was fixed and a gap that never existed are not
  the same thing. 470 tests.

- **2026-09-02** — **Gap-closure phase 1: honesty.** Nothing on the Profiles
  page now claims a behaviour the code does not have.

  **One finding in my own audit was wrong, and is corrected rather than quietly
  dropped.** EXPLAINED.md §8.2 listed `inbound.block_credentials` as declared
  but unread. It is not: the compiler refuses to build a profile that disables
  it, `test_credentials_cannot_be_allowed_through` covers it, and the Profiles
  page has a button that demonstrates the refusal live. The audit's grep
  excluded `policy/profile.py` — which is exactly where the guard lives. The
  outbound twin genuinely *was* declared and unguarded, an asymmetry with no
  argument behind it, and now refuses on the same terms: a credential that
  reaches a reader's screen is irreversible the moment it renders.

  **`substitute_pii` was going to be deleted, and should not have been.** The
  plan's ADR-3 said any switch whose only effect is shipping real PII should be
  removed. Reading the code first turned up a comment already documenting a
  legitimate use: a code-assistant route, where developers paste variable names
  that read as identifiers and placeholdering them wrecks the answer. Deleting
  a real capability on my own say-so would have been the wrong call, so the
  field stays and gains a guard instead — turning it off now requires
  `inbound.pii_waiver_reason`, free text that lands in the compiled artefact
  and therefore in the fingerprint and the audit chain. The decision to send
  real PII can be made; it cannot be made anonymously or by accident.

  **The declared-vs-enforced gap is now structural, not a one-time cleanup.**
  `policy/enforcement.py` declares the state of all 29 profile fields with a
  reason each; `/demo/profiles` serves it; the Profiles page greys every
  declared-only row and chips it with the phase that will wire it. Crucially,
  `test_enforcement.py` walks the `Profile` dataclasses and fails the build if
  a field is added without an entry, or if an entry describes a field that no
  longer exists. Verified by adding a field and watching it go red.

  Three smaller corrections: the quote-mark false positive is fixed (a reply
  opening `"Hey team,` no longer reports `Hey` as fabricated) — and the first
  attempt at that fix was itself wrong, stripping whitespace and quotes in
  separate passes so `She replied. "Hey` still failed, which the test caught
  because it checks position fourteen and not only position zero. `RESTORE` is
  gone from the event contract, where it had been declared and never emitted.
  numpy is pinned: the toxicity model is a pickled artefact that already warns
  under NumPy 2.5, and an unpinned float breaks it on a clean install at the
  worst possible moment. 484 tests.
