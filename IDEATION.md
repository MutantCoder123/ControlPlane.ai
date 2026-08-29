# ControlPlane — Ideation Document

Accenture Innovation Challenge 2026 · Problem statement: ControlPlane.ai

Companion document: [DRAWBACK.md](DRAWBACK.md) — the internally honest list of
gaps, weaknesses and accepted trade-offs. §22 here is the pitch-facing subset.

---

## 1. What we are building

A gateway that sits between an organisation's applications and any LLM
provider. Every request and every response passes through it. The
application changes one line — its `base_url` — and nothing else.

**One-sentence pitch:** the layer that lets a regulated organisation put
real company data into a third-party model, without the sensitive parts
ever leaving the building.

**Scope, stated up front:** we govern the **first-party application path** —
the systems the organisation builds and is the data controller for. We do not
intercept browser sessions, personal-account shadow AI, or AI embedded in
third-party SaaS. §4 sets out the full channel map and why this is the channel
worth owning rather than a shortfall.

---

## 2. Who buys it

**The regulated enterprise.** Banks, insurers, hospitals, telcos. The
person who signs is the one currently *blocking* AI adoption — the
compliance officer, the CISO, the data protection lead.

Frame the product as the thing that turns their "no" into a "yes."

**Explicitly not our buyer:** the model providers themselves. Their
needs (abuse detection, tenant capacity, output liability) barely
overlap with ours, and our most differentiated feature — inbound data
substitution — is irrelevant to them. It is a different product, not a
second market.

**Why this buyer for this panel:** Accenture's business *is* helping
large regulated organisations adopt technology. A judge from that world
recognises "legal won't sign off" instantly.

---

## 3. Scope decision — gatekeeper only

We are **stateless**. We store no conversation history, no user context,
no personalisation data.

**Considered and rejected:** holding user history and injecting it as
substituted placeholders to give personalised answers without exposure.

**Why rejected:**
- Our entire value is "we retain nothing, and you can verify that." That
  is what earns a light security review and lets us sit in the request
  path at all.
- A gatekeeper's failure mode is *degraded* (requests fail, retry). A
  memory store's failure mode is *catastrophic* (leak = every
  conversation ever). The stricter component sets the review bar for the
  whole product.
- We would become the concentration risk we are selling protection from.
- Personalisation is a different hard problem (retrieval, ranking,
  freshness) requiring different expertise.

**The position instead:** *"We don't store your context. We make your
context safe to use."* We are the layer every personalisation platform
sits behind — adopted by all of them rather than competing with each.

Revisit only as a separately-reviewed component, never folded into the
gateway.

---

## 4. Where we sit — the channel we govern

An organisation's data reaches a model through nine distinct channels, and a
`base_url` swap intercepts only some of them. Stating which, before being
asked, is the same credibility move as §3.

| Channel | Example | Intercepted? |
|---|---|---|
| First-party app → provider API | Own service calls OpenAI/Anthropic | **Yes** |
| First-party app → cloud-hosted model | Azure OpenAI, Bedrock, Vertex | Yes, but config not one line |
| Self-hosted open-weights | vLLM in own VPC | Yes (OpenAI-compatible) |
| Embedded AI in third-party SaaS | M365 Copilot, Salesforce Einstein | **No** |
| Vendor chat UI, corporate SSO | ChatGPT Enterprise, claude.ai | **No** |
| Vendor chat UI, personal account | Shadow AI | **No** |
| Browser extensions / AI browsers | AI sidebars | **No** |
| IDE coding assistants | Copilot, Cursor, Claude Code | Often — many accept a base-URL variable |
| Batch pipelines | Embeddings, evals, fine-tune upload | Partly — different endpoints |

**Our scope, stated deliberately: the first-party application path.**

This is not a shortfall we are conceding, it is the channel worth owning:

- It is where the organisation is the **data controller building its own
  product** — it holds both the liability and the control.
- It is the only channel where inbound substitution (§9.3) is even coherent.
  You cannot substitute into a prompt a human is typing into someone else's
  browser.
- It is where regulated enterprises are actually spending — the customer-facing
  and back-office systems that legal is currently blocking.

Shadow AI and browser-level prompt activity are a **real and adjacent problem,
and a different product category** — browser agents and enterprise browsers,
not gateways. Gartner puts embedded copilots in 40% of enterprise applications
by end-2026, so this gap grows rather than shrinks. Say so; do not pretend to
cover it.

> *"We govern the path where you are the data controller. The browser is
> somebody else's product."*

---

## 5. What runs through us — use-case families and route profiles

### 5.1 The nine families

The same gateway carries very different workloads, and they stress different
pillars. Three properties decide which checks fire: **who sees the output**,
**whose data goes in**, and **is it grounded**.

