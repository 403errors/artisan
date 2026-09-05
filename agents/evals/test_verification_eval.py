"""Live verification-agent eval harness. #17 made verification criteria-aware but report-first —
"hard-gating flips only once eval data justifies it." This harness produces that data: oracle-
labeled scenarios (issue + plan + execution diff summary) where the correct verdict is known,
measuring whether the live verification agent agrees.

Per scenario (N_REPS reps each):

- verdict agreement (hard headline, model-judged scenarios only): does `green` match the oracle?
- short-circuit correctness (deterministic, reported separately): tests_passed=false must yield
  green=false with feedback and no LLM call — this is code, not model judgment.
- per-criterion status agreement on the labeled subset (matched case-insensitively by substring
  against the criterion text) — the reliability number #17's hard-gating decision needs.
- feedback presence on expected-red verdicts (a red verdict without actionable feedback breaks
  the retry loop's prior_feedback chain).

Excluded from default runs (`-m 'not eval'`). Run explicitly:

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai \
    GOOGLE_CLOUD_LOCATION=global \
        uv run --package artisan-agents pytest agents/evals/test_verification_eval.py -m eval -s

Writes `agents/evals/VERIFICATION_REPORT.md` and a `verification_results.json` sidecar (consumed
by pipeline_report.py). The only hard assertion is structural: every model-judged rep produced a
parseable VerificationVerdict.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from artisan_agents.agents.domain_expert_agent import criteria_for_domains
from artisan_agents.agents.verification_agent import run_verification
from artisan_shared.models import ExecutionResult, Plan, VerificationVerdict

pytestmark = pytest.mark.eval

GOLDEN_PATH = Path(__file__).parent / "verification_golden.json"
REPORT_PATH = Path(__file__).parent / "VERIFICATION_REPORT.md"
SIDECAR_PATH = Path(__file__).parent / "verification_results.json"
N_REPS = 2


def _criterion_status(verdict: VerificationVerdict, substring: str) -> str | None:
    """Finds the labeled criterion's judged status by case-insensitive substring match against
    the criterion text (labels name criteria by a distinctive fragment, not the full string)."""
    needle = substring.lower()
    for result in verdict.criteria_results:
        if needle in result.criterion.lower():
            return result.status
    return None


@pytest.mark.asyncio
async def test_verification_golden_scenarios() -> None:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "TRUE":
        pytest.skip(
            "eval harness calls live Gemini on Vertex AI — set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
            "(plus GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION=global) to run it"
        )
    scenarios = json.loads(GOLDEN_PATH.read_text())["scenarios"]
    results: dict[str, list[VerificationVerdict | None]] = {}

    for scenario in scenarios:

        async def _run_once(s: dict = scenario) -> VerificationVerdict | None:
            plan = Plan(**s["plan"])
            execution = ExecutionResult(
                branch="eval/verification",
                diff_summary=s["execution"]["diff_summary"],
                tests_passed=s["execution"]["tests_passed"],
                logs_uri="eval://verification",
            )
            try:
                return await run_verification(
                    plan=plan,
                    execution_result=execution,
                    issue_title=s["issue"]["title"],
                    issue_body=s["issue"]["body"],
                    review_criteria=criteria_for_domains(s["domains"]),
                )
            except Exception:  # noqa: BLE001 — a failed call counts as a wrong answer for that
                return None  # rep, not a crashed eval run

        results[scenario["id"]] = list(await asyncio.gather(*(_run_once() for _ in range(N_REPS))))

    failed = [sid for sid, reps in results.items() if any(r is None for r in reps)]
    assert not failed, f"verification failed to produce a valid verdict for: {failed}"

    report, sidecar = _build_report(scenarios, results)
    REPORT_PATH.write_text(report)
    SIDECAR_PATH.write_text(json.dumps(sidecar, indent=2))
    print(f"\n{report}")


def _build_report(scenarios: list[dict], results: dict) -> tuple[str, dict]:
    per_scenario: list[dict] = []
    for scenario in scenarios:
        deterministic = not scenario["execution"]["tests_passed"]
        reps = results[scenario["id"]]
        rep_rows = []
        for verdict in reps:
            criteria_hits = {}
            for substring, expected_status in scenario.get("expected_criteria", {}).items():
                criteria_hits[substring] = _criterion_status(verdict, substring) == expected_status
            rep_rows.append(
                {
                    "green": verdict.green,
                    "verdict_correct": verdict.green == scenario["expected_green"],
                    "feedback_present": bool(verdict.feedback),
                    "criteria_hits": criteria_hits,
                }
            )
        per_scenario.append(
            {
                "id": scenario["id"],
                "deterministic": deterministic,
                "expected_green": scenario["expected_green"],
                "expect_feedback": scenario["expect_feedback"],
                "reps": rep_rows,
            }
        )

    judged = [s for s in per_scenario if not s["deterministic"]]
    shortcircuit = [s for s in per_scenario if s["deterministic"]]
    judged_reps = [r for s in judged for r in s["reps"]]
    verdict_accuracy = (
        sum(1 for r in judged_reps if r["verdict_correct"]) / len(judged_reps) if judged_reps else None
    )
    shortcircuit_ok = all(
        all((not r["green"]) and r["feedback_present"] for r in s["reps"]) for s in shortcircuit
    )
    all_criteria_hits = [hit for s in judged for r in s["reps"] for hit in r["criteria_hits"].values()]
    criteria_agreement = (
        sum(all_criteria_hits) / len(all_criteria_hits) if all_criteria_hits else None
    )
    red_reps = [r for s in judged if s["expect_feedback"] for r in s["reps"] if not r["green"]]
    feedback_rate = (
        sum(1 for r in red_reps if r["feedback_present"]) / len(red_reps) if red_reps else None
    )

    lines = [
        "# Verification eval report",
        "",
        (f"Generated: {datetime.now(timezone.utc).isoformat()} — {len(judged)} model-judged "
         f"scenarios + {len(shortcircuit)} deterministic short-circuit scenarios x {N_REPS} reps, "
         "live Gemini."),
        "",
        "## Headline metrics",
        "",
        f"- **Verdict agreement with oracle (model-judged):** {_pct(verdict_accuracy)}",
        f"- **Per-criterion status agreement (labeled subset):** {_pct(criteria_agreement)}",
        f"- **Feedback present on red verdicts:** {_pct(feedback_rate)}",
        f"- **Deterministic short-circuit correct:** {'yes' if shortcircuit_ok else 'NO'}",
        "",
        ("Guidance thresholds (not yet enforced): verdict agreement >= 90%, criteria agreement "
         ">= 85% before #17 hard-gating can be considered."),
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Expected | Verdict correct (reps) | Criteria hits | Feedback on red |",
        "|---|---|---|---|---|",
    ]
    for s in per_scenario:
        verdicts = "/".join("✓" if r["verdict_correct"] else "✗" for r in s["reps"])
        n_hits = sum(sum(r["criteria_hits"].values()) for r in s["reps"])
        n_labeled = sum(len(r["criteria_hits"]) for r in s["reps"])
        criteria = f"{n_hits}/{n_labeled}" if n_labeled else "—"
        if s["expect_feedback"]:
            fb = "/".join("✓" if r["feedback_present"] else "✗" for r in s["reps"])
        else:
            fb = "n/a"
        label = "green" if s["expected_green"] else "red"
        if s["deterministic"]:
            label += " (short-circuit)"
        lines.append(f"| {s['id']} | {label} | {verdicts} | {criteria} | {fb} |")
    lines.append("")

    sidecar = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_scenarios": len(per_scenario),
        "n_reps": N_REPS,
        "verdict_accuracy": verdict_accuracy,
        "criteria_agreement": criteria_agreement,
        "feedback_rate_on_red": feedback_rate,
        "shortcircuit_ok": shortcircuit_ok,
        "per_scenario": per_scenario,
    }
    return "\n".join(lines), sidecar


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"
