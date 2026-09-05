"""Unit tests for the pipeline-report aggregator (agents/evals/pipeline_report.py) — rendering
logic only; the aggregator itself is offline and sidecar-driven."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

from pipeline_report import build_pipeline_report  # noqa: E402

_ROUTING = {
    "n_cases": 25,
    "n_reps": 3,
    "mean_match": 0.92,
    "stability": 0.96,
    "fallback_rate": 0.111,
    "calibration": {"high": {"correct": 69, "total": 75}},
}

_EXPERT = {
    "mean_recall": 0.83,
    "mean_precision": 0.71,
    "hallucination_rate": 0.02,
    "judge_means": {"root_cause_identified": 0.9},
}

_VERIFICATION = {
    "verdict_accuracy": 0.94,
    "criteria_agreement": 0.88,
    "feedback_rate_on_red": 1.0,
}

_E2E = {
    "verified_correct_rate": 0.75,
    "false_green_rate": 0.125,
    "escalation_rate": 0.125,
    "mean_attempts": 1.6,
}


def test_full_report_renders_all_stages():
    report = build_pipeline_report(_ROUTING, _EXPERT, _VERIFICATION, _E2E)
    assert "92.0%" in report  # routing match
    assert "83.0%" in report  # expert recall
    assert "94.0%" in report  # verification agreement
    assert "**75.0%**" in report  # e2e verified-correct, bolded as the headline
    assert "high: 92.0% (69/75)" in report  # calibration bucket accuracy
    assert "not yet run" not in report


def test_missing_stages_render_as_not_run():
    report = build_pipeline_report(None, None, None, None)
    assert report.count("not yet run") == 4
    assert "The funnel" in report


def test_partial_stages_mix_run_and_missing():
    report = build_pipeline_report(_ROUTING, None, None, _E2E)
    assert "92.0%" in report
    assert "**75.0%**" in report
    assert report.count("not yet run") == 2