| Family | Examples | Output seen by | Dominant risk |
|---|---|---|---|
| **A. Customer-facing chat** | Support bot, banking assistant | The public | Cross-customer leakage; wrong answer becomes a commitment |
| **B. Internal assistant** | HR bot, IT helpdesk, policy Q&A | Employees | Pasted customer records; over-entitled answers |
| **C. Document / batch** | Contracts, claims, KYC, clinical notes | Nobody live | Dense-PII inbound at volume |
| **D. Report generation** | Board summaries, financial reports | Employees, then public | Derived-claim arithmetic |
| **E. Decision about a person** | CV screening, loan/insurance underwriting | Employee, affects a subject | **Bias**; EU AI Act high-risk |
| **F. Code assistance** | Copilot-class, code review | Developers | **Secrets in code** |
| **G. Agentic workflow** | Multi-step automation, MCP tools | Often no human | Sprawl (5–30× tokens/task), unreviewed action |
| **H. Embeddings / indexing** | RAG ingestion | Nobody | The entire corpus ships to the provider |
| **I. Eval / LLM-as-judge** | Regression suites | Nobody | Pure cost line |

Coding dominates by raw token volume — it went from 11% to over 50% of tokens
on OpenRouter through 2025 — but output tokens cost 4–5× input, so **spend**
concentrates in A, C and D, and G multiplies everything it touches.

### 5.2 The use case is the policy unit

There is no single correct configuration of this gateway, and pretending
otherwise is how governance products become unusable. Each family compiles to a
named **route profile**:

**The three the Round 2 brief names** — a customer support assistant, an
internal knowledge assistant, and a decision-support tool in a regulated
workflow — are families A, B and E. Those are the three profiles we build and
demo; the rest of the table is the generalisation argument.

```
customer-chat      → outbound block ON, toxicity SYNC, halluc tier-2 always, cache OFF
internal-assistant → inbound substitute ON, entitlement ON, cache ON (tenant-scoped)
doc-batch          → substitute ON, buffer OFF (no reader), grounded entailment ON
person-decision    → unbiased mode ON, counterfactual sampling 100%, full audit
code-assist        → tier-1 credential block ON (both directions), PII substitution OFF
```

Four things this buys:

1. §11.5's *"customer-configured policy, not inferred"* becomes a mechanism
   rather than a sentence.
2. The control plane (§16) finally has a concrete artefact to **author,
   compile and push** — this is what earns the product name.
3. Demo step 7 (change a policy live, rerun, get a different result) becomes
   the obvious demo: flip `internal-assistant` → `customer-chat`, same prompt,
   different outcome.
4. **Onboarding is "pick your profile,"** not a configuration project — the
   same adoption argument as §9.7's "we inherit their classification."

### 5.3 What the families change about the design

- **The commit-point buffer is a profile property, not a global one.** The
  reader-vs-model argument (§7) only holds where a human reads a stream —
  families A, B, D, F. For C, G and H there is no reader, so the buffer is
  latency with no cover story. Those profiles scan in throughput mode.
- **The inbound/outbound asymmetry (§9.6) inverts in family A.** There the
  inbound PII arrives from the data subject themselves, and the catastrophic
  direction is outbound: customer X seeing customer Y's record. Same
  machinery, opposite threat model, selected by profile.
- **Family H is an unguarded door.** A chat-completions proxy never sees
  `/v1/embeddings`, yet RAG ingestion is the single largest bulk egress of
  internal documents in a typical deployment. Same scanner, different endpoint.

---

## 6. The core architectural principle

> **Split checks by whether the harm can still be undone after the user
> sees it — not by how fast the check is.**

| Harm class | Reversible? | Placement |
|---|---|---|
| Credentials, secrets, PII | No — screen-recordable | Synchronous, before release |
| Hallucination, toxicity, bias | Yes — annotate afterwards | Async, after release |
| Cost | Never user-visible | Before dispatch |

This dissolves the usual "safety vs latency" tension: only the small,
fast category has to be synchronous.

**This is the answer to the TOCTOU / screen-recording problem.** Once a
token reaches the browser it is in the DOM and in the stream. A kill
switch after the fact is theatre.

### 6.1 "But the risk categories overlap" — which is why we don't split by category

A fabricated detail about a real person is simultaneously a hallucination and a
privacy exposure. Under a category-based taxonomy you must decide which bucket
it belongs in, and the choice changes the handling — which is why clean
categorisation is genuinely hard.

**We never ask the question.** Our axis is *reversibility*, which is orthogonal
to category. Fabricated PII rendered on a customer's screen is
screen-recordable, therefore irreversible, therefore synchronous — regardless
of which of the three risk names you attach to it. A response can be all three
at once and still resolve to exactly one placement.

> **Overlap is a problem for a taxonomy that classifies the risk. It is not a
> problem for one that classifies the harm.**

*Honest gap, stated here rather than discovered on stage:* the overlap case is
hard for our **detector**, even though the principle handles it cleanly. An
invented name is not in the known-value store, so §9.2 misses it; only the
pattern tier or a real NER model would see it. The architecture is right and
the detector needs the NER tier to cover this case (D27).

---

## 7. The commit-point buffer

Tokens from the model are **not** passed straight through. They
accumulate until a commit point, are scanned, and only then released.

Commit point = whichever comes first:
- a sentence boundary (natural, invisible)
- ~40 tokens (stops runaway single-sentence paragraphs)
- ~250 ms (stops a slow model stalling the stream)

**Why the delay is invisible — the key pitch line:**

> A person reads ~4 words/sec. A model emits ~50. You pause once, for
> about a fifth of a second, at the very start. After that the buffer is
> permanently ahead of the reader's eye. Cost: one sentence of TTFB.
> Steady-state perceived latency: zero. **We are not racing the model,
> we are racing the reader.**

