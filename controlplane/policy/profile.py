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

    #: Off is legitimate for exactly one shape of route - a code assistant,
    #: where developers paste variable names that look like identifiers and
    #: placeholdering them would wreck the answer. It is NOT a general switch:
    #: turning it off ships real PII to the provider, which is the harm this
    #: product exists to prevent, so `_validate` demands a written waiver
    #: naming the reason. Credentials block either way.
    substitute_pii: bool = True
    block_credentials: bool = True
    known_value_matching: bool = True
    #: Free text, required when `substitute_pii` is false. Not decoration -
    #: it lands in the compiled artefact and therefore in the audit chain, so
    #: the decision to send real PII has an author and a stated reason.
    pii_waiver_reason: str = ""


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
class SessionPolicy:
    """Cumulative limits across a conversation or an agent run.

    Phase 7, answering the Round 2 brief directly: "multi-turn conversations
    and AI agents that take actions... introduce compounding risk, where one
    questionable output can shape several downstream decisions."

    Per-request checking stays stateless (IDEATION section 3) - these are
    CONTROL-plane budgets, enforced by counting references, never content.
    See feedback/session.py, which this section configures rather than
    duplicates: a support bot fielding hundreds of different customers and a
    decision-support tool working one case file need different cumulative
    caps, so the limit is a policy value, not a constructor argument.
    """

    #: Distinct records (by reference, e.g. "customer:44219") disclosed
    #: across one session before it is worth a human's attention, regardless
    #: of whether any single turn looked alarming on its own.
    max_records_per_session: int = 25
    #: Steps an agent may take in one run before sprawl itself is the signal,
    #: independent of what any individual step contained.
    max_agent_steps: int = 40


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
    session: SessionPolicy = field(default_factory=SessionPolicy)
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
    "session": SessionPolicy,
}

_VALID_MODES = {"interactive", "throughput"}
_VALID_AUDIT = {"standard", "full"}


