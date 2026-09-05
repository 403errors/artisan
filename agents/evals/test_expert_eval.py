"""Live domain-expert eval harness. The routing eval (test_routing_eval.py) measures whether the
right domain is picked; this harness measures what a CORRECTLY-routed expert then produces —
given goldens that pin the domain, so routing noise can't contaminate the expert measurement.

Per case (golden issue + synthetic repo with a realistic file tree), the live expert agent runs
N_REPS times and is scored on:

- relevant-files recall / precision (hard metric; matching rules in scoring.py — ancestor
  directories and globs count, per the expert instruction's "plausible directory or pattern"
  allowance)
- hallucinated-path count (hard metric; the instruction forbids fabricating precise paths)
- judge-scored summary quality (SOFT metric, clearly labeled): a reference-based judge compares
  the technical summary against the case's labeled root cause — root-cause identified, correct
  area, actionable. Judge variance is real; never headline these numbers.

Excluded from default runs (`-m 'not eval'`). Run explicitly:

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai \
    GOOGLE_CLOUD_LOCATION=global \
        uv run --package artisan-agents pytest agents/evals/test_expert_eval.py -m eval -s

Writes `agents/evals/EXPERT_REPORT.md` and an `expert_results.json` sidecar (consumed by
pipeline_report.py). The only hard assertion is structural: every rep produced a parseable
DomainExpertOutput.
"""

import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
from artisan_agents.agents._run_agent import run_structured
from artisan_agents.agents.domain_expert_agent import run_domain_expert
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.models import DomainExpertOutput, RepoContext
from google.adk import Agent
from pydantic import BaseModel

from scoring import file_precision_recall

pytestmark = pytest.mark.eval

GOLDEN_PATH = Path(__file__).parent / "expert_golden.json"
REPORT_PATH = Path(__file__).parent / "EXPERT_REPORT.md"
SIDECAR_PATH = Path(__file__).parent / "expert_results.json"
N_REPS = 2


class JudgeScore(BaseModel):
    """Reference-based judge output for one expert summary. Binary questions only — coarse
    rubrics are what keep an LLM judge's variance manageable."""

    root_cause_identified: bool
    correct_area: bool
    actionable: bool
    rationale: str


_judge_agent = Agent(
    model=GEMINI_MODEL_ID,
    name="expert_eval_judge",
    instruction=(
        "You are grading a domain-expert agent's technical summary of a GitHub issue. You are "
        "given the issue, the REFERENCE root cause (ground truth, written by the dataset "
        "authors), and the expert's summary. Answer three binary questions: "
        "root_cause_identified — does the summary point at the same underlying cause/mechanism "
        "as the reference (different wording is fine, a different cause is not)? "
        "correct_area — does the summary focus on the right part of the codebase rather than a "
        "red herring? actionable — could a planning agent act on this summary without re-reading "
        "the issue? Be strict: vague restatements of the issue text score false on "
        "root_cause_identified."
    ),
    output_schema=JudgeScore,
    output_key="judge_score",
)


def _repo_context(case: dict) -> RepoContext:
    repo = case["repo"]
    return RepoContext(
        repo="eval/synthetic",
        head_sha="eval",
        file_tree=repo["file_tree"],
        manifests=repo.get("manifests", {}),
        languages=repo.get("languages", {}),
        fetched_at=datetime.now(timezone.utc),
    )


async def _judge(case: dict, summary: str) -> JudgeScore | None:
    prompt = (
        f"Issue title: {case['title']}\n\nIssue body: {case['body']}\n\n"
        f"Reference root cause (ground truth): {case['root_cause']}\n\n"
        f"Expert's technical summary to grade: {summary}"
    )
    try:
        return await run_structured(
            agent=_judge_agent,
            app_name="artisan-expert-eval-judge",
            output_key="judge_score",
            output_model=JudgeScore,
            prompt=prompt,
        )
    except Exception:  # noqa: BLE001 — a judge failure loses one soft score, not the eval run
        return None


@pytest.mark.asyncio
async def test_expert_golden_dataset() -> None:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "TRUE":
        pytest.skip(
            "eval harness calls live Gemini on Vertex AI — set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
            "(plus GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION=global) to run it"
        )
    cases = json.loads(GOLDEN_PATH.read_text())["cases"]
    # case id -> list of (expert output, judge score) per rep
    results: dict[str, list[tuple[DomainExpertOutput | None, JudgeScore | None]]] = {}

    for case in cases:

        async def _run_once(case: dict = case) -> tuple[DomainExpertOutput | None, JudgeScore | None]:
            try:
                output = await run_domain_expert(
                    domain=case["domain"],
                    issue_title=case["title"],
                    issue_body=case["body"],
                    repo_context=_repo_context(case),
                )
            except Exception:  # noqa: BLE001 — a failed call counts as a wrong answer for that
                return None, None  # rep, not a crashed eval run
            return output, await _judge(case, output.technical_summary)

        results[case["id"]] = list(await asyncio.gather(*(_run_once() for _ in range(N_REPS))))

    failed = [cid for cid, reps in results.items() if any(r is None for r, _ in reps)]
    assert not failed, f"domain expert failed to produce a valid output for: {failed}"

    report, sidecar = _build_report(cases, results)
    REPORT_PATH.write_text(report)
    SIDECAR_PATH.write_text(json.dumps(sidecar, indent=2))
    print(f"\n{report}")


