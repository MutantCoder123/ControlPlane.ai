# Prompt for Track B's AI coding tool

Copy everything below the line into your AI coding assistant, in the checkout
that has your unpushed Track B work.

---

## Context you need before touching anything

I am Track B on a two-person hackathon project called **ControlPlane**
(repo: `https://github.com/MutantCoder123/ControlPlane.ai`). I cloned this
repo early — right after the initial scaffold commit — built my half locally,
and never pushed. The repo has moved a long way since. I need to land my work
on top of current `main` **without losing it and without breaking anything**.

Two facts that change the safe approach:

**1. The remote history was rewritten after I cloned.** Shortly after the
initial push, a file was removed from the repo's history and the result was
force-pushed. So my local `main` may descend from commits that **no longer
exist upstream**. If so, `git pull` will either refuse ("unrelated histories")
or produce a catastrophic merge. Do not run a plain `git pull` or
`git merge origin/main` until you have checked this.

**2. The project uses strict file ownership**, which is what makes this
recoverable. My lane and my partner's lane do not overlap, so my work can be
**transplanted** onto current `main` rather than merged into it.

| Path | Owner | Status on current `main` |
|---|---|---|
| `controlplane/gateway/**` | **me (Track B)** | still the original untouched stubs |
| `controlplane/seed/**` | **me (Track B)** | still the original untouched stubs |
| `tests/test_gateway/**` | **me (Track B)** | empty except `__init__.py` |
| `scripts/demo_roundtrip.py` | **me (Track B)** | still the original stub |
| `README.md` | nominally mine, **but partner has edited it heavily** | ⚠️ conflict expected |
| `CONTRACTS.md`, `requirements.txt`, `.gitignore` | shared | ⚠️ conflict expected |
| `controlplane/engine/**` | partner (Track A) | **fully implemented now** — was stubs when I cloned |
| `controlplane/policy/**`, `audit/`, `decision/`, `feedback/`, `cost/`, `metrics/`, `stream/`, `quality/` | partner | **new since I cloned** — did not exist |

Current `main` has **346 passing tests**. My work must not reduce that number.

**Read the current versions of these files from `origin/main`, not from my
working tree** — my checkout is months of work out of date and its copies of
`CONTRACTS.md`, `README.md` and `controlplane/engine/` are stale:

```bash
git fetch origin
git show origin/main:CONTRACTS.md
git show origin/main:controlplane/engine/api.py
git show origin/main:controlplane/engine/placeholders.py
```

---

## Step 0 — safety first, before anything else

```bash
git branch backup/track-b-local          # snapshot exactly what I have
git stash list && git status             # capture anything uncommitted
git log --oneline -5                     # note my base commit
```

If I have uncommitted work, commit it to `backup/track-b-local` first. Do not
proceed until my work exists in at least one commit I can get back to.

**Never run `git push --force` against `origin`.** My partner's work is there.

---

## Step 1 — diagnose which situation I am in

```bash
git remote -v                            # confirm origin points at the repo above
git fetch origin
git merge-base HEAD origin/main          # empty output = unrelated histories
git cat-file -e 1c97b59 2>/dev/null && echo "rewritten-scaffold present" || echo "absent"
```

- **If `git merge-base` prints a commit**: my history connects. A rebase is
  possible, but the transplant in Step 3 is still safer and faster — my changed
  files barely overlap anyone else's.
- **If `git merge-base` prints nothing**: unrelated histories, exactly as
  warned. **Do not merge or rebase.** Use the transplant. This is the expected
  case.

Either way, tell me which situation applies before continuing.

---

## Step 2 — inventory exactly what I changed

I need to know precisely which files carry my work, so nothing is missed and
nothing extra is dragged along.

```bash
# Compare my work against the scaffold I started from
git diff --stat $(git log --oneline | tail -1 | cut -d' ' -f1) HEAD
git status --porcelain
```

Produce a list, and classify each file into:

- **A — my lane** (`controlplane/gateway/**`, `controlplane/seed/**`,
  `tests/test_gateway/**`, `scripts/demo_roundtrip.py`) → transplant as-is
- **B — shared** (`requirements.txt`, `.gitignore`, `CONTRACTS.md`) → re-apply
  my additions by hand onto the current version
- **C — partner's lane** (`controlplane/engine/**` or any of the newer
  packages) → **discard my version.** If I edited these, I was working against
  stubs that are now real implementations; mine are certainly stale
- **D — `README.md`** → take current `main`'s version and re-apply only my
  sections. Do not overwrite it wholesale; it now documents the whole project

Show me the classification before acting on it.

---

## Step 3 — transplant onto current `main`

