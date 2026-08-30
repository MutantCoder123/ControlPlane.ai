# CONTRACTS — the interface between Track A and Track B

**Read this before writing any code. Both tracks depend on it.**

This file is the reason the two halves will fit together at the end. Neither
track may change anything here unilaterally — if a contract turns out wrong,
say so, agree the change, and edit this file *first*, then the code.

Portion 1 owners:
- **Track A** → `controlplane/engine/` — see [TRACK-A.md](TRACK-A.md)
- **Track B** → `controlplane/gateway/` + `controlplane/seed/` — see [TRACK-B.md](TRACK-B.md)

---

## 1. File ownership — do not edit outside your lane

| Path | Owner | Notes |
|---|---|---|
| `controlplane/engine/**` | **A** | B never edits |
| `controlplane/policy/**` | **A** | Added 2026-08-30 (P2). New lane, nothing of B's moved |
| `controlplane/audit/**` | **A** | Added 2026-08-30 (P8). New lane, nothing of B's moved |
| `controlplane/decision/**` | **A** | Added 2026-08-30 (P6). New lane |
| `controlplane/feedback/**` | **A** | Added 2026-08-30 (P9). New lane |
| `controlplane/cost/**` | **A** | Added 2026-08-30 (P11). New lane |
| `controlplane/metrics/**` | **A** | Added 2026-08-30 (P10). New lane |
| `controlplane/stream/**` | **A** | Added 2026-08-30 (P4). New lane |
| `controlplane/quality/**` | **A** | Added 2026-08-30 (P7). New lane |
| `controlplane/gateway/**` | **B** | A never edits |
| `controlplane/seed/**` | **B** | A consumes the *data*, never edits the generator |
| `tests/test_engine/**`, `tests/test_policy/**`, `tests/test_audit/**`, `tests/test_decision/**`, `tests/test_feedback/**`, `tests/test_cost/**`, `tests/test_metrics/**`, `tests/test_stream/**`, `tests/test_quality/**` | **A** | |
| `tests/test_gateway/**` | **B** | |
| `CONTRACTS.md` | **both** | Only by agreement. Announce before editing |
| `README.md` | **B** | A supplies the engine section when asked |
| `requirements.txt` | **both** | Append only; never remove another track's dep |

Staying inside your lane means you will almost never hit a merge conflict.

---

## 2. The seed-data schema — B produces, A consumes

One JSON object per line, written to `controlplane/seed/data/records.jsonl`.

```json
{
  "record_id": "customer:44219",
  "governance": "governed",
  "fields": [
    {"name": "full_name", "value": "Priya Sharma", "role": "identifier", "category": "customer_name"},
    {"name": "email",     "value": "priya.sharma@example.com", "role": "identifier", "category": "email"},
    {"name": "account",   "value": "50100234567890", "role": "operand", "category": "account_number"},
    {"name": "salary",    "value": "45230", "role": "operand", "category": "compensation"}
  ]
}
```

### Field meanings — these carry two of our drawbacks

**`role`** is `"identifier"` or `"operand"`. This is **D16** made concrete: we
substitute identifiers and never operands, so arithmetic survives (IDEATION
§9.4, *"break the linkage, preserve the arithmetic"*). The distinction is
**encoded in the data, never inferred at runtime.** If the engine has to guess,
we have already lost.

**`governance`** is `"governed"` or `"ungoverned"`. This is **D28**: the brief
assumes "a mix of well-governed and loosely governed internal data sources."
Only `governed` records go into the known-value store. `ungoverned` records
exist so we can *demonstrate* that the pattern+checksum tier is the floor under
the ungoverned half, and that coverage degrades gracefully rather than to zero.

**`category`** is a free-form string A uses to pick a placeholder prefix and to
label audit lines.

---

## 3. The engine API — A implements, B calls

Defined in `controlplane/engine/api.py`. B imports **only** from there.

