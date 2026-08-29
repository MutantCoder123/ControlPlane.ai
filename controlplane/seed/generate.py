"""Seed data generator - TRACK B owns this. Build this FIRST.

Writes seed/data/records.jsonl in the CONTRACTS.md section 2 schema.
Deterministic - fix the RNG seed so the demo reproduces from a clean checkout.
Every number we show a jury must come from this repo, not a vendor report.

D16 lives in `role`: identifier vs operand, encoded in the data, never
inferred at runtime. That is what keeps arithmetic correct through
substitution.

D28 lives in `governance`: ~70% governed (into the known-value store), ~30%
ungoverned (pattern tier only, no record_ref). The brief assumes a mix of
well- and loosely-governed sources; this is how we SHOW graceful degradation
instead of claiming it.

Include the landmine: 4111 1111 1111 1111 passes Luhn but belongs to no
record. Track A has a test asserting it does not fire.
"""

# TODO(Track B): see TRACK-B.md part 1.
