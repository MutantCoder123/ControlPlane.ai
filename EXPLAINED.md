# ControlPlane, explained in plain language

**Who this is for:** anyone who wants to understand what this project actually
does, how each part works, what is genuinely finished, and what still needs
work — without already knowing the codebase or the jargon.

Every claim here was checked against the code on **2026-09-02**, not copied
from an older document. Where something is only *declared* and not actually
*doing* anything, this file says so — that is the most useful part of it.

| File | What it gives you |
|---|---|
| **EXPLAINED.md** (this one) | How it works, in plain words, plus an honest audit |
| [README.md](README.md) | The short public pitch and setup commands |
| [CONTEXT.md](CONTEXT.md) | A one-page state summary for a fresh session |
| [IDEATION.md](IDEATION.md) | *Why* every design decision was made |
| [DRAWBACK.md](DRAWBACK.md) | Every known weakness, numbered D1-D33 |
| [DEMO-SCRIPT.md](DEMO-SCRIPT.md) | The word-for-word video script |

---

## 1. What is this, in one paragraph

Companies want to use AI models on their real work. Their legal and security
teams say no, because sending real customer data to an outside company is a
risk nobody will sign off on. **ControlPlane is a checkpoint you put in the
middle.** The app sends its request to ControlPlane instead of to the AI
provider. ControlPlane swaps every real name, email and account number for a
fake label, sends the labelled version onward, gets the answer back, and puts
the real names back before the employee reads it.

The provider never sees a single real customer detail. The employee still gets
a complete, useful answer. Nobody has to choose between "safe" and "useful".

The only change the app makes is one line: the address it sends requests to.

---

## 2. The mental model (read this and you understand 80%)

Picture a line down the middle of a room.

```
        INSIDE THE BUILDING          |        OUTSIDE (the AI provider)
                                     |
  1. Employee types:                 |
     "Refund Priya Sharma,           |
      balance 45230"                 |
                |                    |
                v                    |
  2. ControlPlane finds the real     |
     values and swaps them           |
                |                    |
                v                    |
  3. "Refund [[CUST_A]],   ----------+-------->  4. The model reads this.
      balance 45230"                 |              It has NO IDEA who
                                     |              [[CUST_A]] is.
                                     |                     |
                                     |                     v
  6. Real name put back  <-----------+-----------  5. "Dear [[CUST_A]], your
     "Dear Priya Sharma, your        |                 refund of 45230 is
      refund of 45230..."            |                 approved."
                |                    |
                v                    |
  7. Employee reads a normal,        |
     complete answer                 |
```

Three things to notice, because they are the whole product:

1. **The number 45230 crossed the line unchanged.** That is deliberate. A
   number alone means nothing. "Priya's balance is 45230" is sensitive
   *because of the name*. Remove the name and the number is harmless — and the
   model can still do maths with it. **Break the link, keep the arithmetic.**
2. **This is substitution, not deletion.** Blacking things out gives a worse
   answer. Swapping gives the same answer.
3. **Nothing sensitive ever crosses.** Not "we delete it afterwards" — it was
   never sent. That is a far stronger thing to say to a compliance officer.

---

## 3. The five rules everything follows from

| # | Rule | Why it matters |
|---|---|---|
| 1 | **Remember nothing** | No conversation database. Nothing to leak, nothing to subpoena. "We keep nothing, and you can check" is what gets a product like this approved. |
| 2 | **Split by "can this be undone?" — not by "is this slow?"** | A leaked password on screen cannot be un-seen (someone can photograph it) so check it *before* sending. A wrong fact can be corrected, so check it *after*, and the user never waits. This dissolves the usual safety-vs-speed argument. |
| 3 | **Swap, don't delete** | The answer stays complete and correct. |
| 4 | **Swap the name, never the number** | Sensitivity lives in the linkage, not the value. |
| 5 | **Ask "is this OUR secret?", not "does this look like a secret?"** | A regex flags every 16-digit number on earth. We check against the company's own records, so the audit line reads `matched customer record 44219` instead of `matched a pattern`. That is the difference between evidence and a guess. |

---

## 4. One request, step by step

What actually happens when someone clicks **Send**. Each step names the file
that does the work, so you can go and read it.

**Step 1 — Open the request.** `demo/orchestrator.py` gives it an ID
(`req_a1b2c3...`) and looks up which *profile* applies: customer-support,
internal-knowledge, or decision-support. Every rule for the rest of the
journey comes from that profile.

**Step 2 — Scan what was typed.** `engine/substitute.py` looks for sensitive
values using two methods at once:
- **Known-value matching** — is this exact value in the company's own records?
  A fast lookup. Finds "Priya Sharma" because Priya Sharma is customer 44219.
- **Pattern + checksum** — does this look like a card / Aadhaar / IBAN *and*
  pass that format's own maths test? A safety net for anything not in records.

Anything found is swapped for a label: `[[CUST_A]]`, `[[ACCT_A]]`. The same
person gets the same label everywhere in one request, or the model would think
two different people were involved.