def _build_report(cases: list[dict], results: dict) -> tuple[str, dict]:
    per_case: list[dict] = []
    for case in cases:
        reps = results[case["id"]]
        rep_scores = []
        for output, judge in reps:
            precision, recall, hallucinated = file_precision_recall(
                output.relevant_files, case["expected_files"], case["repo"]["file_tree"]
            )
            rep_scores.append(
                {
                    "precision": precision,
                    "recall": recall,
                    "hallucinated": hallucinated,
                    "n_files": len(output.relevant_files),
                    "judge": judge.model_dump() if judge else None,
                }
            )
        per_case.append({"id": case["id"], "domain": case["domain"], "reps": rep_scores})

    recalls = [r["recall"] for p in per_case for r in p["reps"]]
    precisions = [r["precision"] for p in per_case for r in p["reps"] if r["precision"] is not None]
    hallucinations = [len(r["hallucinated"]) for p in per_case for r in p["reps"]]
    total_files = [r["n_files"] for p in per_case for r in p["reps"]]
    judge_keys = ("root_cause_identified", "correct_area", "actionable")
    judge_scores = [r["judge"] for p in per_case for r in p["reps"] if r["judge"] is not None]
    judge_means = {
        k: sum(1 for j in judge_scores if j[k]) / len(judge_scores) for k in judge_keys
    } if judge_scores else {}

    mean_recall = sum(recalls) / len(recalls)
    mean_precision = sum(precisions) / len(precisions) if precisions else None

    # Per-domain rollup (run 1 only, mirrors the routing report's per-domain table).
    per_domain: dict[str, list[dict]] = {}
    for p in per_case:
        per_domain.setdefault(p["domain"], []).append(p["reps"][0])

    lines = [
        "# Domain-expert eval report",
        "",
        (f"Generated: {datetime.now(timezone.utc).isoformat()} — {len(cases)} cases x {N_REPS} "
         "reps, live Gemini, domain pinned correct by goldens (routing measured separately)."),
        "",
        "## Headline metrics (hard)",
        "",
        f"- **Relevant-files recall (mean over reps):** {mean_recall:.1%}",
        f"- **Relevant-files precision (mean over reps):** {_pct(mean_precision)}",
        (f"- **Hallucinated paths:** {sum(hallucinations)} across {sum(total_files)} predicted "
         f"paths ({_pct(sum(hallucinations) / max(sum(total_files), 1))})"),
        "",
        "## Judge-scored summary quality (SOFT — reference-based LLM judge, not a headline)",
        "",
    ]
    for key, value in judge_means.items():
        lines.append(f"- {key}: {value:.1%}")
    lines += [
        "",
        "Guidance thresholds (not yet enforced): recall >= 80%, hallucination rate < 5%.",
        "",
        "## Per-domain (run 1)",
        "",
        "| Domain | Recall | Precision | Hallucinated |",
        "|---|---|---|---|",
    ]
    for domain in sorted(per_domain):
        reps = per_domain[domain]
        d_recall = sum(r["recall"] for r in reps) / len(reps)
        d_precs = [r["precision"] for r in reps if r["precision"] is not None]
        d_prec = sum(d_precs) / len(d_precs) if d_precs else None
        d_hall = sum(len(r["hallucinated"]) for r in reps)
        lines.append(f"| {domain} | {d_recall:.0%} | {_pct(d_prec)} | {d_hall} |")
    lines += [
        "",
        "## Per-case results",
        "",
        "| Case | Domain | Recall (reps) | Precision (reps) | Hallucinated | Judge (reps) |",
        "|---|---|---|---|---|---|",
    ]
    for p in per_case:
        rec = "/".join(f"{r['recall']:.0%}" for r in p["reps"])
        prec = "/".join(_pct(r["precision"]) for r in p["reps"])
        hall = sum(len(r["hallucinated"]) for r in p["reps"])
        judge = "/".join(
            f"{sum(1 for k in judge_keys if r['judge'][k])}/3" if r["judge"] else "—"
            for r in p["reps"]
        )
        lines.append(f"| {p['id']} | {p['domain']} | {rec} | {prec} | {hall} | {judge} |")
    lines.append("")

    sidecar = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(cases),
        "n_reps": N_REPS,
        "mean_recall": mean_recall,
        "mean_precision": mean_precision,
        "hallucination_rate": sum(hallucinations) / max(sum(total_files), 1),
        "judge_means": judge_means,
        "per_case": per_case,
    }
    return "\n".join(lines), sidecar


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"
