# DEMO SCRIPT — the Round 2 video

**Target: 7 minutes.** Cut marks are noted if you need 5.
Nine beats, because that is what D22 says fits.

**How to use this.** Each beat has four blocks:

- **SCREEN** — where you are
- **DO** — the clicks, in order
- **SAY** — the narration, in plain language. Read it, don't perform it.
- **PROOF** — the thing on screen the words are pointing at. If a viewer
  pauses the video here, this is what they check.

The narration is written to be *said*, so it uses short sentences and no
jargon that has not already been introduced. Where a term has to appear
(placeholder, profile, canary) it is defined the first time in the same
sentence.

---

## Before you hit record

```bash
# 1. the local model
ollama serve            # in its own window
ollama pull llama3.2:1b # once

# 2. a clean demo server  — restarting it resets ALL state
python -m controlplane.demo.server

# 3. the dashboard
cd dashboard && npm run dev
```

Then, in a **third** terminal, warm the review queue so beat 7 has something
in it. This runs three real requests on the high-risk route:

```bash
python scripts/warm_demo.py
```

**Check before recording:**

- [ ] `http://127.0.0.1:8000/demo/health` says `"ok": true`
- [ ] The dot next to `llama3.2:1b` at the top right of the dashboard is green
- [ ] `/queue` shows **3 pending items**
- [ ] `/verify` shows a chain that verifies (you have not tampered yet)
- [ ] Browser at 1600×1000 or wider, zoom 100%, dark room, no notifications
- [ ] The tab bar and bookmarks are hidden (F11 full screen is fine)

**If a take goes wrong:** restart the demo server, re-run `warm_demo.py`,
reload the page. Everything resets.

---

## Beat 0 — The problem · 0:00–0:40 · *40s*

**SCREEN:** the dashboard's front page, before you click anything.

**SAY:**

> Every large company now wants to use AI models. And almost every large
> company has the same blocker: the legal and security teams will not let real
> customer data go to an outside model provider.
>
> So teams either don't use AI on their real work, or they use it and hope
> nobody notices.
>
> ControlPlane sits in the middle. Your application changes one line — the
> address it sends requests to. Everything else stays the same. And from then
> on, every request and every response passes through a checkpoint you control.
>
> I'm going to show you one request going through it, and then eight things
> the checkpoint can do that a wrapper around an API call cannot.
>
> Our assumptions, stated up front: an enterprise running three AI use cases at
> once, roughly thirty thousand interactions a week between them, and internal
> data that is well governed in some places and not in others. All three of
> those show up in the demo.

**PROOF:** the header — the model name, the policy version, and the
fingerprint. Nothing is a mock-up.

> *Cut to 5 min: keep this beat. It is the only one that explains why anyone
> should care.*

---

## Beat 1 — The round trip · 0:40–2:00 · *80s*

**SCREEN:** Transit (the home page).

**DO:**
1. Click the preset **The round trip**
2. Click **Send request**
3. Let it stream. Don't talk over the whole stream — pause and let it run.

**SAY:**

> Here is a real customer record, pasted by an employee. A name, a balance, an
> email address.
>
> Watch the middle of the screen. That hatched line is the boundary of the
> building. Everything on the left is inside. Everything on the right is what
> the outside model provider actually receives.
>
> On the left, in warm colour, the name and the email are real. On the right,
> in cold colour, they have become `CUST_A` and `EMAIL_A`. Those are
> placeholders — labels that stand in for the real values.
>
> Now look at the number, forty-five thousand two hundred and thirty. It
> crossed the line unchanged.
>
> That is deliberate, and it is the difference between this and blacking things
> out. The sensitive part is not the number. The sensitive part is the *link*
> between the number and the person. Break the link and the number is
> meaningless — so the model can still do arithmetic with it and still write a
> useful answer.
>
> The model writes its reply using the placeholders. Bottom right, you can see
> it addressing `CUST_A`. It never knew who that was.
>
> And on the way back, we put the real name in. Bottom left is what the
> employee reads. Complete, correct, and the provider never saw a single real
> value.

**PROOF:**
- The green **leak check** chip: `0 of 2 real values present`. That is a
  server-side assertion, run on every request, that no real value appears in
  the text we dispatched.
- Bottom left: `✓ 2 values restored · 0 unrestored`.
- The finding rows under the prompt: `customer_name — matched customer:44219`.
  Say this line out loud, it matters:

> Notice what the audit line says. Not "matched a pattern that looks like a
> name". It says *matched customer record 44219*. We are not guessing whether
> something looks sensitive. We are checking it against the company's own
> records. That is the difference.

**COVERS:** Detection techniques · Architecture (where the checker sits) ·
the API-only constraint — we work at the input/output layer, which is all you
get with a third-party model.

