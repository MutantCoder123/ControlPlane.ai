"""Tests for Traffic Simulator (P13 / B3).

Verifies traffic volume, profile mix proportions (60/30/10), and entry formats.
"""

from __future__ import annotations

from controlplane.seed.traffic import generate_synthetic_traffic


def test_mix_within_tolerance():
    total = 1000
    traffic = generate_synthetic_traffic(total_samples=total, seed=42)
    assert len(traffic) == total

    internal_count = sum(1 for t in traffic if t["profile"] == "internal-assistant")
    customer_count = sum(1 for t in traffic if t["profile"] == "customer-support")
    decision_count = sum(1 for t in traffic if t["profile"] == "decision-support")

    assert internal_count == 600
    assert customer_count == 300
    assert decision_count == 100

    # Proportions
    assert internal_count / total == 0.60
    assert customer_count / total == 0.30
    assert decision_count / total == 0.10


def test_traffic_entries_valid():
    traffic = generate_synthetic_traffic(total_samples=50, seed=42)
    for entry in traffic:
        assert "request_id" in entry
        assert entry["profile"] in ("internal-assistant", "customer-support", "decision-support")
        assert "team" in entry
        assert "messages" in entry
        assert len(entry["messages"]) > 0
        assert "role" in entry["messages"][0]
        assert "content" in entry["messages"][0]
