"""Traffic simulator - TRACK B owns this.

Synthetic requests across the three profiles the Round 2 brief names, at the
volume committed in IDEATION section 24.3:

  ~30,000 interactions/week (~3/min average)
  ~60% internal assistant, ~30% customer support, ~10% decision support

Portion 1 only needs a JSONL of plausible prompts - some clean, some with
seeded records, some with credentials. P10 (metrics) and P12 (dashboard)
consume it later. Keep it boring and deterministic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import random

DEFAULT_TRAFFIC_PATH = os.path.join(
    os.path.dirname(__file__), "data", "traffic.jsonl"
)

# Seeded prompt templates by profile
PROMPTS_INTERNAL = [
    "Summarize the Q3 engineering architectural review document.",
    "Draft an announcement email for the upcoming hackathon next Friday.",
    "What is the policy on remote equipment reimbursement for employee {employee_name} ({emp_id})?",
    "Calculate total annual compensation for {employee_name}: base salary {salary} plus 15% target bonus.",
    "Debug this python function that processes database connection retries.",
    "Can you review my pull request for the auth service refactor?",
    "Admin check: configure worker with token sk-proj-999888777666555444333222111 for deployment.",
]

PROMPTS_CUSTOMER = [
    "Customer {customer_name} called regarding account balance on {account_num}.",
    "Please send payment confirmation receipt to {email} for recent transaction of {balance}.",
    "Update address on file for {customer_name} (phone: {phone}).",
    "How do I reset my multi-factor authentication on mobile?",
    "What are your working hours and support channels during holidays?",
    "Check transaction history on card 4532 0151 1283 0366 for customer {customer_name}.",
    "Please cancel account for customer {customer_name} with email {email}.",
]

PROMPTS_DECISION = [
    "Evaluate loan risk score for application ref #LN-9082 based on debt-to-income ratio.",
    "Summarize market trends in enterprise cloud security for leadership briefing.",
    "Compare vendor proposals for datacenter migration focusing on cost and uptime SLA.",
    "What is the credit risk rating recommendation for customer {customer_name} with balance {balance}?",
]


def generate_synthetic_traffic(
    output_path: str = DEFAULT_TRAFFIC_PATH,
    total_samples: int = 1000,
    seed: int = 42,
) -> list[dict]:
    """Generate synthetic request traffic adhering to the 60/30/10 profile mix."""
    rng = random.Random(seed)

    # 60% internal-assistant, 30% customer-support, 10% decision-support
    num_internal = int(total_samples * 0.60)
    num_customer = int(total_samples * 0.30)
    num_decision = total_samples - num_internal - num_customer

    traffic: list[dict] = []

    def make_entry(req_id: str, profile: str, prompt: str, team: str) -> dict:
        return {
            "request_id": req_id,
            "profile": profile,
            "team": team,
            "messages": [{"role": "user", "content": prompt}],
            "model": "gpt-4o",
        }

    # Internal assistant
    for i in range(num_internal):
        tpl = rng.choice(PROMPTS_INTERNAL)
        prompt = tpl.format(
            employee_name="Alice Smith" if i % 2 == 0 else "Rohan Patel",
            emp_id="EMP-1001",
            salary="85000",
        )
        traffic.append(make_entry(f"req-int-{i:05d}", "internal-assistant", prompt, "engineering"))

    # Customer support
    for i in range(num_customer):
        tpl = rng.choice(PROMPTS_CUSTOMER)
        prompt = tpl.format(
            customer_name="Priya Sharma",
            account_num="50100234567890",
            email="priya.sharma@example.com",
            phone="9876501234",
            balance="125000",
        )
        traffic.append(make_entry(f"req-cust-{i:05d}", "customer-support", prompt, "support-tier-1"))

    # Decision support
    for i in range(num_decision):
        tpl = rng.choice(PROMPTS_DECISION)
        prompt = tpl.format(
            customer_name="Priya Sharma",
            balance="125000",
        )
        traffic.append(make_entry(f"req-dec-{i:05d}", "decision-support", prompt, "credit-risk"))

    rng.shuffle(traffic)

    # Write to target JSONL
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for t in traffic:
            f.write(json.dumps(t) + "\n")

    return traffic


if __name__ == "__main__":
    traffic = generate_synthetic_traffic()
    print(f"Generated {len(traffic)} traffic entries at {DEFAULT_TRAFFIC_PATH}")