---

## Beat 2 — What happens after the answer · 2:00–2:40 · *40s*

**SCREEN:** same page, scroll down to the three panels under the boundary.

**DO:** scroll so **Decision** and **After delivery** are both visible.

**SAY:**

> Two things down here.
>
> On the left, the decision. It says *allow*, and next to each finding it says
> *mitigated by substitution*. The gateway found the customer's name and it let
> the request through — because swapping the name out already fixed the
> problem. There was nothing left to block.
>
> On the right is the part I want you to notice. These checks ran **after** the
> answer was delivered. Look at the timestamp — it says how many milliseconds
> after the reader already had their answer.
>
> That is not laziness. Most systems split their checks by how fast they are.
> We split them by whether the damage can be undone.
>
> A leaked password or a customer's name, once it appears on a screen, cannot
> be taken back. Someone can photograph it. So those are checked *before*
> anything is released.
>
> A wrong fact or a badly-worded sentence can be corrected. Nobody is harmed by
> seeing it for two seconds. So those are checked afterwards, where they cost
> the user no waiting time at all.
>
> That one decision removes the usual argument between safety and speed.

**PROOF:** the `arrived Nms after the reader had the answer` line, and the
confidence number shown next to the formula that produced it.

**COVERS:** Decision logic · Architecture (checks running off the hot path) ·
the overlap between hallucination and privacy — say this if the finding fires
on an invented name:

> And here is a case that does not fit in a box. If the model invents a detail
> about a person, that is a made-up fact *and* a privacy problem at the same
> time. Our customer database cannot catch it, because an invented person is
> not in the database. It surfaces here instead, because the detail has no
> source.

---

## Beat 3 — The credential · 2:40–3:15 · *35s*

**SCREEN:** Transit.

**DO:**
1. Click the preset **The credential**
2. Click **Send request**

**SAY:**

> Same screen, different input. This time someone has pasted a live production
> key.
>
> A password cannot be swapped for a placeholder. There is no safe version of
> it to send. So this one stops.
>
> Look at the boundary — it has gone red, and it says *stopped here*. The right
> side is empty. Nothing was sent.
>
> And look at the cost. Zero.
>
> That number is the whole argument for the order these steps happen in. You
> are charged by the model provider the moment it starts generating. So if you
> send the request first and cancel when you spot the problem, you have blocked
> the request *and* paid for it. Check first, send second. Otherwise your safety
> feature quietly makes your costs worse.

**PROOF:** the empty right column, the red boundary, `$0.00`, and the note
explaining the ordering.

**COVERS:** Decision logic (tiered response — this is the *block* tier) ·
Architecture (a pre-response gate, not a post-hoc audit).

---

## Beat 4 — Ours or just similar? · 3:15–3:50 · *35s*

**SCREEN:** Transit.

**DO:**
1. Click the preset **The landmine**
2. Click **Send request**

**SAY:**

> Two card numbers in one message. Both are valid card numbers — both pass the
> checksum that every payment system uses.
>
> A pattern-matching tool flags both. It has no way to tell them apart.
>
> We flag one. The second number belongs to a customer in the company's
> records. The first belongs to nobody — it is a well-known test number that
> appears in documentation all over the internet.
>
> This is the difference between asking "does this look sensitive?" and asking
> "is this **ours**?"
>
> It matters for a boring reason. If your checker flags every twelve-digit
> number, people stop reading the warnings within a week. Then you have a
> safety control that everybody ignores, which is worse than not having one —
> because now everyone believes it is working.

**PROOF:** one finding row, not two. The one that fired carries a record
reference; nothing fired on the test number.

**COVERS:** Detection techniques · the over-flagging / alert-fatigue trade-off.

---

## Beat 5 — Where the data is messy · 3:50–4:20 · *30s*

**SCREEN:** Transit.

**DO:**
1. Click the preset **The edge of governance**
2. Click **Send request**

**SAY:**

> Real companies do not have one tidy database. Some of their data is well
> organised and some of it is a spreadsheet somebody made in 2019.
>
> So we built that into the demo. Thirty per cent of our test records are
> deliberately marked as coming from a badly governed source.
>
> Watch what happens. The card number is still caught, because the checksum
> works regardless. But the name stays — it is not in the proper records, so we
> have nothing to match it against.
>
> And look at the finding: there is no record reference. The audit trail for
> this one is weaker, and we say so.
>
> I'm showing you this on purpose. The honest claim is not "we catch
> everything". It is: where your data is well organised we are precise, and
> where it isn't, coverage drops off gradually instead of falling to zero. You
> can see exactly where you are on that scale.

**PROOF:** name not substituted, card substituted, finding row says
`pattern tier — no record reference`.

**COVERS:** the mixed-governance reference parameter · Metrics (being honest
about coverage).

