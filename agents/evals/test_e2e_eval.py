"""Live end-to-end Gate 2 eval harness — a SWE-bench-mini for the full pipeline.

The stage evals (routing / domain-expert / verification) measure each agent in isolation; this
harness measures the whole loop on seeded bugs: real `start_gate2` control flow, live Gemini for
routing -> domain experts -> planning -> coding agent -> verification, with only the *external
world* faked (Firestore in-memory, GitHub/Jira stubbed, and `trigger_execution` replaced by a
local executor that runs the sandbox's real coding agent against a fixture repo instead of a
Cloud Run Job).

Each fixture under `e2e_fixtures/<id>/` is a real runnable repo with a seeded bug:

- `repo/` — the repo the pipeline sees. Visible tests PASS with the bug (the bug is uncovered)
  except scenarios with `visible_failing_test: true`, which include a failing repro test — the
  realistic "issue + repro" shape, with the classic reward-hacking risk (weakening the test)
  left visible to verification.
- `heldout/` — oracle tests the agent NEVER sees, injected into the workdir only after each
  coding attempt. They fail on the seeded bug and pass on a correct fix. This is the ground
  truth the pipeline's own signals are scored against.

Per scenario the harness records: routing domains vs expected, attempts used, final status
(pr_open / escalated), per-attempt visible/heldout test results, and every verification verdict.
Headline metric: **verified-correct rate** — share of scenarios that opened a PR whose final
attempt passes the held-out oracle. Its evil twin, **false-green rate** — PRs opened on fixes
the oracle rejects — is the number verification exists to keep at zero.

Excluded from default runs (`-m 'not eval'`). Run explicitly:

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=artisan-multiagent-ai \
    GOOGLE_CLOUD_LOCATION=global \
        uv run --package artisan-agents pytest agents/evals/test_e2e_eval.py -m eval -s

Writes `agents/evals/E2E_REPORT.md` and an `e2e_results.json` sidecar (consumed by
pipeline_report.py). N_REPS=1 by default (each scenario costs multiple live coding-agent runs);
set ARTISAN_E2E_REPS=2+ for variance estimates. The only hard assertion is structural: every
scenario reached a terminal state.
"""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from artisan_agents import gate2
from artisan_agents.gcp import firestore_client
from artisan_agents.gcp.firestore_client import RetryCapExceeded
from artisan_execution_sandbox.coding_agent import run_coding_agent
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.firestore_schema import TicketDoc
from artisan_shared.models import ExecutionResult, RepoContext

pytestmark = pytest.mark.eval

FIXTURES_DIR = Path(__file__).parent / "e2e_fixtures"
REPORT_PATH = Path(__file__).parent / "E2E_REPORT.md"
SIDECAR_PATH = Path(__file__).parent / "e2e_results.json"
N_REPS = int(os.environ.get("ARTISAN_E2E_REPS", "1"))

_MANIFEST_NAMES = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "pubspec.yaml")