**Step 3 — Decide what to do.** `decision/tiers.py` grades each finding by
**how bad x how sure x which profile**:

| Outcome | When | What the user sees |
|---|---|---|
| **allow** | Nothing wrong, or already fixed by swapping | Nothing |
| **annotate** | Reversible problem, with real evidence | The answer, plus a marked warning |
| **review** | Genuinely uncertain, or a high-stakes route | The answer, and a human gets it queued |
| **block** | Irreversible harm, high confidence (a live password) | A refusal, with a reason |

The same finding gets different outcomes on different profiles. That is the
entire point of having profiles.

**Step 4 — Write it down.** `audit/chain.py` records what was found — storing
*references* (`customer:44219`) and fingerprints, never actual values. Each
entry is sealed with a code computed from its own contents *plus the previous
entry's code*. Change any old entry and every code after it stops matching.

**Step 5 — Count the session.** `feedback/session.py` bumps counters: how many
turns, how many *different* customer records touched, how many agent steps.
Counters only, no text. If someone quietly pulls up 20 different customers
across 20 innocent-looking questions, the counter notices even though no
single question looked wrong.

**Step 6 — Refuse here if you must.** If the decision was **block**, the
request stops *now*, before anything is sent, and the cost is `$0.00`.
This ordering is the whole money argument: **you are billed the moment the
model starts generating.** Send first and cancel later and you have blocked
the request *and* paid for it. Check first, send second.

**Step 7 — Send the labelled version.** A leak check runs first: does the
outgoing text contain any real value from the mapping? It should be zero, and
the dashboard shows the result on every request.

**Step 8 — Catch the answer carefully.** `stream/buffer.py` does not pass words
straight to the screen. It holds them and releases in safe pieces, committing
when a sentence ends, or ~40 tokens arrive, or 250ms pass — whichever first.

Why hold anything? A password can be **split across two chunks**: `sk-abc`
arrives, then `def123`. Scan each alone and you see nothing; the leak lands on
screen in two halves. So the buffer keeps a 50-character overlap and scans the
*seam* as one piece. Once a token reaches the browser it is in the page and in
any screen recording — a kill switch after that point is theatre.

**Step 9 — Put the real names back.** Every `[[CUST_A]]` becomes
`Priya Sharma` again. An alarm checks the delivered text for any label that
failed to convert, because that is the one bug that would fail live on stage.

**Step 10 — Work out the cost.** `cost/ledger.py` records what this cost, what
it *would* have cost on a premium model, and ControlPlane's own overhead. It
always reports all three: a saving figure that hides its own cost is not a
saving figure.

**Step 11 — The checks that can wait.** Only *after* the reader has the answer
does `quality/checks.py` run: hallucination, toxicity, overclaiming, invented
reasons. All are correctable after the fact, so making the user wait would be
pure cost with no safety gain. The dashboard even prints the timestamp:
*"arrived 1670ms after the reader had the answer."*

**Step 12 — Done.** Every step above emitted an event. The dashboard is only a
renderer for that event stream; it never recalculates anything itself.

---

## 5. Every feature, one at a time

Each entry answers the same four questions: **what problem**, **how it works**,
**where the code is**, and **what it honestly cannot do**.

### 5.1 Substitution engine — the core

**Problem.** Real customer data must not reach the provider, but the answer
must still be useful.

**How it works.** Two detection tiers run together:

| Tier | Question it asks | Strength | Weakness |
|---|---|---|---|
| Known-value | "Is this exact value in our records?" | Certain. Gives a record reference for the audit line. | Exact match only — a typo or nickname is missed |
| Pattern + checksum | "Does this look like a card/Aadhaar/IBAN *and* pass its maths test?" | Catches things not in records | Cannot tell *whose* it is; no record reference |

The checksum step matters: `4111 1111 1111 1111` is a famous test card number
that passes the Luhn check but belongs to nobody. The engine knows test values
and does not flag them. A regex-only tool flags both and trains people to
ignore warnings.

Each value found gets a label. `RequestScope` keeps labels consistent across a
multi-part request — without it, two customers in one request would both become
`[[CUST_A]]` and the answer would name the wrong person.

**Code.** `engine/substitute.py` (assembly), `engine/knownvalue.py` (the record
lookup, with a Bloom filter to make it fast), `engine/patterns.py` (Luhn,
Verhoeff, mod-97), `engine/placeholders.py` (label format and restoration).
160 tests.