**Must-fix bug:** a secret split across two commits matches neither half
and escapes silently. Keep a ~50-character overlap window from the
previous chunk when scanning; ignore anything found entirely within the
overlap.

**Scope of the argument — do not overstate it.** "Racing the reader" only
works where there *is* a reader. For document batch processing, agentic
workflows and embeddings (families C, G, H in §5.1) nothing renders to a
human, so the buffer is latency with no cover story. Buffering is therefore a
**route-profile property, not a global one**; non-interactive profiles scan in
throughput mode instead. Volunteering this is what stops the pitch line from
sounding like a slogan.

---

## 8. Pre-flight gate — everything before we spend money

Order is deliberate:

1. **Identify** — key → team. Nothing works without attribution.
2. **Budget** — estimate cost, refuse if over cap. Refusing here costs zero.
3. **Injection** — protect the model from the user.
4. **Inbound sensitive data** — protect the org from its own paste habit.
5. **Route** — cheapest model that plausibly handles this.

**Critical correction to the original Gemini design:** it proposed
forwarding upstream and cancelling on failure. You are billed the moment
tokens are generated — you would block the request and still pay. Check
first, dispatch second. This is what makes the cost pillar real instead
of contradicting the safety pillar.

---

## 9. Sensitive data handling

### 9.1 Two tiers — state this split openly

| Tier | Examples | Method | Deterministic? | Action |
|---|---|---|---|---|
| Structured secrets | API keys, JWTs, cards, Aadhaar | Pattern + **checksum** | Yes | Block, synchronously |
| Unstructured PII | Names, addresses, health details | NER model | No | Flag / substitute |

The checksums (Luhn, Verhoeff, mod-97) are what make tier 1 genuinely
deterministic — without them every long order number looks like a card.

**Happy accident worth saying out loud:** the deterministic/probabilistic
boundary lands almost exactly on the irreversible/reversible boundary. A
leaked API key is exploitable forever; a leaked first name usually is
not.

### 9.2 Known-value matching — our strongest differentiator

Pattern matching asks *"does this look like a secret?"*
Better question: ***"is this OUR secret?"***

The organisation already knows its own sensitive data — CRM, HR system,
secrets manager. Hash every value, load hashes into memory, put a Bloom
filter in front. Scan for known hashes.

This flips every weakness of regex:
- Catches **unstructured PII deterministically** — we don't guess "Priya
  Sharma" is a name, we know she's customer 44219.
- Catches **internal formats** we never wrote a pattern for.
- **Test data stops firing** — `4111 1111 1111 1111` passes Luhn but
  isn't in the customer database.
- Audit line becomes "matched customer record 44219" instead of "matched
  a regex."

Raw values never stored. Limitation: exact match only — normalisation
helps, doesn't fully solve.

### 9.3 Substitute, don't destroy

Swap real values for consistent placeholders before dispatch; swap back
on the way out. The model reasons about placeholders fine — it doesn't
need a real name to draft a refund email.

- Answer stays complete (no utility/safety trade)
- Provider **never receives real personal data at all** — a far stronger
  compliance claim than "we redact when we detect"
- Same entity → same placeholder, so relational reasoning survives

Mapping lives in memory for one request, then discarded.

### 9.4 The computation problem — solved

**Substitute identifiers, never operands.**

Sensitivity lives in the *linkage*, not the value. "₹45,230" is
meaningless alone; "Priya's salary is ₹45,230" is sensitive because of
the name. Swap the name, the number passes through, arithmetic is
correct, restore on return.

> **Break the linkage, preserve the arithmetic.**

