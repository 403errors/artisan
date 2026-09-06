"""Unit tests for the routing eval's report builder (agents/evals/test_routing_eval.py) —
canonical stability, boundary/omission slices, and dual calibration are pure report logic, so
they get CI-covered tests here with fabricated decisions (the harness itself is live-only)."""

import sys
from pathlib import Path

import pytest
from artisan_shared.models import RoutingDecision

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

from test_routing_eval import _build_report


def _decision(*domains: str, confidence: str = "high") -> RoutingDecision:
    return RoutingDecision(domains=list(domains), parallel=len(domains) > 1, confidence=confidence)


def test_stability_uses_canonical_sets_fallback_synonym_drift_is_stable():
    # The recorded 2026-09-06 run's one unstable case: blockchain vs smart-contracts across reps.
    cases = [{"id": "c1", "expect_fallback": True}]
    results = {
        "c1": [_decision("blockchain"), _decision("smart-contracts"), _decision("blockchain")]
    }
    _, sidecar = _build_report(cases, results)
    (case,) = sidecar["per_case"]
    assert case["stable"] is True
    assert case["consensus"] == "fallback"
    assert case["consensus_passes"] is True
    assert case["derived_confidence"] == "high"
    # Raw labels stay on the record for audit.
    assert case["predicted_reps"] == ["blockchain", "smart-contracts", "blockchain"]
    assert sidecar["stability"] == 1.0


def test_registry_label_drift_is_unstable():
    cases = [{"id": "c1", "expected": ["backend"]}]
    results = {"c1": [_decision("backend"), _decision("frontend"), _decision("backend")]}
    _, sidecar = _build_report(cases, results)
    (case,) = sidecar["per_case"]
    assert case["stable"] is False
    assert case["derived_confidence"] == "medium"
    assert sidecar["stability"] == 0.0


def test_boundary_slice_tracks_tagged_cases_separately():
    cases = [
        {"id": "seam", "expected": ["security"], "boundary": True},
        {"id": "plain", "expected": ["frontend"]},
    ]
    results = {
        "seam": [_decision("security")] * 3,
        "plain": [_decision("backend")] * 3,  # wrong on every rep
    }
    _, sidecar = _build_report(cases, results)
    assert sidecar["boundary_match"] == 1.0
    assert sidecar["mean_match"] == 0.5


def test_omission_rate_counts_dropped_sibling_domains_per_rep():
    cases = [
        {"id": "multi", "expected": ["backend", "database"]},
        {"id": "single", "expected": ["backend"]},
    ]
    results = {
        "multi": [_decision("backend", "database"), _decision("backend"), _decision("backend")],
        "single": [_decision("backend")] * 3,
    }
    _, sidecar = _build_report(cases, results)
    assert sidecar["omission_rate"] == pytest.approx(2 / 3)


def test_omission_and_boundary_are_none_without_matching_cases():
    cases = [{"id": "single", "expected": ["backend"]}]
    _, sidecar = _build_report(cases, {"single": [_decision("backend")] * 3})
    assert sidecar["omission_rate"] is None
    assert sidecar["boundary_match"] is None


def test_derived_calibration_buckets_consensus_correctness():
    cases = [
        {"id": "unanimous-right", "expected": ["backend"]},
        {"id": "split-wrong", "expected": ["security"]},
    ]
    results = {
        "unanimous-right": [_decision("backend")] * 3,
        "split-wrong": [_decision("backend"), _decision("frontend"), _decision("database")],
    }
    report, sidecar = _build_report(cases, results)
    assert sidecar["derived_calibration"] == {
        "high": {"correct": 1, "total": 1},
        "low": {"correct": 0, "total": 1},
    }
    assert "## Derived-confidence calibration" in report
    # The self-reported table stays for contrast — still all-"high" regardless of correctness.
    assert sidecar["calibration"] == {"high": {"correct": 3, "total": 6}}
