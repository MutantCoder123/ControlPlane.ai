"""Per-request context - TRACK B owns this.

Carries request id, key -> team, profile name, timings, token counts, findings.

Portion 1: `profile` is a PASSTHROUGH LABEL ONLY. The compiled policy
artefact, hot-swap and per-profile check selection land in P2 - see
BUILD-PLAN.md. Do not build the profile engine here.
"""

# TODO(Track B): see TRACK-B.md part 2.
