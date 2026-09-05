"""Aggregates the eval harnesses' JSON sidecars into one PIPELINE_REPORT.md — the single
funnel view of pipeline quality, from routing accuracy down to end-to-end verified-correct rate.

Each harness writes its own sidecar when run (routing_results.json, expert_results.json,
verification_results.json, e2e_results.json). This aggregator is offline and free — it makes no
live calls and tolerates missing sidecars (a stage that hasn't run shows as "not yet run" rather
than breaking the report). Run after the harnesses:

    uv run --package artisan-agents python agents/evals/pipeline_report.py

The funnel framing is deliberate: one magic number hides where quality is lost, so the headline
E2E number is always presented with the per-stage numbers that explain it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

EVALS_DIR = Path(__file__).parent
REPORT_PATH = EVALS_DIR / "PIPELINE_REPORT.md"

_SIDECARS = {
    "routing": "routing_results.json",
    "expert": "expert_results.json",
    "verification": "verification_results.json",
    "e2e": "e2e_results.json",
}


def _load(stage: str) -> dict | None:
    path = EVALS_DIR / _SIDECARS[stage]
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _stage_rows(routing: dict | None, expert: dict | None, verification: dict | None,
                e2e: dict | None) -> list[str]:
    rows = [
        "| Stage | Metric | Value | Details |",
        "|---|---|---|---|",
    ]
    if routing:
        rows.append(
            f"| Routing | Exact-set domain match | {_pct(routing['mean_match'])} "
            f"| {routing['n_cases']} cases x {routing['n_reps']} reps; stability "
            f"{_pct(routing['stability'])}; fallback {_pct(routing['fallback_rate'])} |"
        )
        cal = routing.get("calibration", {})
        if cal:
            cal_text = "; ".join(
                f"{lvl}: {b['correct'] / b['total']:.1%} ({b['correct']}/{b['total']})"
                for lvl, b in sorted(cal.items())
                if b.get("total")
            )
            rows.append(f"| Routing | Confidence calibration (accuracy per level) | — | {cal_text} |")
    else:
        rows.append("| Routing | — | not yet run | |")
    if expert:
        rows.append(
            f"| Domain expert | Relevant-files recall | {_pct(expert['mean_recall'])} "
            f"| precision {_pct(expert.get('mean_precision'))}; hallucination rate "
            f"{_pct(expert['hallucination_rate'])} |"
        )
        judge = expert.get("judge_means") or {}
        if judge:
            judge_text = "; ".join(f"{k} {_pct(v)}" for k, v in judge.items())
            rows.append(f"| Domain expert | Summary quality (SOFT, LLM judge) | — | {judge_text} |")
    else:
        rows.append("| Domain expert | — | not yet run | |")
    if verification:
        rows.append(
            f"| Verification | Verdict agreement with oracle | {_pct(verification['verdict_accuracy'])} "
            f"| criteria agreement {_pct(verification['criteria_agreement'])}; feedback-on-red "
            f"{_pct(verification['feedback_rate_on_red'])} |"
        )
    else:
        rows.append("| Verification | — | not yet run | |")
    if e2e:
        rows.append(
            f"| **End-to-end** | **Verified-correct rate** | **{_pct(e2e['verified_correct_rate'])}** "
            f"| false-green {_pct(e2e['false_green_rate'])}; escalations "
            f"{_pct(e2e['escalation_rate'])}; mean attempts {e2e['mean_attempts']:.1f} |"
        )
    else:
        rows.append("| **End-to-end** | — | not yet run | |")
    return rows


def build_pipeline_report(
    routing: dict | None, expert: dict | None, verification: dict | None, e2e: dict | None
) -> str:
    """Renders the funnel report from the four stage sidecars (None when a stage hasn't run)."""
    lines = [
        "# Artisan pipeline quality report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()} — aggregated from the eval "
        "harnesses' JSON sidecars (agents/evals/). All stages run live Gemini against golden "
        "datasets or seeded-bug fixture repos; nothing here is self-reported by the pipeline.",
        "",
        "## The funnel",
        "",
        *_stage_rows(routing, expert, verification, e2e),
        "",
        "## How to read this",
        "",
        "- **Routing** answers: did the right specialist get the ticket? (exact-set match on a "
        "25-case golden dataset, plus confidence calibration — a calibrated router is right more "
        "often when it says \"high\".)",
        "- **Domain expert** answers: given the right specialist, did it identify the right "
        "files and root cause? (file recall/precision are hard metrics; summary quality is "
        "judge-scored and deliberately not a headline.)",
        "- **Verification** answers: does the gate agree with a known-correct oracle? (This is "
        "the number #17's criteria hard-gating decision waits on.)",
        "- **End-to-end** answers: on seeded real bugs, how often does the pipeline ship a fix "
        "that passes tests it never saw? And how often does it ship a wrong fix believing it's "
        "right (false green) — the number verification exists to keep at zero.",
        "",
        "Stage reports: REPORT.md (routing), EXPERT_REPORT.md, VERIFICATION_REPORT.md, "
        "E2E_REPORT.md.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    report = build_pipeline_report(
        _load("routing"), _load("expert"), _load("verification"), _load("e2e")
    )
    REPORT_PATH.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