Genuine failure case: when the identifier *is* the operand ("validate
this account number's checksum"). Needs policy exemption or a locally
hosted model.

### 9.5 Block vs substitute

- **Credentials → block.** No legitimate reason to send an API key to a
  model. Refusing costs the user nothing.
- **Customer/employee PII → substitute.** This is the *use case*, not the
  abuse case.

**Rejected reasoning: "just block everything, it's the user's fault."**
Under DPDP/GDPR the *organisation* is liable regardless of who pasted it
— "your employees shouldn't have done that" removes no risk, it only
moves blame. And blocking every prompt containing customer data blocks
the entire reason they bought the tool.

### 9.6 Inbound vs outbound asymmetry

| | Threat | Right action | Volume |
|---|---|---|---|
| Inbound | Our data reaching a third party | Substitute | High — must be cheap |
| Outbound | User sees what they're not cleared for | Block | Lower — afford scrutiny |

Most teams build one filter for both directions. Naming the asymmetry
signals deployment experience.

**The asymmetry inverts for customer-facing chat (family A, §5.1).** There the
inbound PII arrives *from the data subject themselves* — the customer typing
their own account number — while the catastrophic direction is outbound:
customer X shown customer Y's record. Same machinery, opposite threat model,
selected by route profile. Handling both directions under one policy engine is
a stronger claim than the one-directional framing above.

### 9.7 Who defines "sensitive"

**Not us.** The organisation already classified its data — CRM, HR,
secrets manager, existing classification scheme. We *inherit* their
classification.

- No labelling project required to onboard (this is what kills enterprise adoption)
- Automatically consistent with what they told their regulator
- Correct for their internal formats with no pattern writing

Ship a regulatory baseline (DPDP / GDPR / PCI identifier types) for day-one
value; connectors to their systems of record are what make it stick.

> *"We don't ask the customer what's sensitive. They already decided.
> We read their answer."*

---

## 10. Toxicity and bias

### 10.1 They are not the same problem — separate them

- **Toxicity is a property of one response.** Slurs, harassment, threats.
  Detectable live.
- **Bias is a property of a distribution.** A model recommending the male
  candidate 70% of the time produces no individually-detectable response.
  **Structurally cannot be caught per-response.**

Anyone claiming real-time bias detection is doing toxicity detection and
mislabelling it.

### 10.2 Toxicity

Off-the-shelf classifier, milliseconds, on the **async path** — toxicity
is reversible harm. Don't pay TTFB on every response for a probabilistic
classifier that's wrong 5% of the time.

Exception: a small set of severe categories block synchronously and we
accept false positives.

### 10.3 Bias — measured in aggregate

**Outcome distribution monitoring.** Record outcomes alongside the
attribute; compare rates over hundreds of requests. No clever detection
— it's counting. This is the method regulators accept, because it
measures *effect* not intent.

**Counterfactual probing — our best asset here.** Same request, one
attribute changed (name, postcode, pronoun), compare answers. If the
recommendation flips, that's demonstrable bias.

Why it's strong: it produces **evidence, not a score**. "Classifier rated
this 0.7 biased" is arguable. "Same CV, rejected under one name,
advanced under another — here are both transcripts" is not. Runs as a
scheduled job on sampled traffic, not per-request.

### 10.4 Rejected: masking bias terms before dispatch

The idea: strip demographic terms so the answer must be unbiased.

This is **fairness through unawareness** and it is known to fail:
- Protected attributes leak through correlated features — postcode
  encodes ethnicity, school name, phrasing, employment gaps
- Amazon's recruiting tool: gender removed explicitly; model learned to
  penalise "women's" and favour male-correlated verbs
- **Masking removes our ability to detect bias without removing the
  bias** — worse than nothing, because we then believe we're safe
- Semantically destructive: breaks diversity, legal-compliance, and
  research use cases
- The term list is culturally specific, contested, and never complete

**What we keep:** the same primitive, inverted. Masking is a bad
mitigation and an excellent *measurement instrument* — vary the
attribute instead of hiding it. No unmasking problem, because we compare
rather than restore.

### 10.5 "Unbiased mode" — opt-in only

Narrow legitimate case: the request is **explicitly a decision about a
person** (CV screening, loan, tenancy) where using the attribute is
illegal *regardless of outcome*. Masking satisfies a legal requirement
about **process**, not a technical one about fairness.

Ship with the honest label: *"removes direct attributes; does not
guarantee unbiased outcomes — pair with outcome monitoring."*

**Note on the LLM-rewriter version:** it cannot be asynchronous — a
rewriter must finish before dispatch, so it costs real TTFB. It also
introduces new risks: it may smooth phrasing and standardise non-native
English, erasing the distinctiveness it was meant to protect; and it is
non-deterministic, which is a serious problem for a decision that may
reach a tribunal. **If built, logging the original + rewrite diff is
mandatory.**

Better use of a small LLM here: deciding *whether this request is a
decision about a person at all* — the judgement regex can't make.

> *"Masking satisfies the legal requirement about process. The probe
> satisfies the question about outcome. You need both, and most tools
> only do the first."*

---

## 11. Hallucination

### 11.1 Two different problems

- **Grounded** (documents retrieved): we have ground truth → check claims
  against source. Near-solved.
- **Ungrounded**: no ground truth → infer whether the model *knows* or is
  improvising. The hard case.

### 11.2 Grounded

Break into claims; for each ask **does the source entail this?** Use an
entailment model, not word overlap — negation destroys overlap ("covers
water damage" vs "does not cover water damage" share nearly every word).

Three outcomes, two severities:
- **Contradicted** = an error
- **Unsupported** ≠ false — it means the model added parametric knowledge.
  In a RAG deployment that's a **scope breach**, since the premise was
  "answer from our documents."

### 11.3 Ungrounded — check stability, not truth

Not *"is this true"* but *"does this model actually know this."*
Retrieval from memory is stable; improvisation is not.

- **Ask the claim back narrowly** — extract one assertion, re-ask just
  that. Short answers make divergence unambiguous. Often cheaper than the
  original request.
- **Reverse the question** — real knowledge is consistent in both
  directions; fabrication frequently isn't.
- Compare **facts** (numbers, dates, proper nouns), not wording.
  Rephrasing is normal and meaningless.

### 11.4 Choosing the technique — route by how the claim fails

**First, filter out the uncheckable:** opinions, legitimately ambiguous
questions (divergence there is *correct behaviour* — biggest source of
false positives), and already-hedged claims.

| Claim shape | How it fails | Technique |
|---|---|---|
| Point fact (date, number, name) | Invents a plausible value | Consistency sampling |
| Existence (citation, section, case) | Referent doesn't exist | Ask what it contains |
| Relational (X acquired Y) | Direction/participants swapped | Reverse the question |
| Derived (averages, totals) | Arithmetic error | Recompute from parts |
| Attributed ("per RBI guidelines") | Real source, invented content | Existence + content |

> **Key insight: consistency sampling only works where the failure is
> random.** Where the model fails *systematically* — invented citations,
> bad arithmetic, reversed relations — it fails identically every time
> and sampling scores it as reliable. That's the trap.

### 11.5 The cascade — what triggers a check

Resolves the circularity of "only check flagged responses" (nothing would
ever trigger).

**Tier 0 — free, every response.**
- Any checkable claims at all? (No numbers/dates/proper nouns → skip
  entirely. Removes most traffic. Frame as *"we check responses that
  contain checkable claims"*, not *"we check 10% randomly to save money."*)
- Token confidence dips — fluent sentence, low confidence exactly on a
  date or name. Classic fabrication fingerprint, free if the provider
  exposes logprobs.
- **Entities in the answer absent from question and sources** — highest
  yield single check, pure set comparison.
- Specificity density + absence of hedging: precise *and* certain is the
  risk profile.

**Tier 1 — cheap.** Extract the flagged claim, re-ask narrowly.

**Tier 2 — shape-specific technique from the table above.**

Cascade, don't parallelise: cost stays proportional to risk, not volume.

**Overrides:** high-stakes domains (legal, medical, financial),
customer-facing output, and outputs feeding automated action skip
straight to tier 2. Customer-configured policy, not inferred.

**Random baseline** on everything else — not to catch much, but to
measure whether our own triage works. *"We sample randomly to measure our
detector's precision"* is a strong thing to say.

### 11.6 What to do on a catch

- **Never silently delete** — user loses trust in the whole system
- **Never auto-correct** — we don't know the right answer, only that the
  model was unstable
- **Attribute**: mark the claim, say why, show the divergent alternatives.
  *"This figure varied across samples: 30 / 45 / 60 days"* beats a
  warning icon — it tells the user exactly what to verify
- **Abstention** on high-stakes routes: replace with an explicit "I don't
  have reliable information on this."

> A model that says it doesn't know is worth more than one that's right
> 90% of the time, because the user can act on the admission.

### 11.7 Limitation to state openly

Catches *invented* facts. Does **not** catch consistently-held false
beliefs — if the model reliably believes something wrong, all samples
agree and we score it trustworthy. Only retrieval against real sources
fixes that.

---

## 12. Decision logic — tiers and human escalation

Detection is worthless without a graded response. A binary allow/block forces
every uncertain finding into one of two wrong answers.

### 12.1 Four tiers, mapped to reversibility

| Tier | When | User sees |
|---|---|---|
| **Allow** | No finding, or finding below threshold | Nothing |
| **Annotate** | Reversible harm, evidence available | Response plus a marked claim and *why* (§11.6) |
| **Flag for review** | Mid-band confidence, or high-stakes profile | Response delivered; a reviewer gets it queued |
| **Block** | Irreversible harm, high confidence | Refusal with a reason and a route to exception |

**The tier is a function of severity × confidence × profile — never of the
finding alone.** The same detection resolves differently under
`internal-assistant` and `customer-chat`. This is what makes route profiles
(§5.2) load-bearing rather than decorative.

### 12.2 When a human is pulled in

Not on every flag — that is the fatigue trap. A human is pulled in when:

- **Confidence sits in the mid-band.** The extremes are exactly where automation
  is reliable; the middle is where it is not. Escalating the middle is the
  honest use of a reviewer.
- **The profile says so regardless of confidence** — `person-decision` routes
  everything to review, because the legal exposure justifies the cost.
- **A policy exception is requested** — the identifier-is-operand case (§9.4)
  is a human decision, not a threshold.
- **The detector sees something novel** — a pattern with no prior, where our
  confidence estimate itself is unreliable.

### 12.3 Over-flagging is tuned, not solved

The failure mode the brief names correctly: too many flags and users learn to
dismiss them, which is worse than not flagging, because now there is a control
that everyone believes is working.

Three mechanisms, all deliberate trade-offs rather than fixes:

1. **The cascade already suppresses volume** (§11.5) — most traffic never
   reaches a checker at all, because it contains no checkable claim.
2. **Flag budget per profile.** A cap on flags per hundred responses. Exceed it
   and the threshold auto-tightens, with the overflow diverted to sampling
   instead of the user. The budget is a policy value the customer sets — they
   own their own fatigue tolerance.
3. **No flag without actionable evidence.** "Possible issue" is fatigue.
   *"This figure varied across samples: 30 / 45 / 60 days"* is a task. If we
   cannot say what to check, we do not interrupt.

> *"We did not solve the precision/recall trade-off. We made it a policy value,
> gave it a budget, and made the trade visible to the person who owns it."*

---

## 13. Feedback loops — how detection improves

### 13.1 The tension with statelessness, and its resolution

A feedback loop implies memory. §3 says we store nothing. Both are true:

> **The data plane stays stateless. The control plane learns.**

Feedback is never per-request state. It is *aggregate statistics about
decisions*, accumulated centrally and compiled into the next policy artefact
that gets pushed to the checkpoints (§16). A checkpoint never remembers a
request. The control plane remembers only what it concluded about the policy.

This preserves the §3 argument intact — we still hold no conversation content,
and the thing we accumulate is not sensitive.

### 13.2 What flows back

| Signal | Source | What it changes |
|---|---|---|
| **Override** | Reviewer says a block was wrong | Exception list entry, or threshold moves |
| **Confirmation** | Reviewer says a catch was right | Confidence weight for that pattern |
| **Ignored annotation** | User acted as if the flag were absent | Evidence the annotation was not useful |
| **Random-baseline sample** | §11.5 sampling | Precision estimate without labelling everything |

### 13.3 What we deliberately do not do

**We do not retrain a model on customer data.** That would rebuild exactly the
concentration risk §3 exists to avoid, and it would make our behaviour
non-reproducible for an auditor.

We tune **thresholds and exception lists** — inspectable, diffable, revertible
values in a policy artefact. A customer can read the diff and see why a
decision changed. "The model learned" is not an answer a regulator accepts.

### 13.4 Closing the loop

```
detection → review → override/confirm → aggregate → threshold or exception change
          → compiled into new policy artefact → pushed to checkpoints
          → measurable movement in FP rate (§14)
```

This is the incident→action loop §23 asks for. It is the difference between a
tool that reports and a tool that improves.

---

## 14. Metrics — proving this works to a sceptic

The brief's hardest ask, and the one most teams answer dishonestly.

### 14.1 The uncomfortable asymmetry

**False positives are directly measurable. False negatives are not.**

Every block and every flag can be shown to a reviewer, and disagreement gives a
true FP rate. But we cannot count what we never detected — the same knowledge
gap that causes the miss also hides it. Any team claiming a precise FN rate is
reporting a number they cannot have.

Three honest proxies instead:

1. **Seeded canaries — our primary FN instrument.** Inject known-sensitive
   values into a sample of synthetic traffic and measure catch rate. This gives
   a real, defensible FN estimate *on the seeded distribution*, and the caveat
   is stated rather than hidden. It is also directly demoable.
2. **Dual-detector disagreement.** Run a second, slower, more expensive
   detector over a small sample. Anything it catches that we missed is an FN
   estimate on live traffic.
3. **Downstream incident correlation.** Leaks found by other means, traced back
   to whether we saw the request. Slow, but the only ground truth that is real.

### 14.2 What we report

Per **profile**, never globally — a single FP number spanning `customer-chat`
and `code-assist` is an average of two unrelated things.

- Canary catch rate, with the seeded distribution stated
- FP rate per check type
- **Flags per 100 responses** — the alert-fatigue metric (§12.3)
- **Override rate** — how often humans disagree with us
- Added latency, p50 / p95 / p99
- Our token overhead as a share of protected spend (§15.5)

### 14.3 The posture that makes it credible

**Report override rate prominently.** A governance tool that hides how often it
is wrong is asking for the trust it claims to provide. Publishing the number we
look worst on is what makes the others believable.

> **Trustworthiness is not a score. It is a track record.** Show the trend, the
> method, and the confidence interval — not a single number on a dial.

And apply it to ourselves: the random baseline (§11.5) exists to measure our
own triage, not to catch more. *"We sample randomly to measure our detector's
precision"* is a stronger sentence than any accuracy claim.

---

## 15. Cost

### 15.1 Where the money goes (attribute before optimising)

1. **Wrong model for the job** — biggest lever, order-of-magnitude price
   gaps, usually chosen once and never revisited
2. **Repetition** — same question asked hundreds of times across the org
3. **Context bloat** — system prompts, full history, whole documents
   resent every turn; grows silently
4. **Agentic sprawl** — one request quietly becoming forty
5. **Retries** — failed parses, timeouts, refusals; paid twice

Most teams guess wrong about which dominates them. **The dashboard that
tells them is itself the product.**

### 15.2 Detecting an inefficient prompt

- **Cost-to-value mismatch** — 4,000-token prompt, 20-token answer
- **Repeated invariant context** — hash prompt prefixes, notice the same
  one recurring. **Highest-value cheap win in the product**: the fix is
  one config change (provider prompt caching) for a large discount
- **Model over-provisioning** — route a sample of flagship traffic to a
  cheaper model and compare. Where they agree, that traffic didn't need
  the expensive model. Measured, not guessed, with a rupee figure attached
- **Unbounded output** — no max token limit set
- **Loop signatures** — same tool called with same arguments twice; step
  count climbing without state changing

### 15.3 Semantic caching — "looking around the same thing"

Exact-match caching catches almost nothing. Embed the prompt, compare
against recent prompts, serve the stored answer if close enough.
Embedding is cheap relative to generation.

Three things decide brilliant vs dangerous:
- **Threshold is the whole game.** Too loose = wrong answer to a
  different question, far worse than a cost overrun. Start strict, loosen
  on measured agreement, never on intuition
- **Explicit exclusion policy** for time-sensitive, personalised, or
  context-dependent questions. No embedding distance will tell you
  "what's my leave balance" is unsafe to share
- **Cache within tenant boundaries, always.** Two employees can share;
  two customers absolutely cannot. Get this wrong and the cost feature
  becomes a data breach

Best on support / internal-knowledge assistants (small question set, high
volume). Near-zero on creative work — say so before a judge asks.

### 15.4 Reduction, in order of return

1. Route by difficulty — with **sampled agreement checking** so the
   routing accuracy is measurable, not reckless
2. Provider prompt caching — large discount, one config change
3. Semantic caching, with the caveats above
4. Trim resent context — summarise older turns, chunk documents
5. Cap and fail fast — output limits, agent step limits, route budgets

### 15.5 Account for our own overhead

We add cost to a system we claim reduces cost. Consistency sampling
multiplies token spend.

- Cap evaluation spend as a share of protected spend
- Adaptive sampling: 100% on flagged routes, low baseline elsewhere
- **Report gross saving, our overhead, and net.** More convincing than a
  bigger gross number, because a judge who suspects we're hiding it will
  ask.

Applying our own governance to ourselves is the kind of thing a panel
remembers.

---

## 16. System shape

**Data plane (the checkpoint)** — many instances, stateless, holds policy
as a compiled in-memory artefact, **makes zero network calls on the hot
path**. Deliberately dumb and fast.

**Control plane (the command centre)** — policy authoring, budget ledger,
dashboard, audit log. Rules are pushed to checkpoints in advance.

This split is what earns the product name and is the first thing an
infra-literate judge will probe.

---

## 17. Failure policy — per category, not global

| Component down | Behaviour |
|---|---|
| Credential / PII checker | **Fail closed** — block. A broken app beats a leak. |
| Hallucination / bias / toxicity | **Fail open** — deliver, marked `unverified` |

The customer's app never goes down because an optional check went down.
A judge will ask this; have it ready.

---

## 18. Audit log

Hash-chained: each entry carries a fingerprint of the previous one. Edit
any record and every hash after it breaks.

- ~40 lines of code
- **Demoable**: edit one row live, watch verification fail
- Store **hashes plus already-redacted text**, never raw sensitive data —
  otherwise the compliance tool becomes the largest concentration of
  leaked data in the company

---

## 19. Build vs explain

Every hour spent on something a judge sees for four seconds is an hour
not spent making the demo work.

### Build properly
- Commit-point buffer with **overlap window**
- Pattern + checksum scanner
- **Known-value matching** against a seeded fake customer database — the
  best demo moment: a *real customer's name* caught with a record reference
- Pre-flight gate: budget, injection, routing
- Cost ledger + attribution dashboard
- Prompt-prefix hashing to surface caching opportunities
- Hash-chained audit log
- **Entity-not-in-source** hallucination check — instant, striking
- One counterfactual bias probe

### Explain on slides
- Tokenise-and-restore round trip (build a narrow names-only version if
  time allows — it's the strongest compliance story)
- Entropy detection for unknown secret formats
- Claim-shape routing table for hallucination (**strongest intellectual
  content we have** — explaining *why sampling fails on citations and
  arithmetic* lands better than implementing it)
- Adaptive sampling rates
- LLM-based unbiased-mode rewriter
- Envoy `ext_proc` sidecar deployment; Rust/C++ hot path

### Do not build
- **C++ anything.** The check costs milliseconds in any language; the
  model call costs 1–2 seconds. Buys nothing measurable, costs two days.
  Python/FastAPI or Go.
- **Blur-and-reveal UI.** Not a security control — if the token reached
  the browser it's in the DOM. Worse than a kill switch because it
  *looks* safe. Proposing it to a security-literate judge loses the panel.
- Our own trained bias classifier
- Any claim of real-time bias detection

---

## 20. Demo script

The loop must close. Detection that produces a log line is a college
project; detection that produces an action someone takes on Monday is a
product.

1. **Normal request** — streams through, feels instant
2. **Credential leak** — model tries to emit a live key; two clean
   sentences release, then it stops. *The key is never sent — not deleted
   after, never transmitted.* This is the screen-recording answer,
   demonstrated
3. **Real customer data** — paste a real record, get a **correct, useful
   answer**, then show the audit log proving the model only ever saw a
   placeholder. **This is the whole pitch in fifteen seconds**
4. **Injection blocked** at `cost_usd: 0.0` — refused before dispatch
5. **Hallucination** — model cites a regulation that doesn't exist,
   caught while streaming
6. **Counterfactual** — same request, one name changed, two visibly
   different outputs
7. **Act, not just watch** — change a policy live, rerun, different result
8. **Tamper the audit log** — verification fails on stage
9. **The number** — their traffic, what it cost, what it would have cost

Step 9 is the most persuasive artefact in the pitch and needs no
explanation.

**Time budget — these nine steps do not fit.** The Grand Finale is a
**10-minute pitch plus 5-minute Q&A**. Nine demo steps, plus problem framing,
architecture and the closing number, is roughly 40 seconds each with no
recovery time if anything stalls.

Cut to a spine of four, each carrying a distinct claim:

| Keep | Claim it carries |
|---|---|
| 3. Real customer data | The provider never saw the real record — *the* differentiator |
| 2. Credential block | Irreversible harm stopped before release, not deleted after |
| 7. Live policy change | We act, not just watch — and the control plane is real |
| 9. The number | Measurable business impact, no explanation needed |

Steps 1, 4, 5, 6 and 8 become slides or Q&A material we can pull up if asked.
Every cut step is also build time saved — decide this *before* building, not on
stage. See D22 in [DRAWBACK.md](DRAWBACK.md).

---

## 21. Q&A preparation

**"How do you detect a name deterministically?"**
We don't. Two tiers — structured secrets are deterministic via checksums;
unstructured PII is probabilistic. Volunteering the split is what makes
us credible.

**"Why not just mask demographic terms?"**
That's fairness through unawareness. It fails — the model reconstructs
the attribute from postcode, school, phrasing. It makes bias invisible
without making it absent. We use the same machinery as a probe instead.

**"What if your evaluator is down?"** → Section 17.

**"Doesn't buffering slow it down?"** → Section 7, the reader-vs-model
comparison.

**"Doesn't your checking cost money?"** → Yes. Here's the net number.

**"Why not personalisation / memory?"**
*"Because the moment we store it, we're the thing we're protecting
against. Our value is that we hold nothing."*

---

## 22. Known limitations — state these before being asked

**Scope**
- We cover the first-party application path only — not browser sessions,
  personal-account shadow AI, or AI embedded in third-party SaaS (§4)
- Embeddings and fine-tune uploads leave through different endpoints than chat
  completions; a chat-only proxy never sees the largest bulk egress in a RAG
  rollout
- "One line" is literal for OpenAI-compatible endpoints, a config block for
  Bedrock and Azure OpenAI

**Detection**
- Regex + checksum detection needs a proper NER model in production
- Known-value matching is exact-match only; normalisation helps, doesn't solve
- Consistency checking misses consistently-held false beliefs — and fails
  systematically where the model fails systematically (invented citations, bad
  arithmetic, reversed relations reproduce identically every sample, §11.4)
- Bias detection is aggregate, not per-response — by nature, not by choice

**Operational**
- Audit log is in-memory; production needs append-only storage with the
  chain anchored externally
- Semantic caching has near-zero hit rate on creative work, and the similarity
  threshold is the whole game — too loose is a correctness failure, not a cost
  one
- Buffering only pays for itself on interactive profiles (§7)
- No multi-turn conversation state yet

The fuller, internally honest version — including trade-offs we accepted
deliberately and pitch risks we are managing — lives in [DRAWBACK.md](DRAWBACK.md).

---

## 23. The strategic reminder

Accenture scores **enterprise applicability and measurable business
impact**. A perfect gateway with no buyer narrative places mid-table.

Three shallow pillars read as a wrapper around three API calls. **Build
one dimension with real depth, stub the other two convincingly, and
spend the saved time on the incident→action loop and the dashboard.**

**Refined by the Round 2 brief:** it asks us to *"design a more complete
solution and build a working prototype that demonstrates its core mechanism,
even on a limited or simulated scope."* So the split is not depth-versus-breadth
— it is **complete in the design, narrow in the build**. §24 is the checklist
for the first half; §19 governs the second.

---

## 24. Round 2 brief — coverage map and stated assumptions

### 24.1 The six solutioning areas

| Area | Where we cover it | Strength |
|---|---|---|
| **Detection techniques** | §9 (pattern + checksum, known-value matching), §10.3 (counterfactual), §11 (cascade, claim-shape routing) | **Strong** — our deepest content |
| **Decision logic** | §12 — four tiers, escalation triggers, flag budget | **Now covered** (was our largest hole) |
| **Architecture** | §6 reversibility split, §7 commit-point buffer, §16 data/control plane | **Strong** |
| **Governance** | §5.2 route profiles, §9.7 inherited classification, §18 hash-chained audit | **Strong** |
| **Feedback loops** | §13 — control plane learns, data plane stays stateless | **Now covered** (was absent) |
| **Metrics & monitoring** | §14 — FP measurable, FN via seeded canaries, override rate reported | **Now covered** (was weak) |

### 24.2 Complexities the brief raises, and where we answer them

| Complexity | Our answer |
|---|---|
| One-size-fits-all checking fails across use cases | §5.2 route profiles; §7 buffering is a profile property |
| Bias / hallucination / privacy overlap | §6.1 — we classify the *harm*, not the risk, so overlap is a non-issue |
| No reliable real-time ground truth | §11.3 — check *stability*, not truth; §11.2 for the grounded case |
| Over-flagging causes alert fatigue | §12.3 — cascade, per-profile flag budget, no flag without actionable evidence |
| Multi-turn and agentic compounding risk | Partly. §5.1 family G, §11.5 automated-action override. **Genuine gap — see D4** |
| Regulation varies and evolves | §5.2 profiles carry geography; §9.7 inherits their classification rather than hard-coding rules |
| API-only access, no model internals | §4 — we are an input/output-layer product by design, not by limitation |

### 24.3 Assumptions we are stating explicitly

The brief invites us to make our own and state them clearly:

- **Volume:** ~30,000 interactions/week across three use cases — roughly 3/minute
  average, assumed peaking at 10×. This is comfortably within a single Python
  process, so our latency claims do not depend on unproven scale engineering.
- **Mix:** ~60% internal assistant, ~30% customer support, ~10% decision
  support. Decision support is lowest volume and highest scrutiny — which is
  why 100% sampling there is affordable (§12.2).
- **Data sources:** a mix of well-governed (CRM, HR — populate the known-value
  store) and loosely governed (shared drives, wikis — do not). The regulatory
  baseline and pattern tier are the floor that covers the ungoverned half
  (§9.7, D28).
- **Model access:** third-party API only. No logprobs assumed, so the token
  confidence signal in §11.5 is treated as optional enrichment, not a
  dependency.
- **Simulated scope:** seeded synthetic CRM and traffic. Every number in the
  demo is reproducible from the repo rather than quoted from a vendor report.
