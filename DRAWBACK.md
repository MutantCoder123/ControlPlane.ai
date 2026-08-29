# ControlPlane — Drawbacks, Gaps and Accepted Trade-offs

**Living document.** Updated as ideation progresses. Last updated: 2026-08-29.

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
| **Format risks, decide now** | **D22**, **D23** | Demo does not fit the time budget; stubs must be labelled as stubs |

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
⚪ `accepted`

Real cost, well covered by the reader-vs-model argument (§7): a person reads
~4 words/sec, a model emits ~50, so the buffer is permanently ahead of the eye
after the first pause.

### D6 — …but that argument only holds where a human reads a stream
🟠 `open`

For document batch processing, agentic workflows and embeddings there is no
reader, so the buffer is pure added latency with no cover story. §7 currently
presents it as universal.

*Stance:* the buffer is a property of the **route profile**, not of the
gateway. Throughput-mode scanning for non-interactive profiles.

### D7 — We add cost to a system we claim reduces cost
🟡 `mitigated`

Consistency sampling and counterfactual probing multiply token spend.

*Mitigation:* cap evaluation spend as a share of protected spend, adaptive
sampling, and **report gross saving, our overhead, and net** rather than a
flattering gross number. A judge who suspects we are hiding it will ask.

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
🟠 `open`

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
🟡 `open`

Hash-chaining proves tamper-evidence, but the chain lives in process memory.
Production needs append-only storage with the chain anchored externally —
otherwise an attacker who owns the process rewrites the whole chain.

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
🔴 `open`

The shadow-AI numbers (share of pasted content containing sensitive data,
personal-account usage, added breach cost) all describe browser and
personal-account channels — exactly the ones D1 says we miss. Putting them on a
slide and then demoing a `base_url` proxy is a mismatch a sharp judge catches.

*Stance:* use enterprise **API spend growth** and **regulated first-party
deployment** framing instead. Keep shadow-AI stats only if we explicitly scope
them as "the adjacent problem we do not solve."

### D18 — Our source statistics are marketing-grade and mutually inconsistent
🟠 `open`

The sensitive-paste rate appears as both 11% and 39.7% citing the same vendor.

*Stance:* slide-safe only where a named primary source exists (Gartner, IBM
Cost of a Data Breach). Verify anything else against the primary report before
it reaches a slide.

### D19 — Three shallow pillars read as a wrapper around three API calls
🔴 `open`

The doc's own warning (§23). Breadth without depth places mid-table.

*Stance:* build inbound substitution + known-value matching deep, stub the rest
convincingly, spend the saved time on the incident→action loop and dashboard.

### D20 — The control plane is described but does not yet *do* anything
🟠 `mitigated` · **solve — best return on the list.** Route profiles are cheap to
implement and *buy* a demo step rather than just closing a hole. They also make
§16's data-plane/control-plane claim true in code, which matters now that the
repo is public (D23).

§16 asserts a data-plane/control-plane split, which is what earns the product
name — but nothing in the design was actually authored centrally and pushed.

*Mitigation:* **route profiles** (§5) give the control plane a real artefact to
compile and push, and make the live-policy-change demo natural.

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
🟠 `open` · **solve — cheaply, by labelling**

Round 2 requires a public GitHub repo and a README documenting architecture.
§19's build/explain split assumes judges see only the demo. They do not — a
reviewer can open the code and check whether the README's claims exist.

*Stance:* stubs are fine; **unmarked** stubs are not. Anything described in the
README but not implemented must say so in the code and the README, in the same
words. An honest `# not implemented for prototype — see IDEATION §19` scores
better than an empty function where a bias probe was promised. This costs
about an hour of discipline and removes a whole class of reviewer suspicion.

---

## 6. Gaps exposed by the Round 2 brief

The brief names six solutioning areas. We were strong on three, partial on one,
and absent on two. These entries are the delta.

### D24 — We had no feedback loop, and it collides with statelessness
🔴 `mitigated` · **solve — it is the incident→action loop we already wanted**

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
🔴 `mitigated` · **solve — cheap with simulated data**

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
🟠 `mitigated` · **solve — mostly design, small build**

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
🟠 `mitigated` · **answer, don't build**

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
🟠 (was ⚪) · **answer, don't build**

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

---

## Resolved

*(Nothing yet. Entries move here with the date and what changed.)*

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
