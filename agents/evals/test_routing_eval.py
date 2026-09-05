"""Live routing eval harness (v2 wave 1.5 #19).

Unit tests stub the model, so they can never catch a routing-*quality* regression from a prompt
or model change. This harness runs the real routing agent (live Gemini, Vertex AI `global`,
temperature pinned to 0) against a golden dataset of labeled issues and reports:

- exact-set match rate (per run and mean over N repetitions)
- per-domain precision/recall (first run)
- fallback rate (share of predicted domains outside the bespoke registry)
- cross-run stability (fraction of cases where all N runs agree — #13's real measurement)
- confidence distribution (self-reported by the router since #15)

Excluded from default test runs (`-m 'not eval'` in agents/pyproject.toml's addopts). Run
explicitly:

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai \
    GOOGLE_CLOUD_LOCATION=global \
        uv run --package artisan-agents pytest agents/evals -m eval -s

It writes `agents/evals/REPORT.md`. Thresholds are documented guidance, not hard gates, until
enough runs exist to set a real one — the test itself only asserts structural sanity (every case
produced a parseable RoutingDecision on every rep).
"""

import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
from artisan_agents.agents.domain_expert_agent import PERSONA_DOMAINS
from artisan_agents.agents.routing_agent import run_routing
from artisan_shared.models import RepoContext, RoutingDecision

pytestmark = pytest.mark.eval

GOLDEN_PATH = Path(__file__).parent / "routing_golden.json"
REPORT_PATH = Path(__file__).parent / "REPORT.md"
SIDECAR_PATH = Path(__file__).parent / "routing_results.json"
N_REPS = 3


def _repo_context(case: dict) -> RepoContext | None:
    repo = case.get("repo")
    if repo is None:
        return None
    manifests = repo.get("manifests", {})
    return RepoContext(
        repo="eval/synthetic",
        head_sha="eval",
        file_tree=list(manifests.keys()),
        manifests=manifests,
        languages=repo.get("languages", {}),
        fetched_at=datetime.now(timezone.utc),
    )


def _normalized_domains(decision: RoutingDecision) -> set[str]:
    # Same normalization the lens lookup applies — casing drift shouldn't count as a miss.
    return {d.strip().lower() for d in decision.domains}


def _case_passes(case: dict, predicted: set[str]) -> bool:
    if case.get("expect_fallback"):
        return bool(predicted) and all(d not in PERSONA_DOMAINS for d in predicted)
    return predicted == set(case["expected"])


@pytest.mark.asyncio
async def test_routing_golden_dataset() -> None:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "TRUE":
        pytest.skip(
            "eval harness calls live Gemini on Vertex AI — set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
            "(plus GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION=global) to run it"
        )
    cases = json.loads(GOLDEN_PATH.read_text())["cases"]
    results: dict[str, list[RoutingDecision | None]] = {}

    for case in cases:

        async def _run_once(case: dict = case) -> RoutingDecision | None:
            try:
                return await run_routing(
                    issue_title=case["title"],
                    issue_body=case["body"],
                    jira_key="EVAL-0",
                    repo_context=_repo_context(case),
                )
            except Exception:  # noqa: BLE001 — deliberate: a failed parse/call counts as a
                return None  # wrong answer for that rep, not a crashed eval run

        # Reps within a case run concurrently (temp-0 pin makes them near-free variance-wise);
        # cases stay sequential to keep the live call rate gentle.
        results[case["id"]] = list(await asyncio.gather(*(_run_once() for _ in range(N_REPS))))

    # Structural sanity — the only hard assertion: every rep produced a valid decision.
    failed = [cid for cid, reps in results.items() if any(r is None for r in reps)]
    assert not failed, f"routing failed to produce a valid decision for: {failed}"

    typed_results: dict[str, list[RoutingDecision]] = {
        cid: [r for r in reps if r is not None] for cid, reps in results.items()
    }
    report, sidecar = _build_report(cases, typed_results)
    REPORT_PATH.write_text(report)
    SIDECAR_PATH.write_text(json.dumps(sidecar, indent=2))
    print(f"\n{report}")