def compile_profile(
    definition: dict, base: dict | None = None, jurisdiction: dict | None = None
) -> Profile:
    """Definition (plus optional base, plus optional jurisdiction floor) ->
    frozen, fingerprinted Profile.

    Every validation lives here so a malformed policy is rejected when it is
    authored rather than when a request hits it. On the hot path there is
    nothing left to check.

    `jurisdiction` is a floor, applied AFTER the profile is built and BEFORE
    validation - a profile may be stricter than its jurisdiction demands, and
    may never be looser. See `_clamp_to_floor`.
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
    profile = _clamp_to_floor(profile, jurisdiction or {})
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

    if p.session.max_records_per_session < 1:
        raise PolicyError(f"{p.name}: max_records_per_session must be positive")
    if p.session.max_agent_steps < 1:
        raise PolicyError(f"{p.name}: max_agent_steps must be positive")

    # Refusing to compile an unsafe combination is the whole point of having
    # a compiler rather than a config dict.
    if not p.inbound.block_credentials:
        raise PolicyError(
            f"{p.name}: inbound.block_credentials cannot be disabled - there is no "
            "legitimate reason to send a credential to a model (IDEATION 9.5)"
        )
    # The outbound direction was declared but never guarded - an asymmetry
    # with no argument behind it. A credential rendering to a reader's screen
    # is irreversible the moment it appears, which is if anything the harder
    # direction to undo, so it refuses on the same terms.
    if not p.outbound.block_credentials:
        raise PolicyError(
            f"{p.name}: outbound.block_credentials cannot be disabled - a credential "
            "that reaches the screen is irreversible (IDEATION 9.6)"
        )
    # Substitution may be turned off for a code-assistant route, but not
    # silently: shipping real PII to a provider is a decision that needs an
    # author. The reason travels in the artefact, so it reaches the audit
    # chain with the fingerprint that changed.
    if not p.inbound.substitute_pii and not p.inbound.pii_waiver_reason.strip():
        raise PolicyError(
            f"{p.name}: inbound.substitute_pii is false, which sends real PII to the "
            "provider. Set inbound.pii_waiver_reason to say why, in writing"
        )
    if p.outbound.cross_tenant_check and not p.outbound.scan_pii:
        raise PolicyError(
            f"{p.name}: cross_tenant_check needs outbound.scan_pii enabled to have "
            "anything to check"
        )


#: Paths where a jurisdiction sets a FLOOR rather than a default - a profile
#: may be stricter than its jurisdiction demands; it may never be looser.
#: Each entry says which direction IS stricter, so the clamp knows whether
#: the floor value wins by being the min or the max. Fields with no safety
#: direction (`cost.*`, `streaming.mode`, `description`, ...) are simply
#: absent from this table and are left to the profile entirely.
_STRICTER_MIN_MAX = {
    ("decision", "block_at"): min,                # lower blocks earlier
    ("decision", "flag_budget_per_100"): max,      # higher = fewer flags suppressed
    ("quality", "hallucination_tier"): max,        # higher tier = more checking
    ("streaming", "overlap_chars"): max,           # higher = more held back (D5)
    ("session", "max_records_per_session"): min,   # lower cap = tighter (D4)
    ("session", "max_agent_steps"): min,           # lower cap = tighter (D4)
}

#: Booleans where "on" is the stricter state - a floor can only turn these
#: on, never off (logical OR), regardless of what the profile asked for.
_STRICTER_TRUE = {
    ("decision", "always_review"),
    ("outbound", "scan_pii"),
    ("outbound", "cross_tenant_check"),
}

_AUDIT_RANK = {"standard": 0, "full": 1}


def _clamp_to_floor(profile: "Profile", floor: dict) -> "Profile":
    """A jurisdiction sets a FLOOR. A profile may be stricter; never looser.

    Getting this backwards - letting a profile freely override a
    jurisdiction's requirement - is how a governance product lets a team
    quietly opt out of the law by editing their own config. So the direction
    is enforced here, in the compiler, not merely documented.

    This CLAMPS; it does not refuse. A profile asking for something looser
    than its jurisdiction allows is not an authoring error the way exempting
    a credential is (`_validate` refuses that outright) - it is simply
    overridden, and `Profile.diff()` against the unclamped compile shows
    exactly which values the floor moved (see demo/server.py's jurisdiction
    routes). Silent enforcement, visible in the diff, is the honest version
    of "the law does not ask your permission."
    """
    if not floor:
        return profile

    sections = {
        "inbound": profile.inbound,
        "outbound": profile.outbound,
        "streaming": profile.streaming,
        "decision": profile.decision,
        "quality": profile.quality,
        "cost": profile.cost,
        "session": profile.session,
    }
    changed: dict[str, object] = {}

    for section_name, section_obj in sections.items():
        floor_section = floor.get(section_name)
        if not floor_section:
            continue
        updates: dict = {}
        for key, floor_value in floor_section.items():
            current = getattr(section_obj, key, None)
            if current is None:
                continue  # the floor names a key this section doesn't have
            picker = _STRICTER_MIN_MAX.get((section_name, key))
            if picker is not None:
                clamped = picker(current, floor_value)
            elif (section_name, key) in _STRICTER_TRUE:
                clamped = bool(current) or bool(floor_value)
            else:
                continue  # no safety direction for this field - profile's own value stands
            if clamped != current:
                updates[key] = clamped
        if updates:
            changed[section_name] = replace(section_obj, **updates)

    audit_floor = floor.get("audit_level")
    new_audit_level = profile.audit_level
    if audit_floor and _AUDIT_RANK.get(audit_floor, 0) > _AUDIT_RANK.get(profile.audit_level, 0):
        new_audit_level = audit_floor

    if not changed and new_audit_level == profile.audit_level:
        return profile

    profile = replace(profile, audit_level=new_audit_level, **changed)

    # Derived fix: a clamped block_at can leave review_band's top edge above
    # the new block threshold - dead space no signal can ever land in.
    if "decision" in changed:
        low, high = profile.decision.review_band
        new_high = min(high, profile.decision.block_at)
        if new_high != high:
            profile = replace(
                profile, decision=replace(profile.decision, review_band=(low, new_high))
            )

    return profile


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
