"""Unit tests for bench_report.py — grading import normalization + report rendering."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals" / "bench"))

import bench_report


def test_import_grading_from_swebench_log_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_report, "RUNS_DIR", tmp_path)
    logs = tmp_path / "logs" / "run_evaluation" / "artisan-v2"
    for iid, resolved in (("a__x-1", True), ("b__y-2", False)):
        d = logs / "test" / iid
        d.mkdir(parents=True)
        (d / "report.json").write_text(json.dumps({"instance_id": iid, "resolved": resolved}))

    grading = bench_report.import_grading("swebench-verified", logs)
    assert grading == {"a__x-1": True, "b__y-2": False}
    assert json.loads((tmp_path / "swebench-verified" / "grading.json").read_text()) == grading


def test_import_grading_from_flat_json(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_report, "RUNS_DIR", tmp_path)
    src = tmp_path / "results.json"
    src.write_text(json.dumps({"a__x-1": True, "b__y-2": 0}))
    grading = bench_report.import_grading("swe-polybench", src)
    assert grading == {"a__x-1": True, "b__y-2": False}


def test_report_renders_funnel_and_graded_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_report, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "swebench-verified"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("run_log.json").write_text(json.dumps({
        "a__x-1": {"terminal": "pr_open", "n_attempts": 1},
        "b__y-2": {"terminal": "escalated", "n_attempts": 2},
    }))
    run_dir.joinpath("grading.json").write_text(json.dumps({"a__x-1": True, "b__y-2": False}))

    report = bench_report.build_report()
    assert "| swebench-verified | 2 | **50.0%** (1/2) | 50% | 50% | 0 | 1.5 |" in report
    # benchmarks never run render a placeholder row, not a crash
    assert "| swebench-live | not run |" in report


def test_report_marks_ungraded_benchmarks(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_report, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "swebench-pro"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("run_log.json").write_text(json.dumps({
        "i-1": {"terminal": "pr_open", "n_attempts": 1},
    }))
    report = bench_report.build_report()
    assert "awaiting official harness" in report
