"""Tests for Seed Generator (P13 / B1).

Verifies determinism, schema adherence (CONTRACTS §2), and ~70/30 governance split (D28).
"""

from __future__ import annotations

import os
import tempfile
from controlplane.seed.generate import DEFAULT_DATA_PATH, generate_seed_records


def test_deterministic_across_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = os.path.join(tmpdir, "run1.jsonl")
        path2 = os.path.join(tmpdir, "run2.jsonl")

        r1 = generate_seed_records(output_path=path1, num_customers=50, num_employees=20, seed=42)
        r2 = generate_seed_records(output_path=path2, num_customers=50, num_employees=20, seed=42)

        assert len(r1) == len(r2)
        assert r1 == r2

        with open(path1, "r", encoding="utf-8") as f1, open(path2, "r", encoding="utf-8") as f2:
            assert f1.read() == f2.read()


def test_governance_split_is_roughly_70_30():
    records = generate_seed_records(num_customers=200, num_employees=50, seed=42)
    assert len(records) == 250

    governed = sum(1 for r in records if r["governance"] == "governed")
    ungoverned = sum(1 for r in records if r["governance"] == "ungoverned")

    governed_pct = (governed / len(records)) * 100
    assert 65.0 <= governed_pct <= 75.0
    assert governed + ungoverned == len(records)


def test_schema_conformity():
    records = generate_seed_records(num_customers=20, num_employees=5, seed=42)
    for r in records:
        assert "record_id" in r
        assert r["governance"] in ("governed", "ungoverned")
        assert "fields" in r
        assert isinstance(r["fields"], list)
        for f in r["fields"]:
            assert "name" in f
            assert "value" in f
            assert f["role"] in ("identifier", "operand")
            assert "category" in f


def test_anchor_customer_priya_sharma_present():
    records = generate_seed_records(seed=42)
    priya = next((r for r in records if r["record_id"] == "customer:44219"), None)
    assert priya is not None
    assert priya["governance"] == "governed"
    name_field = next(f for f in priya["fields"] if f["name"] == "full_name")
    assert name_field["value"] == "Priya Sharma"
    assert name_field["role"] == "identifier"
