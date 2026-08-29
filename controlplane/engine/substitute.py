"""SubstitutionEngine - TRACK A owns this. Assembly of the two tiers.

Implements the API in CONTRACTS.md section 3. Two rules that carry design
decisions:

1. Same entity -> same placeholder within one request, so relational
   reasoning survives substitution.
2. Never substitute operands (D16). `role` comes from the seed data, never
   inferred. Sensitivity lives in the linkage, not the value: swap the name,
   let the number through, and the arithmetic in the answer stays correct.
   "Break the linkage, preserve the arithmetic" (IDEATION section 9.4).

The identifier-is-operand case ("validate this account number's checksum")
is NOT solvable here - return the finding and let P6 route it to a human.
"""

from controlplane.engine.api import (  # noqa: F401
    EngineConfig,
    Finding,
    RestoreResult,
    ScanResult,
)


class SubstitutionEngine:
    def __init__(self, records_path: str, config: EngineConfig | None = None):
        raise NotImplementedError("Track A - see TRACK-A.md step 4")

    def scan_inbound(self, text: str) -> ScanResult:
        """Never raises on bad input - returns blocked=True instead."""
        raise NotImplementedError("Track A - see TRACK-A.md step 4")

    def scan_outbound(self, text: str) -> ScanResult:
        raise NotImplementedError("Track A - see TRACK-A.md step 4")

    def restore(self, text: str, mapping: dict) -> RestoreResult:
        raise NotImplementedError("Track A - see TRACK-A.md step 4")