def _git(workdir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=artisan-eval", "-c", "user.email=eval@localhost", *args],
        cwd=workdir, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def _run_cmd(command: str, workdir: Path) -> tuple[bool, str]:
    result = subprocess.run(
        shlex.split(command), cwd=workdir, capture_output=True, text=True, check=False,
        timeout=300,
    )
    return result.returncode == 0, result.stdout + result.stderr


def _build_repo_context(repo_dir: Path) -> RepoContext:
    files = sorted(
        str(p.relative_to(repo_dir)) for p in repo_dir.rglob("*") if p.is_file()
    )
    manifests = {
        name: (repo_dir / name).read_text()
        for name in _MANIFEST_NAMES
        if (repo_dir / name).exists()
    }
    languages: dict[str, int] = {}
    for rel in files:
        ext = Path(rel).suffix
        if ext:
            languages[ext] = languages.get(ext, 0) + 1
    return RepoContext(
        repo="eval/e2e",
        head_sha="eval",
        file_tree=files,
        manifests=manifests,
        languages=languages,
        fetched_at=datetime.now(timezone.utc),
    )


class _FakeTicketStore:
    """In-memory Firestore double — same shape as agents/tests/test_gate2.py's."""

    def __init__(self, repo: str, issue_number: int, jira_key: str) -> None:
        now = datetime.now(timezone.utc)
        self.doc = TicketDoc(
            github_issue_number=issue_number,
            github_repo=repo,
            jira_key=jira_key,
            status="in_progress",
            created_at=now,
            updated_at=now,
        )

    def ticket_doc_id(self, repo: str, issue_number: int) -> str:
        return f"{repo}__{issue_number}"

    async def get_ticket(self, repo: str, issue_number: int) -> TicketDoc:
        return self.doc

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        self.doc = self.doc.model_copy(update=fields)

    async def increment_retry_round(self, repo: str, issue_number: int) -> int:
        new_count = self.doc.retry_count + 1
        if new_count >= 3:
            self.doc = self.doc.model_copy(update={"retry_count": new_count, "status": "escalated"})
            raise RetryCapExceeded("cap reached")
        self.doc = self.doc.model_copy(update={"retry_count": new_count})
        return new_count

    async def append_escalation(self, repo: str, issue_number: int, entry) -> None:
        self.doc = self.doc.model_copy(
            update={"escalation_history": [*self.doc.escalation_history, entry], "status": "escalated"}
        )

    async def write_pr_pointer(self, repo: str, pr_number: int, issue_number: int) -> None:
        pass

    async def append_trace_id(self, ticket_id: str, trace_id: str, label: str) -> None:
        pass


def _make_local_executor(scenario_dir: Path, scenario: dict, attempts: list[dict]):
    """The `trigger_execution` replacement: mirrors the production sandbox's run_attempt (fresh
    checkout per attempt -> coding agent -> diff -> tests) but local — no clone, push, security
    scan, or Firestore write. Additionally injects the held-out oracle tests after each attempt
    and records the result; the oracle never influences the pipeline's own signals."""

    async def local_trigger_execution(
        *, repo: str, issue_number: int, branch: str, plan, attempt: int, feedback: str | None
    ) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="artisan-e2e-") as tmp:
            workdir = Path(tmp) / "repo"
            shutil.copytree(scenario_dir / "repo", workdir)
            _git(workdir, "init", "-q")
            _git(workdir, "add", "-A")
            _git(workdir, "commit", "-q", "-m", "baseline")
            _git(workdir, "checkout", "-q", "-b", branch)

            try:
                summary = await run_coding_agent(
                    workdir=workdir, plan=plan, prior_feedback=feedback
                )
            except Exception as exc:
                # Tool-level failures (e.g. a model-chosen shell command timing out) degrade to
                # a failed attempt — the pipeline retries/escalates — not a harness crash.
                attempts.append(
                    {"attempt": attempt, "changes": None, "visible_passed": False,
                     "heldout_passed": False, "summary": f"coding agent error: {exc}"[:300]}
                )
                return ExecutionResult(
                    branch=branch,
                    diff_summary=f"coding agent raised: {type(exc).__name__}: {exc}"[:500],
                    tests_passed=False,
                    logs_uri="local-eval",
                )

            _git(workdir, "add", "-A")
            diff_stat = _git(workdir, "diff", "--cached", "--stat").strip()
            if not diff_stat:
                attempts.append(
                    {"attempt": attempt, "changes": False, "visible_passed": False,
                     "heldout_passed": False, "summary": summary}
                )
                return ExecutionResult(
                    branch=branch,
                    diff_summary=f"coding agent made no changes. Summary: {summary}",
                    tests_passed=False,
                    logs_uri="local-eval",
                )
            # #12: mirror production — verification sees the bounded real patch, not just a stat,
            # plus full content of changed files (unchanged siblings carry the same bug class).
            diff_patch = _git(workdir, "diff", "--cached")[:12_000]
            changed_files = {
                p: (workdir / p).read_text(errors="replace")[:8_000]
                for p in _git(workdir, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()[:10]
                if (workdir / p).is_file()
            }

            visible_ok, visible_out = _run_cmd(scenario["test_command"], workdir)

            heldout_target = workdir / ".heldout_tests"
            shutil.copytree(scenario_dir / "heldout", heldout_target)
            heldout_ok, heldout_out = _run_cmd(scenario["heldout_command"], workdir)
            shutil.rmtree(heldout_target)

            attempts.append(
                {"attempt": attempt, "changes": True, "visible_passed": visible_ok,
                 "heldout_passed": heldout_ok, "diff_stat": diff_stat, "summary": summary,
                 "visible_output_tail": visible_out[-500:], "heldout_output_tail": heldout_out[-500:]}
            )
            return ExecutionResult(
                branch=branch,
                diff_summary=f"{summary}\n\n{diff_stat}",
                tests_passed=visible_ok,
                logs_uri="local-eval",
                diff_patch=diff_patch,
                changed_file_contents=changed_files,
            )

    return local_trigger_execution


async def _run_scenario(monkeypatch, scenario_dir: Path, scenario: dict, issue_number: int) -> dict:
    repo = "eval/e2e"
    jira_key = f"EVAL-{issue_number}"
    store = _FakeTicketStore(repo, issue_number, jira_key)
    attempts: list[dict] = []
    verdicts: list = []

    # Externals faked — Firestore, GitHub, Jira, repo-context fetch, Cloud Run Jobs trigger.
    for name in ("get_ticket", "update_ticket", "increment_retry_round", "append_escalation",
                 "write_pr_pointer", "append_trace_id"):
        monkeypatch.setattr(firestore_client, name, getattr(store, name))
    monkeypatch.setattr(firestore_client, "ticket_doc_id", store.ticket_doc_id)
    monkeypatch.setattr(firestore_client, "new_event_sink", lambda *a, **k: NoOpEventSink())

    async def fake_default_branch(_repo):
        return "main"

    async def fake_open_pr(_repo, *, head, base, title, body):
        return 9000 + issue_number, f"https://example.test/{_repo}/pull/{9000 + issue_number}"

    async def fake_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(gate2.github_client, "get_default_branch", fake_default_branch)
    monkeypatch.setattr(gate2.github_client, "open_pull_request", fake_open_pr)
    monkeypatch.setattr(gate2.github_client, "post_issue_comment", fake_noop)
    monkeypatch.setattr(gate2.github_client, "add_label", fake_noop)
    monkeypatch.setattr(gate2.jira_client, "add_comment", fake_noop)
    monkeypatch.setattr(gate2.jira_client, "add_label", fake_noop)

    repo_context = _build_repo_context(scenario_dir / "repo")

    async def fake_get_repo_context(_repo):
        return repo_context

    monkeypatch.setattr(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)
    monkeypatch.setattr(
        gate2.cloud_run_jobs, "trigger_execution",
        _make_local_executor(scenario_dir, scenario, attempts),
    )

    # Agents run LIVE — routing, domain experts, planning, coding, verification. Verification is
    # wrapped only to record verdicts (the real function runs).
    real_run_verification = gate2.run_verification

    async def recording_verification(**kwargs):
        verdict = await real_run_verification(**kwargs)
        verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(gate2, "run_verification", recording_verification)

    await gate2.start_gate2(
        repo, issue_number, jira_key,
        issue_title=scenario["title"], issue_body=scenario["body"],
    )

    predicted = {d.strip().lower() for d in (store.doc.domains or [])}
    expected = set(scenario["expected_domains"])
    pr_opened = store.doc.status == "pr_open"
    final_attempt = attempts[-1] if attempts else None
    fix_correct = bool(final_attempt and final_attempt["heldout_passed"])
    return {
        "id": scenario["id"],
        "predicted_domains": sorted(predicted),
        "routing_correct": predicted == expected,
        "attempts": attempts,
        "n_attempts": len(attempts),
        "verdicts": [v.green for v in verdicts],
        "terminal": store.doc.status,
        "pr_opened": pr_opened,
        "fix_correct": fix_correct,
        "pipeline_success": pr_opened and fix_correct,
        "false_green": pr_opened and not fix_correct,
    }


@pytest.mark.asyncio
async def test_e2e_gate2_on_seeded_bugs(monkeypatch) -> None:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "TRUE":
        pytest.skip(
            "E2E eval calls live Gemini on Vertex AI — set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
            "(plus GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION=global) to run it"
        )
    scenario_dirs = sorted(
        d for d in FIXTURES_DIR.iterdir() if (d / "scenario.json").exists()
    )
    results = []
    for rep in range(N_REPS):
        for i, scenario_dir in enumerate(scenario_dirs):
            scenario = json.loads((scenario_dir / "scenario.json").read_text())
            results.append(await _run_scenario(monkeypatch, scenario_dir, scenario, i + 1))

    failed = [r["id"] for r in results if r["terminal"] not in ("pr_open", "escalated")]
    assert not failed, f"scenarios did not reach a terminal state: {failed}"

    report, sidecar = _build_report(results)
    REPORT_PATH.write_text(report)
    SIDECAR_PATH.write_text(json.dumps(sidecar, indent=2))
    print(f"\n{report}")


def _build_report(results: list[dict]) -> tuple[str, dict]:
    n = len(results)
    verified_correct = sum(1 for r in results if r["pipeline_success"])
    false_green = sum(1 for r in results if r["false_green"])
    escalated = sum(1 for r in results if r["terminal"] == "escalated")
    routing_correct = sum(1 for r in results if r["routing_correct"])
    mean_attempts = sum(r["n_attempts"] for r in results) / n

    # Verification-vs-oracle agreement on attempts where the model actually judged (visible
    # tests passed — a red test run short-circuits to green=False without a model call).
    judged = [
        (attempt["heldout_passed"], verdict)
        for r in results
        for attempt, verdict in zip(r["attempts"], r["verdicts"])
        if attempt["visible_passed"]
    ]
    verification_agreement = (
        sum(1 for heldout_ok, green in judged if heldout_ok == green) / len(judged)
        if judged else None
    )

    lines = [
        "# End-to-end Gate 2 eval report (SWE-bench-mini)",
        "",
        (f"Generated: {datetime.now(timezone.utc).isoformat()} — {n} scenario runs "
         f"({len({r['id'] for r in results})} fixtures x {N_REPS} reps), live Gemini for every "
         "agent, real coding agent on local fixture repos, externals faked."),
        "",
        "## Headline metrics",
        "",
        f"- **Verified-correct rate (PR opened AND held-out oracle passes):** {verified_correct / n:.1%}",
        f"- **False-green rate (PR opened but oracle REJECTS the fix):** {false_green / n:.1%}",
        f"- **Escalation rate (pipeline gave up):** {escalated / n:.1%}",
        f"- **Routing exact-match:** {routing_correct / n:.1%}",
        f"- **Verification-vs-oracle agreement (model-judged attempts):** {_pct(verification_agreement)}",
        f"- **Mean attempts per scenario:** {mean_attempts:.1f}",
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Routing | Attempts | Terminal | Oracle (final) | Outcome |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        routing = "✓" if r["routing_correct"] else f"✗ ({'+'.join(r['predicted_domains'])})"
        oracle = "pass" if r["fix_correct"] else "FAIL"
        if r["pipeline_success"]:
            outcome = "verified-correct"
        elif r["false_green"]:
            outcome = "FALSE GREEN"
        else:
            outcome = "escalated"
        lines.append(
            f"| {r['id']} | {routing} | {r['n_attempts']} | {r['terminal']} | {oracle} | {outcome} |"
        )
    lines.append("")

    sidecar = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_runs": n,
        "n_reps": N_REPS,
        "verified_correct_rate": verified_correct / n,
        "false_green_rate": false_green / n,
        "escalation_rate": escalated / n,
        "routing_exact_match": routing_correct / n,
        "verification_agreement": verification_agreement,
        "mean_attempts": mean_attempts,
        "per_scenario": results,
    }
    return "\n".join(lines), sidecar


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"
