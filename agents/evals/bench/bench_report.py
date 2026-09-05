"""Benchmark report generator — turns bench_runs/ into BENCH_REPORT.md (manual tool).

    # after runner.py produced predictions for a benchmark:
    python agents/evals/bench/bench_report.py

    # after grading with the benchmark's OFFICIAL harness, import its verdicts:
    python agents/evals/bench/bench_report.py --import-harness swebench-verified \
        logs/run_evaluation/artisan-v2     # dir tree of per-instance report.json files
    python agents/evals/bench/bench_report.py --import-harness swe-polybench results.json
    # (a flat {"instance_id": true/false} or {"resolved": {"iid": bool}} JSON also works)

Artisan never grades itself: the "resolved" column exists only where an official harness's
per-instance report files were imported. Everything else comes from the runner's own
run_log.json (routing domains, attempts, terminal state) — pipeline funnel metrics, NOT
correctness claims.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry import BENCHMARKS

RUNS_DIR = Path(__file__).resolve().parent / "bench_runs"
REPORT_PATH = Path(__file__).resolve().parent / "BENCH_REPORT.md"


def import_grading(benchmark_key: str, source: Path) -> dict[str, bool]:
    """Normalizes an official harness's output into {instance_id: resolved} and stores it as
    bench_runs/<key>/grading.json. Accepts a SWE-bench-style run_evaluation log tree (glob for
    per-instance report.json) or a flat JSON mapping."""
    if source.is_dir():
        reports = list(source.rglob("report.json"))
        if not reports:
            raise SystemExit(f"No report.json files under {source} — is that a harness log dir?")
        grading = {}
        for report in reports:
            payload = json.loads(report.read_text())
            iid = payload.get("instance_id") or report.parent.name
            grading[iid] = bool(payload.get("resolved"))
    else:
        payload = json.loads(source.read_text())
        if "resolved" in payload and isinstance(payload["resolved"], dict):
            grading = {k: bool(v) for k, v in payload["resolved"].items()}
        else:
            grading = {k: bool(v) for k, v in payload.items()}
    out = RUNS_DIR / benchmark_key / "grading.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(grading, indent=2))
    return grading


def _benchmark_row(key: str) -> str:
    run_dir = RUNS_DIR / key
    log_path = run_dir / "run_log.json"
    if not log_path.exists():
        return f"| {key} | not run | — | — | — | — | — |"
    log = json.loads(log_path.read_text())
    attempted = [v for v in log.values() if isinstance(v, dict)]
    n = len(attempted)
    pr_open = sum(1 for v in attempted if v.get("terminal") == "pr_open")
    escalated = sum(1 for v in attempted if v.get("terminal") == "escalated")
    errors = sum(1 for v in attempted if v.get("terminal") == "runner_error")
    attempts = [v.get("n_attempts", 0) for v in attempted]
    mean_attempts = f"{sum(attempts) / n:.1f}" if n else "—"

    grading_path = run_dir / "grading.json"
    if grading_path.exists():
        grading = json.loads(grading_path.read_text())
        resolved = sum(1 for v in grading.values() if v)
        resolved_str = f"**{resolved / len(grading):.1%}** ({resolved}/{len(grading)})"
    else:
        resolved_str = "awaiting official harness"
    return (
        f"| {key} | {n} | {resolved_str} | {pr_open / n:.0%} | {escalated / n:.0%} "
        f"| {errors} | {mean_attempts} |"
    )


def build_report() -> str:
    lines = [
        "# Artisan external benchmark report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()} — 50 frozen instances per "
        "benchmark, Artisan pipeline (live Gemini) generating patches, correctness graded ONLY "
        "by each benchmark's official harness (imported via --import-harness).",
        "",
        "| Benchmark | Attempted | Resolved (official) | PR opened | Escalated | Runner errors | Mean attempts |",
        "|---|---|---|---|---|---|---|",
        *(_benchmark_row(key) for key in sorted(BENCHMARKS)),
        "",
        "Resolved rate = official-harness FAIL_TO_PASS+PASS_TO_PASS verdicts on our "
        "predictions.jsonl. PR-opened/escalated/attempts are Artisan-internal funnel metrics "
        "from run_log.json (how the pipeline behaved), not correctness claims.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--import-harness", nargs=2, metavar=("BENCHMARK", "PATH"),
                        help="import official-harness verdicts (log dir or JSON) for a benchmark")
    args = parser.parse_args()

    if args.import_harness:
        key, source = args.import_harness
        if key not in BENCHMARKS:
            raise SystemExit(f"unknown benchmark {key!r} — choices: {sorted(BENCHMARKS)}")
        grading = import_grading(key, Path(source))
        print(f"imported {len(grading)} official verdicts for {key} "
              f"({sum(grading.values())} resolved)")

    REPORT_PATH.write_text(build_report())
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