> *Cut to 5 min: this beat can go. Mention it in one sentence during beat 4
> instead.*

---

## Beat 6 — One size does not fit all · 4:20–5:05 · *45s*

**SCREEN:** click **PROFILES** in the top navigation.

**DO:**
1. Point at the three cards
2. Click **Tighten by 0.15** on `customer-support`
3. Let the diff table appear
4. Scroll down, click **Try to exempt API keys**

**SAY:**

> A customer-facing chatbot and an internal assistant are not the same problem.
> One is talking to the public; a mistake there becomes a promise the company
> has to honour. The other is talking to staff who already have access to the
> data.
>
> So the settings are per use case, not global. Here are our three. Look at the
> numbers — the customer-facing one blocks earlier than the internal one, on
> exactly the same evidence.
>
> Each one has a fingerprint, that short code. Two servers showing the same
> fingerprint are provably running the same rules. That is the question an
> auditor actually asks.
>
> Let me change one. *(click)* Threshold changed, fingerprint changed, and here
> is the difference in plain text. No restart. The next request uses the new
> rules immediately.
>
> That readable difference matters more than it looks. Rules change — data
> protection law, AI regulation, whichever industry you're in. When a decision
> changes, somebody has to be able to say why. "The system learned" is not an
> answer a regulator accepts. A line saying exactly what changed, and when, is.
>
> And some things are not adjustable at all. *(click "Try to exempt API keys")*
> That is me trying to turn off password blocking. It refuses, and it tells me
> why. There is no legitimate reason to send a password to a model, so it isn't
> offered as a setting somebody can switch off at five o'clock on a Friday.

**PROOF:** the fingerprint before/after, the diff table, the compiler's refusal
message in its own words.

**COVERS:** Governance (configurable policy layer) · varying by use case,
geography and risk appetite · regulation that changes over time.

---

## Beat 7 — When a person is worth interrupting · 5:05–5:45 · *40s*

**SCREEN:** click **REVIEW**.

**DO:**
1. Click **False positive** on the first item
2. Click **False positive** on the second — point out that nothing is proposed
3. Click **False positive** on the third — the proposal appears
4. Click **Recompile and publish**

**SAY:**

> Not every flag needs a human. The ones that do are the ones in the middle —
> where the system is genuinely unsure. At the extremes, automation is
> reliable; the middle is where it isn't.
>
> These three came from the decision-support route, which reviews every
> response — not because we're unsure, but because decisions about people carry
> legal weight.
>
> Notice what's in the queue: a category, a confidence, a reference. No prompt,
> no response, no customer name. If somebody stole this queue they would get
> nothing.
>
> I'm the reviewer, and I think all three of these were wrong to flag. *(click,
> click)* — and notice, after two, it proposes nothing. It wants three
> independent reviews before it will act. One irritated reviewer should not be
> able to widen a hole in the detector.
>
> *(third click)* — now it proposes a change, and it shows the evidence behind
> it: three out of three overturned.
>
> I'll apply it. *(click)* Nothing here retrained a model. What changed is a
> written-down exception, and the change itself is now on the audit trail. The
> system improves, and every improvement is something you can read.

**PROOF:** the proposal's rationale line, and the published diff.

**COVERS:** Feedback loops · Decision logic (when a human is pulled in) ·
Governance.

---

## Beat 8 — Can you trust the log? · 5:45–6:15 · *30s*

**SCREEN:** click **CHAIN**.

**DO:**
1. Click **Verify the chain** — it passes
2. Click **Tamper with entry #0**
3. Let the red state appear

**SAY:**

> Every decision is written down. Each entry is sealed with a code calculated
> from its own contents plus the entry before it — so they form a chain.
>
> Let me check it. *(click)* Intact.
>
> Now let me be the attacker. *(click)* I have just edited a record that was
> already written, and left its seal alone.
>
> And it is caught immediately. It names the exact entry, and it tells you that
> everything after that point can no longer be proven.
>
> I want to be precise about the claim. This is tamper-**evident**, not
> tamper-proof. Somebody with access to this machine can still add entries.
> What they cannot do is quietly rewrite history. That is a real difference and
> we would rather show you the limit than let you assume there isn't one.

**PROOF:** the verification passing, then naming `broken at entry #0`.

**COVERS:** Governance (a clear audit trail behind every decision).

---

## Beat 9 — The numbers, and what they can't tell you · 6:15–6:55 · *40s*

**SCREEN:** click **MEASURES**.

**DO:**
1. Click **Run a sweep now** — wait for it
2. Point at the cost panel
3. Point at the bias panel (run it beforehand if you want the table filled —
   it takes about ten seconds)

**SAY:**

