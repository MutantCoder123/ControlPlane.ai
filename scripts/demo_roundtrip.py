"""The Portion 1 acceptance artefact - TRACK B owns this.

For a prompt containing a seeded customer, print:
  1. the prompt AS THE UPSTREAM PROVIDER SAW IT   (placeholders only)
  2. the final answer returned to the caller       (real values restored)
  3. any arithmetic in the answer, still correct

That is demo step 3 - "the whole pitch in fifteen seconds" - proved from a
terminal. See CONTRACTS.md section 6.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controlplane.engine.placeholders import find_placeholders
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.gateway.context import create_request_context
from controlplane.gateway.pipeline import GatewayPipeline
from controlplane.gateway.upstream import FakeUpstreamClient
from controlplane.seed.generate import DEFAULT_DATA_PATH, generate_seed_records


def _placeholder_for(scan_res, category: str) -> str:
    """The placeholder the engine actually minted for one category."""
    for finding in scan_res.findings:
        if finding.category == category and finding.placeholder:
            return finding.placeholder
    raise SystemExit(
        f"demo precondition failed: nothing was substituted for {category!r}. "
        "Check the seed record is governed and the field is an identifier."
    )


async def run_demo():
    print("=" * 80)
    print("ControlPlane.ai — Portion 1 Acceptance Proof (Demo Step 3)")
    print("Fifteen-second spine: Known-value substitution round-trip with intact arithmetic")
    print("=" * 80)

    # Ensure seed records exist
    if not os.path.exists(DEFAULT_DATA_PATH):
        print(f"Generating deterministic seed records at {DEFAULT_DATA_PATH}...")
        generate_seed_records(DEFAULT_DATA_PATH)

    engine = SubstitutionEngine(DEFAULT_DATA_PATH)

    # 1. Original User Prompt containing governed customer + operands
    user_prompt = (
        "Customer Priya Sharma (email: priya.sharma@example.com) requests a summary. "
        "Her current balance is 125000 and base salary is 45230. "
        "Calculate the total combined financial assets (balance + salary)."
    )

    print("\n[ORIGINAL INPUT PROMPT]")
    print(f"  \"{user_prompt}\"")

    # Step 1: Scan inbound & show upstream view
    scan_res = engine.scan_inbound(user_prompt)
    print("\n" + "-" * 80)
    print("1. PROMPT AS THE UPSTREAM PROVIDER SAW IT (Zero sensitive PII sent):")
    print("-" * 80)
    print(f"  \"{scan_res.text}\"")
    print(f"\n  [Findings: {len(scan_res.findings)} governed entities detected]")
    for f in scan_res.findings:
        print(f"    - {f.category} ({f.record_ref}) -> replaced with {f.placeholder} [Confidence: {f.confidence}]")

    # Simulate upstream LLM computing on the placeholders and numbers
    # 125000 + 45230 = 170230
    # Placeholders come from the scan we just ran, never typed in: Track A owns
    # the format and may change it (CONTRACTS.md section 4), and a literal here
    # would make this script "prove" a round trip against a token the engine
    # never minted.
    name_ph = _placeholder_for(scan_res, "customer_name")
    email_ph = _placeholder_for(scan_res, "email")

    simulated_upstream_response = (
        f"Based on our records, {name_ph} ({email_ph}) has a total combined asset "
        f"value of 125000 + 45230 = 170230. All accounts for {name_ph}'s profile "
        "are in good standing."
    )

    fake_upstream = FakeUpstreamClient(canned_response_text=simulated_upstream_response)
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)
    ctx = create_request_context(headers={"X-ControlPlane-Profile": "customer-support"})

    # Execute through pipeline
    result = await pipeline.execute_chat(
        messages=[{"role": "user", "content": user_prompt}],
        context=ctx,
        model="gpt-4o",
        stream=False,
    )

    final_answer = result["choices"][0]["message"]["content"]

    print("\n" + "-" * 80)
    print("2. FINAL ANSWER RETURNED TO CALLER (Real values restored in-flight):")
    print("-" * 80)
    print(f"  \"{final_answer}\"")

    print("\n" + "-" * 80)
    print("3. ARITHMETIC VERIFICATION (Break the linkage, preserve the arithmetic - D16):")
    print("-" * 80)
    # Check if calculation 170230 is present and accurate
    expected_sum = 125000 + 45230  # 170230
    has_correct_sum = str(expected_sum) in final_answer
    has_customer_name = "Priya Sharma" in final_answer
    has_customer_email = "priya.sharma@example.com" in final_answer
    # Any placeholder-shaped token still in the answer is a D15 failure.
    # PLACEHOLDER_RE is exactly the alarm for this - use it, do not guess.
    no_placeholders = not find_placeholders(final_answer)

    possessive_pass = "Priya Sharma's" in final_answer
    print(f"  - Customer Name Restored:    {'PASS' if has_customer_name else 'FAIL'}")
    print(f"  - Customer Email Restored:   {'PASS' if has_customer_email else 'FAIL'}")
    print(f"  - Possessive Form Restored:  {'PASS' if possessive_pass else 'FAIL'}")
    print(f"  - Zero Leaked Placeholders:  {'PASS' if no_placeholders else 'FAIL'}")
    print(f"  - Correct Arithmetic (170230): {'PASS' if has_correct_sum else 'FAIL'}")


    checks = {
        "customer name restored": has_customer_name,
        "customer email restored": has_customer_email,
        "possessive form restored": possessive_pass,
        "zero leaked placeholders": no_placeholders,
        "arithmetic correct (170230)": has_correct_sum,
    }
    failed = [name for name, ok in checks.items() if not ok]

    print()
    print("=" * 80)
    if failed:
        # This is the CONTRACTS.md section 6 acceptance artefact. It used to
        # print SUCCESSFUL unconditionally and exit 0, so it could not fail -
        # and an acceptance check that cannot fail is decoration.
        print("RESULT: Portion 1 acceptance verification FAILED.")
        for name in failed:
            print(f"  - {name}")
        print("=" * 80)
        raise SystemExit(1)

    print("RESULT: Portion 1 acceptance verification SUCCESSFUL.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_demo())
