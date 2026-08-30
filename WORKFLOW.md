# WORKFLOW — how the two of us work

Two people, two tracks, one contract. This file is the protocol; it applies to
both of us equally.

New to the project? Start with [ONBOARDING.md](ONBOARDING.md) instead.

---

## 1. The model

We do **not** both work on whatever seems urgent. Work is cut into *portions*.
A portion is a slice of [BUILD-PLAN.md](BUILD-PLAN.md) small enough that both of
us can finish our half without waiting on the other.

For each portion:

1. The portion is split into two tracks with **no dependency between them**.
2. The interface where they meet is written down in
   [CONTRACTS.md](CONTRACTS.md) **before either of us writes code**.
3. Each track gets a brief saying what to build, which drawbacks it owns, and
   what "done" means.
4. Both halves land, we integrate, and only then do we cut the next portion.

**Why no dependency between tracks:** the obvious ordering for Portion 1 was
seed data → engine → gateway, which is a chain. One of us would have sat idle.
Splitting against the contract instead means both start on day one.

### Portion 1 (current)

| | Track A | Track B |
|---|---|---|
| Owner | Indranil | teammate |
| Builds | Substitution engine (P3) | Seed data + traffic sim (P13), gateway spine (P1) |
| Brief | [TRACK-A.md](TRACK-A.md) | [TRACK-B.md](TRACK-B.md) |
| Lane | `controlplane/engine/**` | `controlplane/gateway/**`, `controlplane/seed/**` |

---

## 2. File ownership — the anti-conflict rule

Ownership is listed in [CONTRACTS.md §1](CONTRACTS.md). The short version:

- **Track A** owns `controlplane/engine/**`, `tests/test_engine/**`
- **Track B** owns `controlplane/gateway/**`, `controlplane/seed/**`,
  `tests/test_gateway/**`
- **Shared, by agreement only:** `CONTRACTS.md`, `requirements.txt`

If you need a change in the other person's lane, **ask them to make it.** Do not
edit it yourself, even if it is one line and obviously correct. Staying in your
lane is why we will almost never see a merge conflict.

*This rule got broken once and it is worth recording how.* `README.md` was
assigned to Track B. Track A edited it through four phases without asking —
each edit individually reasonable, none of them agreed. Nobody noticed until
integration, when it turned into the one guaranteed conflict in an otherwise
clean transplant. The lesson is not "be more careful": it is that a lane
crossing is invisible while you are alone on a branch, so the check has to
happen at review time, on the checklist, every time.

`requirements.txt` is **append-only**. Never remove or re-pin another track's
dependency without saying so.

---

## 3. Branches and commits

```bash
git checkout main && git pull
git checkout -b track-a/substitution-engine     # or track-b/gateway-and-seed
```

Branch naming: `track-<a|b>/<short-thing>`.

Commit whenever a piece works. Small commits beat one heroic commit — if
something breaks we want to know which change did it.

Message format: a short imperative line, then *why* if it is not obvious.

```
Add Verhoeff checksum for Aadhaar detection

Without the checksum every 12-digit order number reads as an Aadhaar
number, which is exactly the false-positive flood D26 is about.
```

Reference drawback IDs (`D15`, `D28`) and IDEATION sections in commit bodies
where they explain a decision. Future us will not remember.

---

## 4. Pushing and merging

Push your branch daily, even if unfinished. A branch nobody can see is a branch
nobody can help with.

```bash
git push -u origin track-b/gateway-and-seed
```

When your half of the portion is green, open a PR into `main`. The other person
reviews. **Review is not a formality** — you are the only other person who
understands this codebase, and a public repo means judges may read it too.

Review checklist:

- [ ] Does it stay inside its lane?
- [ ] Does it honour [CONTRACTS.md](CONTRACTS.md) exactly?
- [ ] Are stubs **labelled** as stubs? (D23 — an unmarked gap reads as vapour)
- [ ] Do tests pass without network or an API key?
- [ ] Are raw sensitive values absent from logs and `__repr__`?

### And the one that actually caught things: *can this test fail?*

Portion 1 shipped eight bugs past a green suite. Half of them were green
because of **how the test was written**, not because the code worked. A test
that cannot fail is worse than no test: it occupies the slot where a real one
would have gone, and it reports success.

Check each new test against these four shapes:

| Shape | What it looks like | Why it passes anyway |
|---|---|---|
| **Built from its own output** | Feeds `restore()` a reply assembled from the placeholders `scan()` just returned | Proves we can undo something we handed ourselves, not that a real reply survives |
| **Transport, not logic** | A streaming test asserting SSE framing — `data:` prefixes, `[DONE]` | The bytes are well-formed whatever the buffer decided |
| **No assertion** | A call with no `assert`, relying on "it didn't raise" | Sometimes legitimate — then say so, and assert the state it leaves behind |
| **Acceptance script that can't fail** | Prints output, exits 0 regardless | Nobody reads the output once it's in CI |

The test for a test: **make the code wrong on purpose and watch it go red.** If
it stays green, the test is decoration. Mutating one line and re-running takes
under a minute, and it is the only check that actually proves the assertion is
load-bearing.

Merge with a merge commit, not a squash — we want the individual steps.

---

## 5. When to talk to each other

Four moments, and they are not optional:

**Before changing CONTRACTS.md.** Always. The contract is the only thing
keeping the halves compatible. Agree the change, edit the file *first*, then
write the code that depends on it.

**When the first real artefact lands.** Track B: tell A the moment
`records.jsonl` exists for real — they have been working against a hand-written
fixture and will want to swap it in. If A's tests then fail, the schema was
ambiguous and CONTRACTS.md needs fixing, not the tests.

**When you are blocked for more than an hour.** Do not grind. Say what you are
stuck on. Most blocks here are contract ambiguities, and the other person can
resolve them in two minutes.

**When you want to build something not in your brief.** See §6.

---

## 6. Scope discipline — the thing most likely to sink us

Both briefs have a **"do not build"** section. Those are not suggestions and
they are not there because we ran out of time.

Every item was triaged in [DRAWBACK.md §0](DRAWBACK.md). Some things are
deliberately answered in prose rather than code, because the format rewards it:
the finale is a 10-minute pitch and a 5-minute Q&A, so a weakness that gets
*asked about* needs a good answer, not an implementation. Building it anyway
costs hours and scores nothing.

Concretely, do not "helpfully" add: semantic caching (D13), an NER model (D10),
real-time bias detection (D12 — it is structurally impossible), multi-turn state
(D4 — it breaks our statelessness positioning), or the profile engine before its
portion (P2).

**If you think something belongs in scope, say so and make the case.** The
triage is a judgement, not scripture, and it has already changed once when the
Round 2 brief arrived. What must not happen is scope drifting silently in a
branch nobody reviewed.

---

## 7. Definition of done for a portion

A portion is done when this works from a **clean checkout**, not just on the
machine where it was written:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest
```

Plus the portion-specific acceptance in [CONTRACTS.md §6](CONTRACTS.md).

"Works on my machine" is how demos die on stage. Test the clean path.

---

## 8. Then what

When both halves land, we integrate, update the docs that moved
([DRAWBACK.md](DRAWBACK.md) changelog, README status table), and cut the next
portion from [BUILD-PLAN.md](BUILD-PLAN.md).

We do not plan the next portion in advance. What we learn building this one
changes what the next one should be — that already happened once when the Round
2 brief reordered the whole build.
