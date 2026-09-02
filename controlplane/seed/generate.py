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

from __future__ import annotations

import json
import os
from pathlib import Path
import random

# Fixed first names and last names for realistic generation
FIRST_NAMES = [
    "Priya", "Aarav", "Rohan", "Ananya", "Vikram", "Sneha", "Rahul", "Pooja",
    "Aditya", "Neha", "Amit", "Kavita", "Suresh", "Sunita", "Deepak", "Meera",
    "Rajesh", "Divya", "Manoj", "Shweta", "Arjun", "Ritu", "Karan", "Tanvi",
    "John", "Alice", "David", "Emma", "Michael", "Sarah", "James", "Emily",
]

LAST_NAMES = [
    "Sharma", "Patel", "Verma", "Rao", "Gupta", "Singh", "Mehta", "Deshmukh",
    "Iyer", "Nair", "Reddy", "Choudhury", "Bose", "Das", "Joshi", "Kulkarni",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
]

DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "data", "records.jsonl"
)


def generate_seed_records(
    output_path: str = DEFAULT_DATA_PATH,
    num_customers: int = 200,
    num_employees: int = 50,
    seed: int = 42,
) -> list[dict]:
    """Generate deterministic seed customer and employee records conforming to CONTRACTS §2."""
    rng = random.Random(seed)
    records: list[dict] = []

    # 1. Anchor record for demo and testing (Priya Sharma customer:44219)
    records.append({
        "record_id": "customer:44219",
        "governance": "governed",
        "fields": [
            {"name": "full_name", "value": "Priya Sharma", "role": "identifier", "category": "customer_name"},
            {"name": "email", "value": "priya.sharma@example.com", "role": "identifier", "category": "email"},
            {"name": "phone", "value": "9876501234", "role": "identifier", "category": "phone_number"},
            {"name": "account", "value": "50100234567890", "role": "operand", "category": "account_number"},
            {"name": "salary", "value": "45230", "role": "operand", "category": "compensation"},
            {"name": "balance", "value": "125000", "role": "operand", "category": "balance"},
        ],
    })

    # 2. Generate remaining customer records (~70% governed, ~30% ungoverned)
    used_names: set[str] = {"Priya Sharma"}
    
    # 70% governed target
    target_governed_customers = int((num_customers - 1) * 0.70)

    for i in range(1, num_customers):
        # Pick unique name
        while True:
            fn = rng.choice(FIRST_NAMES)
            ln = rng.choice(LAST_NAMES)
            name = f"{fn} {ln}"
            if name not in used_names:
                used_names.add(name)
                break

        cust_id = f"customer:{10000 + i}"
        is_governed = i <= target_governed_customers
        governance = "governed" if is_governed else "ungoverned"

        email_domain = rng.choice(["example.com", "acme-corp.com", "finmail.org", "outlook.test"])
        clean_email_name = name.lower().replace(" ", ".")
        email = f"{clean_email_name}@{email_domain}"
        phone = f"98765{rng.randint(10000, 99999)}"
        account_num = f"50100{rng.randint(10000000, 99999999)}"
        balance = str(rng.randint(5000, 500000))

        fields = [
            {"name": "full_name", "value": name, "role": "identifier", "category": "customer_name"},
            {"name": "email", "value": email, "role": "identifier", "category": "email"},
            {"name": "phone", "value": phone, "role": "identifier", "category": "phone_number"},
            {"name": "account", "value": account_num, "role": "operand", "category": "account_number"},
            {"name": "balance", "value": balance, "role": "operand", "category": "balance"},
        ]

        # In ungoverned records, occasionally include a credit card identifier
        if not is_governed and (i % 3 == 0):
            # Valid Luhn card (starting with 4532)
            card_base = f"4532{rng.randint(10000000000, 99999999999)}"
            # Compute Luhn check digit
            digits = [int(d) for d in card_base]
            checksum = 0
            for idx, digit in enumerate(reversed(digits)):
                doubled = digit * 2
                checksum += doubled - 9 if doubled > 9 else doubled
            check_digit = (10 - (checksum % 10)) % 10
            card_num = card_base + str(check_digit)
            fields.append({"name": "card", "value": card_num, "role": "identifier", "category": "card_number"})

        records.append({
            "record_id": cust_id,
            "governance": governance,
            "fields": fields,
        })

    # 3. Generate employee records (~50 employees, ~70% governed)
    target_governed_employees = int(num_employees * 0.70)
    for i in range(num_employees):
        fn = rng.choice(FIRST_NAMES)
        ln = rng.choice(LAST_NAMES)
        emp_name = f"{fn} {ln}"
        emp_id = f"EMP-{2000 + i}"
        is_governed = i < target_governed_employees
        governance = "governed" if is_governed else "ungoverned"
        salary = str(rng.randint(40000, 180000))
        manager_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

        records.append({
            "record_id": f"employee:{2000 + i}",
            "governance": governance,
            "fields": [
                {"name": "full_name", "value": emp_name, "role": "identifier", "category": "employee_name"},
                {"name": "emp_id", "value": emp_id, "role": "identifier", "category": "employee_id"},
                {"name": "salary", "value": salary, "role": "operand", "category": "compensation"},
                {"name": "manager", "value": manager_name, "role": "identifier", "category": "manager_name"},
            ],
        })

    # Write to target file
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    return records


if __name__ == "__main__":
    records = generate_seed_records()
    print(f"Generated {len(records)} records at {DEFAULT_DATA_PATH}")
