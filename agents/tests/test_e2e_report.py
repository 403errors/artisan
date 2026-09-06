"""Unit tests for the E2E harness's `_build_report` aggregation (no live calls — the report
builder is pure aggregation over per-scenario result dicts; the harness's own eval-marked tests
never run here)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import test_e2e_eval  # noqa: E402 — the module under test is the eval harness itself


def _scenario_result(*, n_attempts: int, pipeline_success: bool, false_green: bool = False) -> dict:
    return {
        "id": "fixture-x",
        "predicted_domains": ["backend"],
        "routing_correct": True,
        "attempts": [{"visible_passed": True, "heldout_passed": pipeline_success}]
        * n_attempts,
        "n_attempts": n_attempts,
        "verdicts": [pipeline_success] * n_attempts,
        "terminal": "pr_open" if pipeline_success or false_green else "escalated",
        "pr_opened": pipeline_success or false_green,
        "fix_correct": pipeline_success,
        "pipeline_success": pipeline_success,
        "false_green": false_green,
    }


def test_first_attempt_success_rate_counts_only_single_attempt_verified_correct():
    results = [
        _scenario_result(n_attempts=1, pipeline_success=True),  # counts
        _scenario_result(n_attempts=2, pipeline_success=True),  # retried — does not count
        _scenario_result(n_attempts=3, pipeline_success=False),  # escalated
    ]

    report, sidecar = test_e2e_eval._build_report(results)

    assert sidecar["first_attempt_success_rate"] == 1 / 3
    assert sidecar["verified_correct_rate"] == 2 / 3
    assert "First-attempt success" in report
    assert "33.3%" in report
