"""Route profiles - the compiled policy artefact.

D20. IDEATION section 16 claims a data-plane / control-plane split, which is
what earns the product its name, but nothing was ever actually authored
centrally and pushed. This module is that artefact.

THE IDEA (IDEATION section 5.2): the use case is the policy unit. There is no
single correct configuration of this gateway, and pretending otherwise is how
governance products become unusable. A customer support bot, an internal
knowledge assistant and a decision-support tool have different risk
tolerances and different latency budgets - the Round 2 brief opens by saying
exactly that - so each compiles to a named profile.

THE SPLIT
---------
- The CONTROL PLANE authors definitions, validates them, resolves
  inheritance, and compiles a frozen artefact with a version fingerprint.
- The DATA PLANE holds that artefact in memory and reads it on the hot path.
  It makes ZERO network calls to decide anything (IDEATION section 16).

So everything expensive happens once, at compile time, and the checkpoint
stays deliberately dumb and fast.

D6 is settled here too: `streaming.mode` makes buffering a per-profile
property rather than a global one. "Racing the reader" only works where there
is a reader, and a batch profile has none.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace


class PolicyError(ValueError):
    """A profile definition that cannot be compiled.

    Raised at compile time, in the control plane, never on the hot path -
    a bad policy must fail when it is authored, not when a request arrives.
    """


@dataclass(frozen=True)
class InboundPolicy:
    """Protecting the organisation from its own paste habit."""

    substitute_pii: bool = True
    block_credentials: bool = True
    #: Substitution off is legitimate for code assistants: developers paste
    #: variable names that look like identifiers, and placeholdering them
    #: would wreck the answer. Credentials still block.
    known_value_matching: bool = True


@dataclass(frozen=True)
class OutboundPolicy:
    """The asymmetry (IDEATION section 9.6): inbound substitutes, outbound blocks.

    Outbound volume is lower, so it can afford more scrutiny, and the harm is
    different - here the risk is a reader seeing what they are not cleared
    for, or a live credential rendering to screen.
    """

    block_credentials: bool = True
    scan_pii: bool = False
    #: Family A inverts the asymmetry (D21): in a customer-facing bot the
    #: catastrophic direction is outbound, customer X shown customer Y.
    cross_tenant_check: bool = False


@dataclass(frozen=True)
class StreamingPolicy:
    """D6 - buffering is a profile property, not a global one."""

    mode: str = "interactive"      # "interactive" | "throughput"
    commit_tokens: int = 40
    commit_ms: int = 250
    overlap_chars: int = 50

    @property
    def buffered(self) -> bool:
        return self.mode == "interactive"


@dataclass(frozen=True)
class DecisionPolicy:
    """Tier thresholds (IDEATION section 12). Consumed by P6.

    The tier is a function of severity x confidence x profile - never the
    finding alone - which is what makes profiles load-bearing rather than
    decorative.
    """

    block_at: float = 0.90
    review_band: tuple[float, float] = (0.50, 0.90)
    #: Alert fatigue is tuned, not solved (IDEATION section 12.3). The
    #: customer owns their own tolerance, so it is a policy value.
    flag_budget_per_100: int = 10
    #: person-decision routes everything to a human regardless of confidence,
    #: because the legal exposure justifies the cost.
    always_review: bool = False
    #: Values a reviewer has judged not worth flagging here. This is what the
    #: feedback loop writes to (IDEATION section 13.3): we tune thresholds and
    #: exception lists, never model weights, because a customer must be able
    #: to read the diff and see why a decision changed. Matched against a
    #: finding's category, its record_ref, or "kind:category".
    exempt: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityPolicy:
    """Reversible harms - annotated after release, not blocked before."""

    hallucination_tier: int = 0     # 0 free signals, 1 narrow re-ask, 2 shape-specific
    toxicity_sync: bool = False
    counterfactual_sample_rate: float = 0.0


@dataclass(frozen=True)
class CostPolicy:
    cache_enabled: bool = False
    max_output_tokens: int = 1024
    request_budget_usd: float = 0.50


@dataclass(frozen=True)
class Profile:
    """One compiled route profile. Immutable by construction.

    `fingerprint` is the content hash. Two checkpoints holding the same
    fingerprint are provably running the same policy, which is the question
    an auditor actually asks.
    """

    name: str
    description: str = ""
    geography: str = "IN"           # brief: policy varies by geography
    inbound: InboundPolicy = field(default_factory=InboundPolicy)
    outbound: OutboundPolicy = field(default_factory=OutboundPolicy)
    streaming: StreamingPolicy = field(default_factory=StreamingPolicy)
    decision: DecisionPolicy = field(default_factory=DecisionPolicy)
    quality: QualityPolicy = field(default_factory=QualityPolicy)
    cost: CostPolicy = field(default_factory=CostPolicy)
    audit_level: str = "standard"   # "standard" | "full"
    fingerprint: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("fingerprint", None)
        data["streaming"]["mode"] = self.streaming.mode
        data["decision"]["review_band"] = list(self.decision.review_band)
        data["decision"]["exempt"] = list(self.decision.exempt)
        return data

    def with_fingerprint(self) -> "Profile":
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return replace(self, fingerprint=digest)

    def diff(self, other: "Profile") -> dict[str, tuple]:
        """What changed between two versions, as a flat path -> (old, new) map.

        A customer must be able to read why a decision changed (IDEATION
        section 13.3). "The model learned" is not an answer a regulator
        accepts; a diff is.
        """
        return _diff(other.to_dict(), self.to_dict())


def _diff(old: dict, new: dict, prefix: str = "") -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    for key in sorted(set(old) | set(new)):
        path = f"{prefix}{key}"
        a, b = old.get(key), new.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            out.update(_diff(a, b, f"{path}."))
        elif a != b:
            out[path] = (a, b)
    return out


# --------------------------------------------------------------------------
# Compilation - the control plane's job
# --------------------------------------------------------------------------

_SECTIONS = {
    "inbound": InboundPolicy,
    "outbound": OutboundPolicy,
    "streaming": StreamingPolicy,
    "decision": DecisionPolicy,
    "quality": QualityPolicy,
    "cost": CostPolicy,
}

_VALID_MODES = {"interactive", "throughput"}
_VALID_AUDIT = {"standard", "full"}


def compile_profile(definition: dict, base: dict | None = None) -> Profile:
    """Definition (plus optional base) -> frozen, fingerprinted Profile.

    Every validation lives here so a malformed policy is rejected when it is
    authored rather than when a request hits it. On the hot path there is
    nothing left to check.
    """
    merged = _merge(base or {}, definition)

    name = merged.get("name")
    if not name or not isinstance(name, str):
        raise PolicyError("profile needs a name")

    kwargs: dict = {
        "name": name,
        "description": merged.get("description", ""),
        "geography": merged.get("geography", "IN"),
        "audit_level": merged.get("audit_level", "standard"),
    }

    if kwargs["audit_level"] not in _VALID_AUDIT:
        raise PolicyError(f"{name}: audit_level must be one of {sorted(_VALID_AUDIT)}")

    for section, cls in _SECTIONS.items():
        payload = merged.get(section, {})
        if not isinstance(payload, dict):
            raise PolicyError(f"{name}: section '{section}' must be an object")
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = set(payload) - allowed
        if unknown:
            # A typo in a policy file is a silent security downgrade if we
            # ignore it - "block_credential: true" would simply not apply.
            raise PolicyError(f"{name}.{section}: unknown keys {sorted(unknown)}")
        if section == "decision":
            payload = dict(payload)
            if "review_band" in payload:
                payload["review_band"] = tuple(payload["review_band"])
            if "exempt" in payload:
                # Sorted so the fingerprint is stable regardless of the order
                # a reviewer happened to add exemptions in.
                payload["exempt"] = tuple(sorted(payload["exempt"]))
        kwargs[section] = cls(**payload)

    profile = Profile(**kwargs)
    _validate(profile)
    return profile.with_fingerprint()


def _validate(p: Profile) -> None:
    if p.streaming.mode not in _VALID_MODES:
        raise PolicyError(f"{p.name}: streaming.mode must be one of {sorted(_VALID_MODES)}")
    if p.streaming.overlap_chars < 0:
        raise PolicyError(f"{p.name}: overlap_chars cannot be negative")
    if p.streaming.buffered and p.streaming.commit_tokens < 1:
        raise PolicyError(f"{p.name}: an interactive profile needs commit_tokens >= 1")

    low, high = p.decision.review_band
    if not 0.0 <= low <= high <= 1.0:
        raise PolicyError(f"{p.name}: review_band must satisfy 0 <= low <= high <= 1")
    if not 0.0 <= p.decision.block_at <= 1.0:
        raise PolicyError(f"{p.name}: block_at must be between 0 and 1")
    if p.decision.flag_budget_per_100 < 0:
        raise PolicyError(f"{p.name}: flag budget cannot be negative")
    if any(not isinstance(e, str) or not e for e in p.decision.exempt):
        raise PolicyError(f"{p.name}: exemptions must be non-empty strings")
    # An exemption is a deliberate hole in the detector. Letting one apply to
    # credentials would let a reviewer switch off the one check that guards
    # against irreversible harm, one override at a time.
    banned = {"api_key", "jwt", "private_key"}
    if banned & {e.split(":")[-1] for e in p.decision.exempt}:
        raise PolicyError(
            f"{p.name}: credentials cannot be exempted - blocking them is not "
            "a tunable (IDEATION 9.5)"
        )

    if p.quality.hallucination_tier not in (0, 1, 2):
        raise PolicyError(f"{p.name}: hallucination_tier must be 0, 1 or 2")
    if not 0.0 <= p.quality.counterfactual_sample_rate <= 1.0:
        raise PolicyError(f"{p.name}: counterfactual_sample_rate must be between 0 and 1")

    if p.cost.max_output_tokens < 1:
        raise PolicyError(f"{p.name}: max_output_tokens must be positive")

    # Refusing to compile an unsafe combination is the whole point of having
    # a compiler rather than a config dict.
    if not p.inbound.block_credentials:
        raise PolicyError(
            f"{p.name}: inbound.block_credentials cannot be disabled - there is no "
            "legitimate reason to send a credential to a model (IDEATION 9.5)"
        )
    if p.outbound.cross_tenant_check and not p.outbound.scan_pii:
        raise PolicyError(
            f"{p.name}: cross_tenant_check needs outbound.scan_pii enabled to have "
            "anything to check"
        )


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