```bash
# Save my files somewhere outside the repo
mkdir -p /tmp/trackb
git archive HEAD controlplane/gateway controlplane/seed tests/test_gateway scripts \
  | tar -x -C /tmp/trackb

# Start clean from current upstream
git fetch origin
git checkout -b track-b/gateway-and-seed origin/main

# Restore only my lane
cp -r /tmp/trackb/* .
git status                               # review before staging
```

Then, separately and by hand:

- **`requirements.txt`** — the file is append-only by team convention. Add any
  dependency I need that is missing; never remove or re-pin an existing line.
- **`.gitignore`** — add my entries only.
- **`README.md`** — start from `main`'s version, re-apply only my sections.
- **`CONTRACTS.md`** — read it, do not edit it. If something in it is wrong,
  flag it to me rather than changing it unilaterally.

Do **not** copy anything from `controlplane/engine/` or the newer packages.

---

## Step 4 — reconcile with what changed while I was away

My code was written against stubs. Several are now real, and two things I was
told to leave as seams have since been built. Check my code against these and
report anything that needs updating:

**The engine is real now.** `controlplane/engine/api.py` still defines
`Finding`, `ScanResult`, `RestoreResult` with the same fields, and
`SubstitutionEngine` still exposes `scan_inbound`, `scan_outbound`, `restore`.
The contract held, so my `pipeline.py` calls should still be correct — verify
rather than assume.

**Placeholders are `[[CUST_A]]`-shaped.** If I hardcoded a placeholder format
anywhere, replace it with an import:
`from controlplane.engine.placeholders import PLACEHOLDER_RE, is_placeholder`.
Hardcoding it is a real bug even where it currently works.

**The commit-point buffer now exists** (`controlplane/stream/buffer.py`). My
brief told me to stream straight through and leave a seam. That seam can now
be filled:

```python
from controlplane.stream.buffer import CommitPointBuffer

buf = CommitPointBuffer(profile, engine.scan_outbound,
                        restore=engine.restore, mapping=scanned.mapping)
for chunk in upstream_stream:
    for release in buf.feed(chunk):
        if release.blocked:
            stop_the_stream(release.reason)
        else:
            write_to_client(release.text)
for release in buf.flush():
    write_to_client(release.text)
```

**The policy engine now exists** (`controlplane/policy/store.py`). My brief
said to treat `X-ControlPlane-Profile` as a passthrough string. It can now
resolve properly via `PolicyStore.profile_for(name)`, which raises
`PolicyError` on an unknown profile rather than falling back to something
permissive. Wire this only if it is straightforward; flag it if not.

Do these as **separate commits** from the transplant, so the diff stays
readable.

---

## Step 5 — verify

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

Requirements to satisfy before pushing:

- **All 346 pre-existing tests still pass**, plus mine. If any pre-existing
  test now fails, my transplant touched something it should not have — stop and
  report which.
- `python -m controlplane.seed.generate` writes `controlplane/seed/data/records.jsonl`
- `python scripts/demo_roundtrip.py` prints the round trip
- An unmodified `openai` client works against the gateway with only `base_url`
  changed

**Seed-data schema check.** My generator must emit exactly the schema in
`CONTRACTS.md §2`, including `role` (`identifier` | `operand`) and `governance`
(`governed` | `ungoverned`) on every field. Track A's engine is built against
that schema and has tests that depend on it. If Track A's tests fail against my
real `records.jsonl`, the schema was ambiguous — report it as a contract
problem, do not "fix" it by editing their tests.

---

## Step 6 — push

I have been asked to fork. Either of these is fine — confirm which with me:

**Fork + pull request:**
```bash
# fork on github.com first, then:
git remote add fork https://github.com/<my-username>/ControlPlane.ai.git
git push -u fork track-b/gateway-and-seed
# open a PR: my fork's branch -> MutantCoder123/ControlPlane.ai : main
```

**Or branch on the shared repo** (simpler for two people, same result):
```bash
git push -u origin track-b/gateway-and-seed
```

Either way: **a branch and a PR, never a push straight to `main`, and never a
force-push.**

---

## Rules for this whole task

1. **Never force-push to `origin`.** My partner's work is there.
2. **Never `git pull` / `git merge origin/main`** until Step 1 confirms the
   histories are related.
3. **Keep `backup/track-b-local` intact** until the PR is merged.
4. **Stay in my lane.** If a fix seems needed in `controlplane/engine/**` or
   any package I do not own, report it — do not edit it.
5. **Do not edit `CONTRACTS.md`** unilaterally. It is the agreement that made
   this recoverable.
6. **Do not reduce the test count.** 346 pre-existing tests pass on `main`.
7. If anything is ambiguous, **stop and ask me** rather than guessing. Losing
   the work is the only unrecoverable outcome here.

Start with Step 0 and Step 1, then report what you found before making changes.