```python
@dataclass(frozen=True)
class Finding:
    kind: str                    # "known_value" | "pattern"
    category: str                # "customer_name" | "api_key" | ...
    action: str                  # "substitute" | "block"
    record_ref: str | None       # "customer:44219" — the audit line (§9.2)
    placeholder: str | None      # None when action == "block"
    span: tuple[int, int]        # offsets into the ORIGINAL text
    confidence: float            # 1.0 for known-value and checksum-verified

@dataclass
class ScanResult:
    text: str                    # transformed text, safe to send upstream
    findings: list[Finding]
    mapping: dict[str, str]      # placeholder -> original. REQUEST-SCOPED ONLY
    blocked: bool
    block_reason: str | None

@dataclass
class RestoreResult:
    text: str
    restored: int                # how many placeholders were put back
    unrestored: list[str]        # placeholders we could not resolve — D15 signal

@dataclass
class RequestScope:
    assigned: dict[tuple[str, str], str]   # (category, value) -> placeholder
    counters: dict[str, int]               # next index per category
    mapping:  dict[str, str]               # cumulative for the whole request

class SubstitutionEngine:
    def __init__(self, records_path: str, config: EngineConfig | None = None): ...
    def new_request_scope(self) -> RequestScope: ...
    def scan_inbound(self, text: str, scope: RequestScope | None = None) -> ScanResult: ...
    def scan_outbound(self, text: str) -> ScanResult: ...
    def restore(self, text: str, mapping: dict[str, str]) -> RestoreResult: ...
```

### RequestScope — amendment, agreed 2026-08-30

**Pass one scope to every scan in a request.** A request is rarely one piece of
text: a system prompt, several messages, sometimes several content parts each.
Each is scanned separately, and without a shared scope every call restarts
numbering at `A` — so two different customers in one request both come back as
`[[CUST_A]]`. The provider is told they are the same person, and restoring the
merged mapping puts the wrong name back. That is a wrong-customer leak produced
by the component meant to prevent one.

```python
scope = engine.new_request_scope()
for part in request_parts:
    scanned = engine.scan_inbound(part.text, scope=scope)
    send_upstream(scanned.text)
answer = engine.restore(model_reply, scope.mapping)
```

- The scope also carries **identity**, not just numbering: Priya is
  `[[CUST_A]]` in message 1 and message 7, so relational reasoning survives
  across the conversation.
- `ScanResult.mapping` is **cumulative for the scope**, so merging each result
  as it arrives gives the same answer as reading `scope.mapping` at the end.
  Both obvious usages are correct.
- Omitting the scope is safe for a genuinely single-text request; it opens a
  throwaway one. Existing single-call code is unaffected.
- **Statelessness is unaffected** (IDEATION §3): the caller creates the scope
  and drops it when the request ends. The engine keeps no reference and holds
  no scopes of its own.

*Why this is an engine change and not a caller workaround:* the alternative was
for the gateway to concatenate the parts and scan once. That would make every
`span` refer to a joined string that was never sent, breaking rule 4 below —
so it would have worked around a gap in the contract by silently violating a
different part of it.

### Rules that are not negotiable

1. **`mapping` never leaves the request.** It is created per request, passed
   back to `restore()`, then dropped. Nothing persists it. This is IDEATION §3
   — statelessness is the whole positioning, and it is what earns us a light
   security review.
2. **`scan_inbound` never raises on bad input.** A malformed prompt returns a
   `ScanResult` with `blocked=True`, never a traceback. B's gateway must be able
   to trust that.
3. **Raw sensitive values are never logged**, by either track. Audit lines carry
   `record_ref` and already-redacted text only (IDEATION §18) — otherwise the
   compliance tool becomes the largest concentration of leaked data in the org.
4. **`span` offsets refer to the original text**, not the transformed text. B
   needs this for the audit entry.

---

## 4. The placeholder format — A decides, B must not assume

A owns the exact format and will fix it in `engine/placeholders.py` before
writing anything else. B must treat placeholders as **opaque** and only ever
match them via the helper A exposes:

```python
from controlplane.engine.placeholders import PLACEHOLDER_RE, is_placeholder
```

**Why this is a contract and not a detail:** see **D15**. If the model returns
`[CUSTOMER_A]'s` or reformats the token, naive string replacement leaves visible
artefacts on stage, in the fifteen seconds the entire pitch rests on. Whatever
format A picks has to survive inflection, possessives, casing changes, and the
model quoting it back inside code or JSON. B hardcoding `"[CUSTOMER_A]"`
anywhere would silently break that.

---

## 5. Where the two halves meet

One function, written by **B**, in `controlplane/gateway/pipeline.py`:

```
request → engine.scan_inbound(prompt)
        → if blocked: refuse at cost_usd 0.0, never dispatch   (IDEATION §8)
        → dispatch scanned.text upstream
        → engine.restore(response, scanned.mapping)
        → return to caller
```

That is the whole integration surface for Portion 1. If either track needs
anything else from the other, it is a contract change — discuss first.

---

## 6. Definition of done for Portion 1

Both tracks are done when this passes from a clean checkout:

```bash
pytest                                    # both suites green
python -m controlplane.seed.generate      # writes records.jsonl
python -m controlplane.gateway.app        # serves on :8000
python scripts/demo_roundtrip.py          # B writes this; prints the proof
```

`demo_roundtrip.py` must print, for a prompt containing a seeded customer:

- the text **as the upstream provider saw it** (placeholders only)
- the final answer returned to the caller (real values restored)
- any arithmetic in the answer, still correct

That is demo step 3 — *"the whole pitch in fifteen seconds"* — end to end.

---

## 6a. What Track B can now import

Landed since Portion 1 started. Track B does not have to use any of it to
finish P1/P13 — the Portion 1 integration is still just the four engine names
in section 3 — but it exists and is tested.

```python
from controlplane.policy.store import ControlPlane      # authoring side
from controlplane.policy.profile import Profile, PolicyError
from controlplane.audit.chain import AuditLog, record_scan, text_fingerprint
from controlplane.decision.tiers import DecisionEngine, signals_from_findings
from controlplane.feedback.session import SessionRiskTracker
from controlplane.cost.ledger import CostLedger, BudgetExceeded
from controlplane.metrics.registry import MetricsRegistry
from controlplane.stream.buffer import CommitPointBuffer
```

**For the gateway's streaming path:** wrap the upstream SSE iterator in a
`CommitPointBuffer(profile, engine.scan_outbound, restore=engine.restore,
mapping=scanned.mapping)`. Call `.feed(chunk)` per chunk and `.flush()` at
the end; each returns a list of `Release` objects to write to the client. A
`Release` with `.blocked` means stop the stream. This replaces the
"stream straight through" seam in TRACK-B.md.

`DecisionEngine.decide(signals, profile)` returns a `Decision` whose `.tier` is
one of `allow` / `annotate` / `review` / `block`, and whose `.audit_payload()`
is safe to hand straight to the audit log. When the gateway wires this in, the
pipeline's block/allow choice comes from the decision rather than from
`ScanResult.blocked` alone.

`PolicyStore.profile_for(name)` is the hot-path lookup: a dict read, no I/O,
raises `PolicyError` on an unknown name rather than falling back to something
permissive. When the gateway wires this in, `X-ControlPlane-Profile` resolves
through it instead of staying a bare string.

**Nothing in `gateway/` or `seed/` was touched.**

---

## 7. Not in Portion 1

Do not build these yet, however tempting. Each is a later portion with its own
brief: profiles/control plane (P2), commit-point buffer (P4), decision tiers
(P6), audit log (P8), feedback loop (P9), metrics (P10), cost ledger (P11),
dashboard (P12).

Leave a labelled stub where one is obviously missing — see **D23**: on a public
repo an unmarked gap reads as vapour, while
`# not implemented in Portion 1 — see BUILD-PLAN.md P8` reads as scope control.