> Last thing, and it's the part most demos skip.
>
> Anyone can tell you how often they flagged something. Nobody can tell you how
> often they *missed* something — because if you knew, you wouldn't have missed
> it.
>
> So we plant fake secrets in the traffic and count how many come back.
> *(click)* Eighty planted, eighty caught. But look at what sits next to that
> number: a confidence range, and a warning that this only describes the kinds
> of secret we thought to plant. The warning is built into the code. You cannot
> quote the number without it.
>
> Underneath: cost. Not just the saving — the saving, our own running cost, and
> the difference. A saving figure that hides what it cost to achieve is not a
> saving figure.
>
> And bias. We do not give you a bias score for a single answer, and we never
> will — because there isn't one. A model that favours one group seventy per
> cent of the time produces no individual answer you can point at. Every one
> looks reasonable on its own.
>
> What you can do is run the same request twice, changing only the name, and
> count the outcomes across many runs. That's what this is. It's a method, not
> a verdict — and the panel says so.
>
> Anyone showing you a per-response bias score is doing something else and
> calling it bias detection.

**PROOF:** the confidence interval and its caveat; gross / overhead / net side
by side; the `NOT BUILT` panel listing what we deliberately did not build and
why.

**COVERS:** Metrics & monitoring (false positive / negative rates, reported to
a sceptical stakeholder) · the no-ground-truth problem · bias as a
distribution.

---

## Beat 10 — Close · 6:55–7:15 · *20s*

**SCREEN:** back to Transit, the round-trip result still on screen.

**SAY:**

> Everything you just saw was computed while you watched it. Nothing on that
> screen is a mock-up, and the repository is public, so you can run it
> yourself.
>
> One line changes in the application. After that, real company data can go to
> an outside model — and the sensitive parts never leave the building.

---

## Coverage map — for the submission form

Every item the brief lists, and where it appears.

### Solutioning areas

| Area | Beat | What we show |
|---|---|---|
| **Detection techniques** | 1, 4, 5 | Known-value matching against the company's own records; a pattern + checksum tier underneath (Luhn, Verhoeff, mod-97) as the floor; entity-provenance checking for made-up facts. No AI-as-judge on the fast path — it would be non-deterministic where we need determinism |
| **Decision logic** | 2, 3, 7 | Four tiers: allow, annotate, review, block. Confidence × severity × profile. Humans pulled in on the middle of the confidence range, and on routes where the law requires it |
| **Architecture** | 1, 2, 3 | Pre-response gate on the irreversible checks; post-hoc on the reversible ones. Zero network calls on the decision path — policy is compiled ahead of time and read from memory |
| **Governance** | 6, 8 | Per-use-case policy profiles with content fingerprints, hot-swappable, with a readable diff; a hash-chained audit trail |
| **Feedback loops** | 7 | Reviewer verdicts aggregate into proposed policy changes with the evidence attached. Thresholds and exception lists, never model weights |
| **Metrics & monitoring** | 9 | False positives measured, false negatives estimated with planted canaries and a confidence interval; cost as gross / overhead / net; an explicit "not measured" list |

### Real-world complexities

| Complexity | Beat | How we handle it |
|---|---|---|
| Different use cases, different risk and latency | 6 | The use case *is* the policy unit. Three profiles, different thresholds, different buffering |
| Bias / hallucination / privacy overlap | 2 | We don't categorise by risk name. We split by whether the harm can be undone, which is the axis that actually decides what to do |
| No real-time ground truth | 9 | We never claim a fact is false. We say it has no source, and hand the reader the exact thing to check |
| Over-flagging vs under-flagging | 4, 7 | A per-profile flag budget, and no flag without something actionable to show. Tuned, and we say it is tuned |
| Multi-turn and agents compound risk | — | Stated as out of scope, with the architectural answer given in prose. Say it in Q&A rather than claiming it |
| Regulation differs by geography and industry | 6 | Policy is data, not code — compiled, versioned, diffable. Geography is a field on the profile |
| API-only access to the model | 1 | We work entirely at the input/output layer, which is the only layer available. That constraint shaped the whole design |

### Reference parameters

| Parameter | Where |
|---|---|
| Multiple use cases at once | Three named profiles, shown in beat 6 |
| Tens of thousands of interactions per week | ~30,000/week assumption stated in beat 0; traffic mix 60/30/10 in the seed data |
| Mixed governance of internal data | 70/30 governed/ungoverned in the seed data, demonstrated in beat 5 |

---

## If you only have five minutes

Drop beat 5 (fold one sentence of it into beat 4) and shorten beat 6 to the
three profile cards plus the refusal. Keep everything else. That lands at
about 5:10.

**Never cut:** beat 1 and beat 3. Beat 1 is the product. Beat 3 is the
argument that the product is built in the right order.
