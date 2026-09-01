# ControlPlane — Drawbacks, Gaps and Accepted Trade-offs

**Living document.** Updated as ideation progresses. Last updated: 2026-08-31.

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