def _build_report(cases: list[dict], results: dict[str, list[RoutingDecision]]) -> tuple[str, dict]:
    per_case: list[dict] = []
    for case in cases:
        reps = results[case["id"]]
        predicted_sets = [_normalized_domains(r) for r in reps]
        per_case.append(
            {
                "id": case["id"],
                "expected": "fallback" if case.get("expect_fallback") else "+".join(case["expected"]),
                "passes": [_case_passes(case, s) for s in predicted_sets],
                "stable": len({tuple(sorted(s)) for s in predicted_sets}) == 1,
                "predicted_run1": "+".join(sorted(predicted_sets[0])),
                "confidence_run1": reps[0].confidence,
            }
        )

    # Calibration (wave-2 #5 input): per-rep correctness bucketed by self-reported confidence.
    # A calibrated router is right more often when it says "high" than when it says "low" — the
    # wave-1.5 baseline answered "high" on all 75 reps including the wrong ones (uncalibrated).
    calibration: dict[str, dict[str, int]] = {}
    for case, p in zip(cases, per_case):
        for rep, passes in zip(results[case["id"]], p["passes"]):
            bucket = calibration.setdefault(rep.confidence, {"correct": 0, "total": 0})
            bucket["total"] += 1
            bucket["correct"] += int(passes)

    n = len(per_case)
    mean_match = sum(sum(p["passes"]) / N_REPS for p in per_case) / n
    stability = sum(1 for p in per_case if p["stable"]) / n
    all_predicted = [d for case in cases for r in results[case["id"]] for d in _normalized_domains(r)]
    fallback_rate = sum(1 for d in all_predicted if d not in PERSONA_DOMAINS) / max(
        len(all_predicted), 1
    )
    confidences = Counter(r.confidence for case in cases for r in results[case["id"]])

    # Per-domain precision/recall on run 1 (multi-label: each predicted/expected domain counts).
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    for case in cases:
        predicted = _normalized_domains(results[case["id"]][0])
        expected = set() if case.get("expect_fallback") else set(case["expected"])
        for d in predicted & expected:
            tp[d] += 1
        for d in predicted - expected:
            if d in PERSONA_DOMAINS:
                fp[d] += 1
        for d in expected - predicted:
            fn[d] += 1

    lines = [
        "# Routing eval report",
        "",
        (f"Generated: {datetime.now(timezone.utc).isoformat()} — {n} cases x {N_REPS} reps, "
        "live Gemini via Vertex AI `global`, temperature=0."),
        "",
        "## Headline metrics",
        "",
        f"- **Exact-set match (mean over reps):** {mean_match:.1%}",
        f"- **Cross-run stability (all {N_REPS} reps agree):** {stability:.1%}",
        f"- **Fallback rate (predictions outside the bespoke registry):** {fallback_rate:.1%}",
        f"- **Self-reported confidence:** {dict(confidences)}",
        "",
        "## Confidence calibration (accuracy within each confidence bucket)",
        "",
        "| Confidence | Correct | Total | Accuracy |",
        "|---|---|---|---|",
    ]
    for level in ("low", "medium", "high"):
        bucket = calibration.get(level)
        if bucket:
            acc = bucket["correct"] / bucket["total"]
            lines.append(f"| {level} | {bucket['correct']} | {bucket['total']} | {acc:.0%} |")
    lines += [
        "",
        "Guidance thresholds (not yet enforced): match >= 90%, stability >= 95%, fallback < 10%.",
        "",
        "## Per-domain precision/recall (run 1)",
        "",
        "| Domain | Precision | Recall | TP/FP/FN |",
        "|---|---|---|---|",
    ]
    for domain in PERSONA_DOMAINS:
        precision = tp[domain] / (tp[domain] + fp[domain]) if tp[domain] + fp[domain] else None
        recall = tp[domain] / (tp[domain] + fn[domain]) if tp[domain] + fn[domain] else None
        lines.append(
            f"| {domain} | {_pct(precision)} | {_pct(recall)} | "
            f"{tp[domain]}/{fp[domain]}/{fn[domain]} |"
        )
    lines += [
        "",
        "## Per-case results",
        "",
        "| Case | Expected | Run 1 predicted | Passes (of reps) | Stable | Confidence (run 1) |",
        "|---|---|---|---|---|---|",
    ]
    for p in per_case:
        lines.append(
            f"| {p['id']} | {p['expected']} | {p['predicted_run1']} | "
            f"{sum(p['passes'])}/{N_REPS} | {'yes' if p['stable'] else 'NO'} | {p['confidence_run1']} |"
        )
    lines.append("")

    sidecar = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(cases),
        "n_reps": N_REPS,
        "mean_match": mean_match,
        "stability": stability,
        "fallback_rate": fallback_rate,
        "confidence_distribution": dict(confidences),
        "calibration": calibration,
        "per_case": per_case,
    }
    return "\n".join(lines), sidecar


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
