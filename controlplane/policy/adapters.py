"""Translating a compiled `Profile` into the arguments other packages take.

WHY THIS FILE IS NOT IN `engine/` OR IN `policy/profile.py`
------------------------------------------------------------
`engine/` must not import `policy/`: per-profile configuration lives in the
compiled artefact, and `EngineConfig`'s docstring has said so since Portion 1.
Equally, `policy/` should not grow knowledge of every consumer's argument
shapes. So the translation lives in one small module that both sides can
depend on without either depending on the other.

Adding a knob? Change it here and in `policy/enforcement.py` in the same
commit. That file's test fails the build if a profile field goes undeclared,
which is what stops a setting drifting back into being decorative.
"""

from __future__ import annotations

from controlplane.engine.api import ScanOptions
from controlplane.policy.profile import Profile


def inbound_options(profile: Profile) -> ScanOptions:
    """What the engine should do on the way in, for this route."""
    return ScanOptions(
        known_value_matching=profile.inbound.known_value_matching,
        substitute_pii=profile.inbound.substitute_pii,
        # Irrelevant inbound; carried so one options object can be logged.
        scan_pii=profile.outbound.scan_pii,
    )


def outbound_options(profile: Profile) -> ScanOptions:
    """What the engine should do on the way out, for this route.

    `known_value_matching` stays ON regardless of the inbound setting: the
    outbound question is "did a real value we never sent appear in the
    response", and answering it needs the record store even on a route that
    scans inbound with patterns only.
    """
    return ScanOptions(
        known_value_matching=True,
        substitute_pii=profile.inbound.substitute_pii,
        scan_pii=profile.outbound.scan_pii,
    )
