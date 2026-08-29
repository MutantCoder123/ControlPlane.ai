"""Where the two tracks meet - TRACK B owns this.

    request -> engine.scan_inbound(prompt)
            -> if blocked: refuse at cost_usd 0.0, NEVER dispatch
            -> dispatch scanned.text upstream
            -> engine.restore(response, scanned.mapping)
            -> return to caller

The refusal happens BEFORE dispatch on purpose (IDEATION section 8): you are
billed the moment tokens are generated, so forwarding first and cancelling on
failure means you block the request and still pay. Check first, dispatch
second.

Import ONLY the names in CONTRACTS.md section 3, plus PLACEHOLDER_RE /
is_placeholder if you need to recognise a placeholder. Never hardcode the
placeholder format - that is a live D15 bug even on the day it happens to work.

NOT in Portion 1: commit-point buffer (P4), decision tiers (P6), audit log
(P8). Stream straight through and leave the seam.
"""

# TODO(Track B): see TRACK-B.md part 2.
