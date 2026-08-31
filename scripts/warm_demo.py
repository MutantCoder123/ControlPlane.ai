"""Put the demo server into the state beat 7 of the video needs.

WHY THIS EXISTS
---------------
The review queue fills from the *reversible* half of the pipeline - a
hallucination finding on a route whose profile reviews every response - and
the policy tuner will not propose a change until it has seen MIN_EVIDENCE
independent reviews. So a cold server has an empty queue and a beat with
nothing in it.

Three real requests fix that. Nothing here is faked: each one goes through the
same pipeline the dashboard shows, against the same local model, and the queue
items it produces carry real confidences and real timestamps. A production
review queue has a backlog for exactly this reason.

Run it after starting the demo server and before recording:

    python -m controlplane.demo.server      # window 1
    python scripts/warm_demo.py             # window 2, once

Restarting the demo server clears everything, so this is also the reset
between takes. See DEMO-SCRIPT.md.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

#: The decision-support route is EU AI Act high-risk in our profile set, so it
#: reviews every response. That is what puts these in the queue - not low
#: confidence, but the legal exposure of decisions about a person.
PROFILE = "decision-support"
RUNS = 3

PROMPT = (
    "Rewrite the notes below as a short customer email. Do not add any facts "
    "that are not in the notes.\n\n"
    "Notes:\n"
    "- Customer: Priya Sharma\n"
    "- Account balance: 45230 rupees\n"
    "- Refund approved: 12 percent of the balance\n\n"
    "Email:"
)


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read())


def _run_once(index: int) -> int:
    """One request through the real pipeline. Returns items queued."""
    request = urllib.request.Request(
        BASE + "/demo/run",
        data=json.dumps({"prompt": PROMPT, "profile": PROFILE}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    queued = 0
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw in response:
            if not raw.startswith(b"data:"):
                continue
            event = json.loads(raw[5:])
            if event["stage"] == "queue.enqueue":
                queued += 1
            elif event["stage"] == "error":
                print(f"  run {index}: {event['reason']}", file=sys.stderr)
    return queued


def main() -> int:
    try:
        health = _get("/demo/health")
    except urllib.error.URLError:
        print(
            "The demo server is not answering on " + BASE + ".\n"
            "Start it first:  python -m controlplane.demo.server",
            file=sys.stderr,
        )
        return 1

    if not health["ok"]:
        print(
            f"The local model is not reachable: {health['model']['detail']}\n"
            "Start it with `ollama serve`, then `ollama pull llama3.2:1b`.",
            file=sys.stderr,
        )
        return 1

    print(f"model {health['model']['name']} reachable, policy v{health['policy_version']}")
    print(f"warming the review queue with {RUNS} real requests on {PROFILE}...")

    total = 0
    for i in range(1, RUNS + 1):
        queued = _run_once(i)
        total += queued
        print(f"  run {i}/{RUNS}: {queued} item(s) queued")

    pending = len(_get("/demo/queue")["pending"])
    chain_ok = _get("/demo/audit")["length"]

    print()
    print(f"review queue : {pending} pending")
    print(f"audit chain  : {chain_ok} entries")
    print()

    if pending < 3:
        # The tuner needs three independent reviews before it proposes
        # anything, so beat 7 would show a queue and no policy change.
        print(
            f"WARNING: only {pending} pending, and the policy tuner needs 3 before it\n"
            "will propose a change. Run this again, or expect beat 7 to stop at the\n"
            "queue rather than reaching the policy diff.",
            file=sys.stderr,
        )
        return 1

    print("Ready to record. Checklist:")
    print("  - dashboard at http://localhost:3000, model dot green")
    print("  - /queue shows 3 pending")
    print("  - /verify verifies (do not tamper until beat 8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