**Cannot do.** Free-text names not in records (no NER model — D9/D10). If the
identifier *is* the thing you need computed on ("validate this account
number's checksum"), substitution breaks it; the engine flags it and a human
decides (D16).

### 5.2 Route profiles — the policy layer

**Problem.** A public chatbot and an internal assistant are not the same risk.
One global setting is wrong for both.

**How it works.** Three profiles ship: `customer-support` (public-facing,
blocks earliest at 0.75), `decision-support` (decisions about people, reviews
*everything*, EU AI Act high-risk), `internal-knowledge` (staff who already
have data access, blocks latest at 0.90).

Each profile is compiled into a frozen artefact with a **fingerprint** — a
short code from its contents. Two servers showing the same fingerprint are
provably running identical rules. That is the question an auditor actually
asks. Change a value and the fingerprint changes; the diff is printed and
written to the audit chain. No restart.

Some things cannot be switched off at all: the compiler **refuses** to build a
profile that exempts credentials. There is no legitimate reason to send a
password to a model, so it is not offered as a setting somebody can disable on
a Friday afternoon.

**Code.** `policy/profile.py`, `policy/store.py`, `policy/profiles/*.json`.
33 tests (plus 11 more for the jurisdiction floors below).

### 5.3 Jurisdiction floors — geography

**Problem.** Rules differ by country and change over time.

**How it works.** A middle layer: `_base.json` -> jurisdiction floor ->
profile. A jurisdiction can only make a profile **stricter**, never looser.
The direction is fixed per field in a table (minimum for `block_at`, maximum
for flag budgets, logical-OR for on/off switches). Getting this backwards is
how a governance product would let a team quietly opt out of the law by editing
their own config, so it is enforced by the compiler, not by convention.

Three example floors ship (`eu`, `in`, `us`), each carrying its own disclaimer:
*a mechanism for expressing jurisdiction policy, not an implementation of any
statute, and not legal advice.* Selecting **EU** visibly tightens several
profiles. Selecting **US** changes nothing at all — every fingerprint stays
identical, which is the honest way to show a permissive floor rather than
assert one. Trying to loosen a profile past its floor compiles fine and does
**nothing** — same fingerprint before and after.

**Code.** `policy/profile.py` (`_clamp_to_floor`), `policy/jurisdictions/*.json`.

### 5.4 Decision tiers — what to actually do

**Problem.** Allow-or-block forces every uncertain finding into one of two
wrong answers.

**How it works.** Four tiers (allow / annotate / review / block) from
**severity x confidence x profile**. Key rules, each of which exists because
the obvious alternative is worse:

- **Substitution counts as mitigation.** A name that was already swapped still
  appears in the audit trail and metrics — but it no longer drives the
  decision, because there is nothing left to prevent.
- **Mid-band confidence escalates only *irreversible* harm.** Sending every
  uncertain hallucination to a person is how a review queue becomes noise.
- **A flag budget** caps user-visible flags per 100 requests, so a noisy period
  does not train people to ignore warnings. It can *never* suppress a block.
- **No flag without evidence.** "Possible issue" *is* alert fatigue.

**Code.** `decision/tiers.py`. 26 tests.

### 5.5 Commit-point buffer — safe streaming

**Problem.** Streaming text word-by-word means a secret split across two chunks
is invisible to a scanner looking at each chunk alone.

**How it works.** Hold, scan the seam, release. Commit on sentence end / ~40
tokens / 250ms. Keep a 50-character overlap so the join is always scanned as
one piece. If the scan fails, nothing is released at all.

There is a second, subtler seam this file also guards: the fixed-size overlap
can cut a *placeholder* in half (`[[CUST` released, `_A]]` held), and neither
half would restore — putting literal broken brackets on screen. A separate
guard holds back any dangling `[[...` opening regardless of the overlap size.
That bug was found by looking at the screen, not by a test, and the alarm that
should have caught it was itself checking the wrong copy of the text.

**Code.** `stream/buffer.py`. 28 tests.

### 5.6 Audit chain — proof you can check

**Problem.** "Trust our logs" is not an answer to an auditor.

**How it works.** Every entry is hashed together with the previous entry's
hash. Verification walks the chain and reports the exact sequence number where
it breaks. The dashboard lets you tamper with an entry live and watch
verification catch it and name the entry.

**Honest limit, stated on stage:** this is tamper-**evident**, not
tamper-proof. Someone with access to the machine can still append entries.
What they cannot do is quietly rewrite history. It is also **in memory only**
— restart the server and the chain is gone (D14).

**Code.** `audit/chain.py`. 20 tests.

### 5.7 Session risk — many small requests adding up

**Problem.** No single question looks wrong, but forty questions about forty
different customers is a pattern.

**How it works.** Per-session counters: turns, distinct records touched, agent
steps, blocks. Budgets come from the profile (`internal-knowledge` caps at 3
records for the demo). Tripping the budget **flags, it does not block** — a
cumulative pattern is evidence about a session, not proof about the request in
front of you, and cutting off turn seven of a legitimate investigation is the
over-flagging failure this project is otherwise careful to avoid.

The panel shows only numbers, with the caption *"counters only — no prompt, no
response, no value"* permanently beside them. That is how compounding risk gets
caught without keeping the conversation that would make it easy.

**Code.** `feedback/session.py`, wired in `demo/orchestrator.py`. 11 tests.

### 5.8 Hallucination detection — three shapes, real confidence

**Problem.** Models state things that are not in any source, confidently.

**How it works.** Three different checks, because hallucination has more than
one shape:

| Shape | Check | Example it catches |
|---|---|---|
| Invented fact | `entity_not_in_source` | "Your refund of **98765**" when no source says 98765 |
| Overclaiming | `find_absolute_claims` | "This **always** works", "**guaranteed**" |
| Invented reason | `find_unsupported_causal_claims` | "delayed **because of a supplier issue**" when nothing says why |

The first works by pure set comparison: pull every number and proper noun out
of the answer, pull the same out of the question and sources, and anything in
the answer that is in neither came from the model. The other two exist because
a sentence can be a hallucination with **no number or name in it at all** — the
first check is structurally blind to those.

**The confidence number is real, and this is the important part.** It is *not*
the model being asked "how confident are you?" — a model fluent enough to
hallucinate convincingly is fluent enough to *say* it is sure, so asking is
circular. Instead ControlPlane reads the **actual log-probability the model
assigned each word as it generated it** (Ollama 0.33+ returns these), and
compares the flagged span against the response's own average. A model reciting
real information is fluent throughout; a model improvising a specific detail
tends to dip in confidence exactly where the invented detail sits. That dip is
measurable, reproducible, and impossible to fake after the fact.

It is deliberately a **capped, minority bonus** on top of the grounding-based
score — corroborating evidence sharpens a verdict, it does not replace the
reasoning behind it. If the backend has no log-probabilities, everything
behaves exactly as before.

**On screen:** the flagged text is highlighted *inside the answer itself*, with
the confidence as a small visible badge (`59%`), plus the full reasoning on
hover. Because the checks run after delivery, the highlights fade in a moment
*after* the text does — the interface demonstrating the architecture rather
than asserting it.

**Code.** `quality/checks.py`. **Cannot do:** it never says a fact is *false* —
only that it has no source. It cannot catch a wrong belief the model holds
consistently. Real contradiction detection would need an entailment model,
deliberately not built.

### 5.9 Toxicity — imported, not invented

**Problem.** Replies can be abusive.

**How it works.** An off-the-shelf pretrained classifier
(`alt-profanity-check`, a small linear model with its weights bundled in the
package — no download, no network call). We import somebody else's classifier
and report its score. Training our own is explicitly off the list: we are not
positioned to validate our own accuracy or audit our own bias.

Runs after delivery (toxicity is correctable), fails open if the dependency is
missing, and names the exact package and score in its evidence rather than
saying "flagged as toxic".

**Code.** `quality/checks.py::toxicity`. This is the **only** exception to the
engine's otherwise dependency-free rule, and `requirements.txt` says so.

### 5.10 Bias — measured, never scored per response

**Problem.** Everyone wants a "bias score" per answer. There isn't one.

**How it works — and why it is different from everything else here.** Bias is
a property of a *distribution*, not of one response. A model that favours one
group 70% of the time produces no individually-detectable answer; each one
looks reasonable alone. So the probe runs the *same request twice*, changing
only the name, and counts outcomes across many runs.

We **vary** the attribute rather than masking it. Masking demographic terms is
"fairness through unawareness" and is known to fail — the model reconstructs
the attribute from postcode, school, phrasing — so masking removes your ability
to *measure* bias without removing the bias.

It now works on **any** request, not a fixed template: it finds the person's
name in the prompt automatically (reusing the same proper-noun detector the
hallucination check uses), and reads the outcome vocabulary out of the prompt's
own instruction ("answer with exactly one word: approve or deny"), so a new
scenario needs no code change. If the prompt is not a forced choice, it falls
to an honest free-text tier: raw transcripts side by side, no invented rate.

**Code.** `quality/checks.py` + `POST /demo/bias`. The page carries the line
*"there is no per-response bias score on this page and there never will be."*

### 5.11 Feedback loop — the system learns, readably

**Problem.** Detection that produces a log line is a college project.

**How it works.** Reviewers resolve queued items. When **three independent
reviewers** overturn the same kind of flag, the system proposes a policy change
with the evidence attached. One irritated reviewer cannot widen a hole in the
detector. Applying it writes a readable diff to the audit chain.

Nothing retrains a model. What changes is a written-down exception you can read
— which is also the only kind of change a regulator accepts.

**Code.** `feedback/loop.py`. 16 tests.

### 5.12 Metrics and canaries — measuring being wrong

**Problem.** Anyone can report how often they flagged something. Nobody can
report how often they *missed* something — if you knew, you would not have
missed it.

**How it works.** Plant fake secrets in the traffic and count how many come
back. That gives a false-negative *estimate* with a **Wilson confidence
interval** and a caveat that it only describes the categories you thought to
plant. The caveat is built into the code so the number cannot be quoted alone.

False positives are different: those are *measured*, from reviewer
disagreement. The asymmetry is the honest part.

**Code.** `metrics/canary.py`, `metrics/registry.py`. 25 tests.

### 5.13 Cost — gross, overhead, net

**Problem.** A saving figure that hides its own cost is marketing.

**How it works.** Every request records what it cost, what a premium model
would have cost, and ControlPlane's own overhead. The report always shows all
three together, plus the price list's as-of date. An unpriced model raises an
error rather than silently costing zero.

**Code.** `cost/ledger.py`, `cost/pricing.py`. 22 tests.

### 5.14 The dashboard — evidence, not decoration

Five pages, each the *evidence* for a claim rather than a chart of it:

| Page | What you can check yourself |
|---|---|
| **Transit** | The prompt, what the provider received, the raw stream, the restored answer — side by side, live, plus a leak check and highlighted hallucination spans |
| **Profiles** | Change a threshold, watch the fingerprint change and the diff print. Try to exempt a credential and watch the compiler refuse. Switch jurisdiction and watch the floors clamp |
| **Review** | Resolve three items, watch a policy change get proposed with its evidence, apply it |
| **Chain** | Verify the audit chain, then tamper with an entry and watch verification name the exact break |
| **Measures** | Run a canary sweep, read cost as gross/overhead/net, probe any prompt for bias — each with what it cannot tell you |

The rule the dashboard follows: **it renders events, it never recalculates.**
An earlier build broke this twice (it re-found placeholders with its own regex
and re-implemented the buffer in three lines), which put the interface in the
position of quietly disagreeing with the engine.

---

## 6. How the pieces fit together

```
                        THE CONTROL PLANE (slow, off the request path)
                        ------------------------------------------------
                        policy/     compiles rules -> fingerprinted artefact
                        feedback/   reviewer verdicts -> proposed rule changes
                        metrics/    canary sweeps, flag rates
                                            |
                                    publishes rules
                                            v
   ============================================================================
                        THE DATA PLANE (fast, on the request path)
                        ------------------------------------------------
   request -> engine/      scan + swap real values for labels
           -> decision/    grade it: allow / annotate / review / block
           -> audit/       write a sealed, chained record (references only)
           -> feedback/session   bump counters (no text)
           -> [BLOCK HERE if needed -> cost 0.00, nothing sent]
           -> provider     the labelled text goes out
           -> stream/      buffer, scan the seam, release safely
           -> engine/      put real values back
           -> cost/        gross / overhead / net
           -> quality/     AFTER delivery: hallucination, toxicity, overclaim
```

**The split matters.** The control plane can be slow, can call out, can think.
The data plane must be fast and must never make a network call to decide
something — the rules were already compiled and are read straight from memory.

**Two front doors exist, and they are not equal:**

| Door | File | What it is | State |
|---|---|---|---|
| The demo lane | `controlplane/demo/` | An instrumented narration of the pipeline, one typed event per stage, built for the video and the dashboard | **Built. Wires nearly everything.** |
| The real gateway | `controlplane/gateway/` | The OpenAI-compatible API an actual app would point at (`/v1/chat/completions`) | **Stubs in this repo.** Real code lives in a teammate's unmerged fork |

This is the single most important thing to understand about the current state
of the project, and section 7 goes into it properly.

---

## 7. How to run it and see it for yourself

### Setup (three windows)

```bash
# window 1 - the local model, so nothing needs an API key or the internet
ollama serve
ollama pull llama3.2:1b          # once

# window 2 - the demo server (real modules, one event stream)
python -m venv .venv
source .venv/Scripts/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m controlplane.demo.server        # http://127.0.0.1:8000

# window 3 - the dashboard
cd dashboard && npm install && npm run dev  # http://localhost:3000
```

Check `http://127.0.0.1:8000/demo/health` says `"ok": true` before anything
else. An empty screen mid-demo is the worst possible failure, so that route
exists to catch it early.

To fill the review queue (it starts empty on a cold server):

```bash
python scripts/warm_demo.py
```

### The eight things to click, and what each proves

Every one of these is a preset button on the **Transit** page.

| # | Click this | Watch for | What it proves |
|---|---|---|---|
| 1 | **The round trip** | `45230` crosses the line unchanged; the name and email do not; the answer is still correct | Substitution beats redaction, and arithmetic survives |
| 2 | **The credential** | Boundary turns red, right column empty, cost `$0.00` | The password was never sent — and refusing first is what keeps it free |
| 3 | **The landmine** | Two valid card numbers, only **one** flagged, and it carries a record reference | "Is this ours?" beats "does this look sensitive?" |
| 4 | **The edge of governance** | Card caught, name *not* caught, finding says "no record reference" | Coverage degrades gradually where data is messy, instead of pretending |
| 5 | **The same finding, a stricter route** | Identical input, different profile, different outcome | Profiles are load-bearing, not decoration |
| 6 | **No single turn looks wrong** (then **Run 4 turns**) | The counter climbs and trips on the 4th; caption says "counters only" | Compounding risk caught without storing a transcript |
| 7 | **The internal vent** | Reply delivers in full, toxicity finding appears *afterwards* with a real classifier score | Reversible harm is annotated, never held |
| 8 | **The invented reason** | The invented phrase highlighted *inside the answer* with a live confidence badge | Hallucination with no number or name in it, caught — with real per-token confidence |

Then the other four pages:

- **Profiles** — click *Tighten by 0.15*: fingerprint changes, diff prints, no
  restart. Click *Try to exempt API keys*: the compiler refuses and says why.
  Set jurisdiction to **European Union**: watch the floors clamp all three
  profiles. Click *Try to loosen below the floor*: it compiles, and the
  fingerprint is **identical** — the request was silently absorbed.
- **Review** — resolve three items; after the third, a policy change is
  proposed with its evidence; apply it and the diff lands on the chain.
- **Chain** — *Verify* passes. *Tamper with entry #0*. Verify again: it names
  the exact entry and says everything after it is unprovable.
- **Measures** — *Run a sweep* (canaries with a confidence interval), read the
  cost breakdown, and paste **any** prompt naming a person into the bias box.

### Running the tests

```bash
pytest -q          # 470 tests, no network and no API key needed
```

The house standard for a test is not "does it pass" but **"can it fail?"** —
break the code on purpose and confirm that specific test goes red. Eight bugs
once shipped past a green suite here; half were green because of *how the test
was written*, not because the code worked.

---

## 8. What is really built, what is only declared

This section is the audit. It was produced by reading the code, not the docs.
Nothing here is a criticism of the project — knowing exactly where the edges
are is what makes the rest of it trustworthy.

### 8.1 Fully built, wired, and tested

| Feature | Evidence |
|---|---|
| Substitution engine (both tiers, scope, restore) | 160 tests, runs on every request |
| Route profiles, fingerprints, hot-swap, diff | 33 tests, visible on `/policy` |
| Jurisdiction floors | 11 tests, compiler-enforced, verified live on all 3 profiles |
| Decision tiers + flag budget | 26 tests, drives every request |
| Commit-point buffer | 28 tests, on the live stream path |
| Audit chain + tamper detection | 20 tests, demonstrable on `/verify` |
| Session risk counters | 11 tests, live panel on Transit |
| Hallucination (3 shapes) + real logprob confidence | 57 tests in the quality module (shared with toxicity and bias) |
| Toxicity (imported classifier) | Live on every response |
| Bias probe (any prompt, auto subject detection) | Live on `/trust` |
| Review queue + 3-reviewer threshold + policy proposal | 16 tests |
| Canaries + Wilson interval | 25 tests |
| Cost ledger (gross/overhead/net) | 22 tests |
| Dashboard, 5 pages | 33 pipeline tests behind it (`tests/test_demo/`); renders events only |

### 8.2 Declared in policy, but nothing reads it

These fields exist in the profile JSON and are **shown on the dashboard**, but
no code branches on them. A viewer would reasonably assume they do something.

| Field | Shown where | Actually enforced? |
|---|---|---|
| `quality.hallucination_tier` | Profiles page | **No** — the same tier-0 check runs for every profile |
| `quality.toxicity_sync` | Profiles page | **No** — toxicity always runs async (documented, D31) |
| `quality.counterfactual_sample_rate` | (used in `decision-support`) | **No** — the bias probe is manual-only, never sampled from live traffic |
| `inbound.substitute_pii`, `inbound.known_value_matching` | Profiles page | **No** — substitution always runs |
| `outbound.scan_pii`, `outbound.cross_tenant_check` | — | **No** — outbound scanning is not profile-conditional |
| `inbound.block_credentials`, `outbound.block_credentials` | — | **No** — credential blocking is unconditional (safe direction, but not policy-driven) |
| `cost.cache_enabled`, `cost.max_output_tokens`, `cost.request_budget_usd` | — | **No** — caching was deliberately not built (D13); the budget gate exists and is tested but is never called on the live path |
| `audit_level` | Profiles page | **No** — every entry is written the same way |

**Why this matters:** two of these (`toxicity_sync`, `counterfactual_sample_rate`)
are already written up honestly in DRAWBACK.md. The other six are not, and a
judge who opens `policy/profile.py` and greps for one of them will find it read
by nobody. Fixing the *documentation* here costs an hour; fixing the *code*
costs more but not much (see 9.2).

### 8.3 Stub files in this repository — RESOLVED 2026-09-02

*This section described the repository before the Track B merge. Kept, with the
resolution recorded, because a fixed gap and a gap that was never there are not
the same thing.*

**Was:** `controlplane/gateway/` and `controlplane/seed/` shipped as TODO stubs
— 10 to 22 lines each, a docstring and `# TODO(Track B)`. `tests/test_gateway/`
contained zero tests. The README's headline claim ("the app changes one line —
its `base_url`") had no runnable code behind it in this repository.

**Now:** merged (plan phase 0.2). 1,893 lines across `gateway/{app,pipeline,
upstream,context}.py`, `seed/{generate,traffic}.py` and `scripts/
demo_roundtrip.py`, plus 28 tests in `tests/test_gateway/`. The merge applied
cleanly; the only deletions were the ten `# TODO(Track B)` markers.

The claim is now checkable rather than assertable:
`test_openai_client_with_only_base_url_changed` drives an unmodified
`openai.AsyncOpenAI` client against the gateway with nothing changed but
`base_url`, and asserts the caller reads back the restored real name while the
upstream only ever saw the placeholder.

### 8.4 A gap between the two lanes

**Still open after the merge** — this is what plan phase 3 exists to close:

| Component | Demo lane (`demo/orchestrator.py`) | Real gateway (`gateway/pipeline.py`) |
|---|---|---|
| Substitution + restore | yes | yes |
| Policy profiles | yes | yes |
| Commit-point buffer | yes | yes |
| **Decision tiers** | yes | **no** |
| **Audit chain** | yes | **no** |
| **Cost ledger / budget gate** | yes | **no** |
| **Session risk** | yes | **no** |
| **Quality checks** | yes | **no** |

So the pipeline a real application would hit is thinner than the one the video
shows. This is the single biggest structural gap in the project and is not
currently written up in DRAWBACK.md.

### 8.5 Smaller findings

- **`RESTORE` event is declared and never emitted.** `demo/events.py` defines
  `RESTORE = "restore"`; `orchestrator.py` never uses it. Harmless dead code,
  but it is in a file whose whole job is to be the event contract.
- **Audit log is memory-only (D14).** Restart the server and the chain is gone.
  Fine for a demo, named openly, but it is not an audit log yet.
- **`demo/server.py` has no tests.** 883 lines — the largest file in the
  project — verified only by hand and by browser. Its route logic is thin glue,
  but the bias route now contains real tier-selection logic worth testing.
- **A known false positive, now more visible.** A reply that opens with a quote
  mark (`"Hey team, ...`) gets "Hey" flagged as an invented entity, because the
  quote character defeats the sentence-start check. It predates the
  highlighting work; the highlighting just makes it easier to see.
- **Local model output is not perfectly reproducible.** A fixed seed reduces
  variance; it does not eliminate it. A prompt sitting near the model's refusal
  boundary can flip behaviour between runs. One demo preset had to be reworded
  for exactly this reason.
- **The current branch is not merged.** `phase-6/dashboard-and-demo` is 4
  commits ahead of `origin/main`, plus a large body of uncommitted work
  (toxicity, bias generalisation, hallucination depth). `main` does not yet
  contain the dashboard.

---

## 9. What is left to do

Ordered by what a judge is most likely to notice.

### 9.1 Must do before submission

| # | Task | Why it matters | Rough effort |
|---|---|---|---|
| 1 | **Commit and push the current work** | 4 commits plus a day of uncommitted work sit only on a local branch. A public repo that does not contain the dashboard undercuts every claim about it | 15 min |
| 2 | **Merge Track B's fork** | Without it the repo ships stub files and zero gateway tests, and the "one line change" claim has no code behind it | 1-2 h including conflict check |
| 3 | **Record the demo video** | DEMO-SCRIPT.md is written and timed at 8:40 — but no take exists | half a day with retakes |
| 4 | **Fix the docs in 8.2** | Six profile fields are displayed as if they do something. Either enforce them or label them | 1 h |

### 9.2 Should do if there is time

| # | Task | Value |
|---|---|---|
| 5 | **Wire the checks into the real gateway** (see 8.4) | Closes the gap between what the video shows and what an app would actually get |
| 6 | **Enforce `hallucination_tier` and `toxicity_sync`** | Makes two visible profile settings real; small, contained changes |
| 7 | **Wire `counterfactual_sample_rate`** | Bias probing on sampled live traffic instead of a manual button. It doubles token cost per sampled request, so it belongs in the cost ledger, not hidden |
| 8 | **Persist the audit chain** | Even a JSON-lines file moves it from "demo" to "prototype" (D14) |
| 9 | **Add route tests for `demo/server.py`** | Largest file, no tests; the bias tiering logic now deserves them |

### 9.3 Explicitly not doing, and why

These are decisions, not omissions. Each has a written reason.

| Not built | Reason |
|---|---|
| NER model for free-text names | Non-deterministic and slow on the synchronous path; would undercut the determinism that makes the detection tier credible (D10) |
| Semantic caching | The similarity threshold is a *correctness* risk, not a cost one — too loose and you serve the answer to a different question (D13) |
| Real-time bias scoring | Structurally impossible: bias is a property of a distribution (D12) |
| Consistency sampling | Only catches *random* fabrication; systematic failures reproduce identically and get scored reliable (D11) |
| Prompt injection detection | Duplicates what the provider already does with better visibility, and the one variant that would be ours has no target — the model was never given the real value, so it cannot be talked into revealing it (D30) |
| Multi-turn content memory | Breaks statelessness, which is rule #1. Cumulative risk is tracked with counters instead (D4) |
| Envoy / Rust hot path | The check costs milliseconds; the model call costs seconds. Buys nothing measurable |

---

## 10. What could be improved

Beyond simply finishing what exists.

### 10.1 Correctness

1. **Fix the quote-mark false positive.** `_starts_a_sentence` should treat an
   opening quote as sentence-initial. One line, removes a visibly wrong flag.
2. **Give the hallucination check real sources.** It currently compares the
   answer against the *question only* — `sources=""` is hardcoded in the
   orchestrator. In a real RAG deployment the retrieved documents are the
   source, and passing them in would cut false positives sharply: today a
   correct-but-new fact is indistinguishable from an invented one.
3. **Separate "absent from source" from "contradicts source".** Both read as
   one category today. Contradiction is a much stronger signal and deserves a
   higher tier.
4. **Cover the `[[CUST_A2]]` case in the highlighter.** Placeholder numbering
   goes past `Z`; the span logic looks fine, but it deserves a test.

### 10.2 The product story

5. **Make one more profile field visibly enforced per demo beat.** The Profiles
   page shows eight settings and enforces two. Enforcing even two more makes
   the page match its own promise.
6. **Show the cost of the safety machinery on screen.** The ledger separates
   overhead already, but nothing says "these checks cost $X per thousand
   requests". That number persuades a sceptic more than a saving does.
7. **Show the false-positive rate beside the false-negative estimate.** Both
   exist in `metrics/`; only the canary side reaches the screen.

### 10.3 Engineering hygiene

8. **Test the demo server routes.** FastAPI's `TestClient` plus a fake model
   would cover all 20 routes cheaply.
9. **Pin the numeric dependencies.** `alt-profanity-check` pins scikit-learn,
   but numpy floats free and already emits a deprecation warning unpickling the
   model. A future numpy could break toxicity on a clean install — the worst
   possible moment to discover it.
10. **Delete or emit the `RESTORE` event.** Dead code inside the event contract.
11. **Split `demo/server.py`.** 883 lines; bias, policy and audit routes are
    three independent concerns sharing one file.

### 10.4 For a real deployment

12. **Persist audit, policy versions and metrics.** All three live in memory.
13. **Multi-tenancy.** Everything assumes one organisation. Records, profiles
    and sessions would each need a tenant key.
14. **Key management.** Teams are identified by API key; there is no rotation,
    revocation or scoping story yet.
15. **Backpressure and timeouts.** The buffer holds text per request in memory;
    a slow reader or a very long generation has no limit today.

---

## 11. Honest risks on demo day

| Risk | What already mitigates it | What remains |
|---|---|---|
| The local model refuses or drifts (a fixed seed is not a guarantee) | Presets chosen and re-verified for reliability; `warm_demo.py`; a restart-and-reload recovery note in the script | Real. Rehearse every preset on the morning |
| The repo shows stub gateway files | — | Merge Track B first |
| A judge greps a profile field and finds nothing reads it | Two are documented | Fix the other six |
| Audit chain lost on restart | Named as D14 | State it openly on stage |
| Eleven demo beats against a 10-minute pitch | Timed at 8:40, with a documented 5-minute cut | Fine, if rehearsed |

---

## 12. Quick reference

### Where everything lives

```
controlplane/
  engine/    find and swap sensitive values, put them back      [BUILT]
  policy/    compile rule sets, fingerprint them, jurisdictions [BUILT]
  decision/  allow / annotate / review / block                  [BUILT]
  audit/     hash-chained, tamper-evident record                [BUILT, in memory]
  feedback/  review queue, policy tuning, session counters      [BUILT]
  metrics/   canaries, Wilson intervals, flag rates             [BUILT]
  cost/      gross / overhead / net                             [BUILT]
  stream/    commit-point buffer, seam scanning                 [BUILT]
  quality/   hallucination, toxicity, bias                      [BUILT]
  demo/      the narrated pipeline plus 20 HTTP routes          [BUILT]
  gateway/   the real OpenAI-compatible API                     [BUILT, merged]
  seed/      synthetic customer records and traffic mix         [BUILT, merged]
dashboard/   Next.js, 5 pages, renders events only              [BUILT]
tests/       470 tests                                          [28 of them gateway]
```

### Glossary

| Term | Plain meaning |
|---|---|
| **Placeholder** | The fake label (`[[CUST_A]]`) standing in for a real value |
| **Profile** | A named rule set for one kind of use (support chat, internal assistant) |
| **Fingerprint** | A short code proving two servers run identical rules |
| **Commit point** | The moment the buffer decides a piece of text is safe to show |
| **Reversible harm** | A mistake you can correct afterwards (a wrong fact) |
| **Irreversible harm** | Something that cannot be un-seen once shown (a password) |
| **Canary** | A fake secret planted in traffic to measure what the detector misses |
| **Known-value matching** | Checking against the company's own records, not a pattern |
| **Logprob** | The probability the model assigned a word as it wrote it — used as real confidence, never a self-report |
| **Jurisdiction floor** | A country-level minimum a profile may exceed but never undercut |

### The fifteen seconds that are the whole pitch

Paste a real customer record. Get a correct, useful answer. Then show that the
provider only ever saw `[[CUST_A]]` — and that the arithmetic in that answer is
still right.

Everything else in this repository exists to make that moment credible.
