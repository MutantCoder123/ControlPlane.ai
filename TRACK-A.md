# TRACK A — The Substitution Engine (P3)

**You own:** `controlplane/engine/**` and `tests/test_engine/**`
**Your partner is on:** [TRACK-B.md](TRACK-B.md) — gateway spine + seed data
**Shared interface:** [CONTRACTS.md](CONTRACTS.md) — read it first
**Design background:** IDEATION.md §9 · Drawbacks D15, D9, D10, D16

---

## Why this part matters more than the others

This is the differentiator. Everything else in ControlPlane exists in other
products; **known-value matching does not.**

Pattern matching asks *"does this look like a secret?"* We ask *"is this **our**
secret?"* — because the organisation already knows its own sensitive data. That
flips every weakness of regex at once: we catch unstructured PII
deterministically (we don't guess "Priya Sharma" is a name, we know she is
customer 44219), we catch internal formats nobody wrote a pattern for, and test
data stops firing — `4111 1111 1111 1111` passes the Luhn check but isn't in the
customer database, so it isn't ours, so it isn't a finding.

The audit line stops being *"matched a regex"* and becomes
*"matched customer record 44219."* That sentence is the product.

**And this is the one part that fails live, on stage, rather than politely in
Q&A.** Demo step 3 is fifteen seconds long and it is the whole pitch. If it
produces `[CUSTOMER_A]'s account` in front of the jury, we lose the moment we
built everything else to reach.

---

## Build in this order — the order matters

### Step 1 — `engine/placeholders.py` — decide the format FIRST

**Do not skip ahead to the matcher.** This is D15, the drawback rated 🔴 for
exactly this reason: *restoration fidelity is the sharp edge, not detection.*

Detection is the easy half. The hard half is that the model will not hand your
token back unchanged. It will write possessives, pluralise, change case, wrap it
in quotes or backticks, put it inside JSON, or split it across a line break.
Naive `str.replace()` handles none of that.

Before writing anything else, pick a format and prove it survives:

| Adversarial case | What the model might emit |
|---|---|
| Possessive | `[CUSTOMER_A]'s account balance` |
| Case change | `[customer_a]` |
| Inside code | `` `[CUSTOMER_A]` `` or `{"name": "[CUSTOMER_A]"}` |
| Pluralised | `[CUSTOMER_A]s` |
| Adjacent punctuation | `[CUSTOMER_A],` `([CUSTOMER_A])` |
| Line-wrapped | `[CUSTOMER_\nA]` |
| Repeated | same entity twice → must map to the same placeholder |

Expose exactly two things to the rest of the world:

```python
PLACEHOLDER_RE          # compiled regex that matches your format tolerantly
def is_placeholder(s: str) -> bool
def make_placeholder(category: str, index: int) -> str
```

Track B is contractually forbidden from hardcoding your format (CONTRACTS §4),
so you are free to change it — but change it *now*, not after the matcher exists.

**Write the adversarial test file before the implementation.** If you do one
thing from this brief in a test-first way, make it this.

### Step 2 — `engine/knownvalue.py` — the known-value store

Load `controlplane/seed/data/records.jsonl` (schema in CONTRACTS §2, produced by
Track B). For every field with `role == "identifier"` **and**
`governance == "governed"`:

- normalise (casefold, collapse whitespace, strip punctuation)
- hash it
- put the hash in a set, with a Bloom filter in front

**Store hashes, never raw values.** If someone dumps our memory they must not
get a customer list — otherwise we become the concentration risk we sell
protection against.

Then scan inbound text for those hashes. Tokenise into candidate n-grams (names
are usually 1–3 tokens) and check the filter first, the set second.

**D9 — this is exact-match only, and that is a known, stated limitation.**
Normalisation buys you case, whitespace and punctuation. It does *not* buy you
misspellings, nicknames, or transliteration. Do not try to solve that here; a
production system uses an NER model for the unknown-entity case, and we say so
openly. Getting exact match *right* is worth more than getting fuzzy match
*roughly*.

### Step 3 — `engine/patterns.py` — the structured-secret tier

Pattern **plus checksum**, never pattern alone:

| Type | Pattern | Checksum |
|---|---|---|
| Payment card | 13–19 digits, optional separators | **Luhn** |
| Aadhaar | 12 digits | **Verhoeff** |
| IBAN | country + digits | **mod-97** |
| API keys / JWTs | prefix + entropy (`sk-`, `ghp_`, `eyJ...`) | structural |

**The checksums are the whole point of this tier** (IDEATION §9.1). Without
them every long order number looks like a card and we drown the user in false
positives — which is D26/alert-fatigue territory, and the brief calls it out by
name.

Action rules (IDEATION §9.5):
- **Credentials → `action="block"`.** There is no legitimate reason to send an
  API key to a model. Refusing costs the user nothing.
- **Customer/employee PII → `action="substitute"`.** This is the *use case*, not
  the abuse case. Blocking every prompt containing customer data blocks the
  entire reason they bought the tool.

**D10 — say plainly in the module docstring** that this tier is a prototype
stand-in for a real NER model, and that it catches unstructured PII only when
the value is in the known-value store.

### Step 4 — `engine/substitute.py` — assembly

Wire the two tiers into `scan_inbound`, `scan_outbound`, `restore`, matching
CONTRACTS §3 exactly.

Two rules that carry design decisions:

**Same entity → same placeholder, within one request.** Relational reasoning has
to survive substitution. If "Priya Sharma" appears three times it must be
`[CUSTOMER_A]` all three times, or the model can no longer tell it is the same
person and the answer degrades.

**Never substitute operands.** Take `role` straight from the seed data (D16).
Sensitivity lives in the *linkage*, not the value: `₹45,230` alone is
meaningless, `Priya's salary is ₹45,230` is sensitive because of the name. Swap
the name, let the number through, and the arithmetic in the model's answer is
still correct. That is what makes this substitution rather than redaction.

The genuine failure case — when the identifier *is* the operand, e.g. *"validate
this account number's checksum"* — is **not solvable here**. Return the finding,
let a later portion (P6, decision tiers) route it to a human. Leave a labelled
comment pointing at D16.

---

## Done when

```bash
pytest tests/test_engine/ -v
```

…and specifically:

1. **Round-trip holds** across every adversarial case in the Step 1 table.
2. **`unrestored` is empty** for a normal response. That list is your D15 alarm —
   if it is ever non-empty in the demo, the format is wrong.
3. **Arithmetic survives.** Feed a record where salary is an operand; confirm a
   sum computed over substituted text is still right.
4. **Test data does not fire.** `4111 1111 1111 1111` passes Luhn but is not in
   the store → not a finding. This is the moment that proves known-value beats
   regex; make it an explicit test with that name.
5. **An ungoverned record still gets pattern-tier coverage** but no
   `record_ref`. That is D28 demonstrated rather than asserted.
6. **No raw value appears in any log line or `__repr__`.**

---

## Do not build

- **NER / GLiNER / any ML model.** Non-deterministic, slow on the sync path, and
  it undoes the "deterministic" claim that makes this tier credible. D10 covers
  the gap in prose.
- **Fuzzy or semantic matching.** D9 is a stated limitation, not a TODO.
- **Anything touching the gateway, HTTP, or streaming.** That is Track B. Your
  module must stay importable and testable with zero network.
- **Persistence of `mapping`.** Request-scoped, in memory, then gone (§3).

---

## Where you meet Track B

They are building the FastAPI gateway that will call you, and the seed data you
load. Concretely:

- **They produce** `controlplane/seed/data/records.jsonl` in the CONTRACTS §2
  schema. **Do not wait for it** — hand-write a 5-record fixture in
  `tests/test_engine/fixtures/` today and build against the schema. When their
  generator lands, your tests should pass unchanged. If they don't, the schema
  was ambiguous and CONTRACTS.md needs fixing.
- **They call you** from `gateway/pipeline.py` via exactly the four names in
  CONTRACTS §3. Anything else you expose is private to your package.
- **They must never** hardcode your placeholder format. If you see it in their
  code, flag it — that is a live D15 bug even if it works today.

**Tell them immediately if** you need a field the schema doesn't have, or the
`Finding` shape doesn't fit what you found. Change CONTRACTS.md first, together,
then the code.
