"""Manual benchmark runner — Artisan pipeline vs. a frozen 50-instance benchmark set.

    uv run --package artisan-agents python agents/evals/bench/runner.py --benchmark swebench-verified --limit 5
    uv run --package artisan-agents python agents/evals/bench/runner.py --benchmark swebench-verified   # full 50

NEVER runs in CI: every instance is a live Gemini pipeline run (routing -> domain experts ->
planning -> coding agent -> verification) against a real repository checkout. Externals are
faked exactly like the E2E mini-bench (in-memory Firestore, stubbed GitHub/Jira, local executor
in place of the Cloud Run Job) — the agents and control flow are the real production ones.

Requirements (preflight-checked, fails fast):
  - GOOGLE_GENAI_USE_VERTEXAI=TRUE + GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION=global
  - Docker running — instance test environments come from the benchmarks' official images
    (SWE-bench family: sweb.eval.x86_64.<instance_id>; Pro: per-row dockerhub_tag). The coding
    agent edits a HOST checkout; tests run in the container with the checkout bind-mounted over
    /testbed. On Apple Silicon the x86_64 images run under emulation (slow but functional).

Output per benchmark (under bench_runs/<benchmark>/):
  - predictions.jsonl — SWE-bench prediction format ({"instance_id", "model_name_or_path",
    "model_patch"}), one line per attempted instance. RESUMABLE: already-present instance_ids
    are skipped on re-run, so a crashed/limited run continues where it stopped.
  - run_log.json — per-instance pipeline detail (routing, attempts, verdicts, terminal state).

Grading is NOT done here: predictions.jsonl feeds each benchmark's OFFICIAL harness (see
README.md) — Artisan-generated patches, benchmark-owned containers and grading, so the headline
number is externally credible.

Cost caps: --limit N (first N frozen instances), --max-attempts (verification/retry loop cap,
default 2), per-instance test timeout. A full 50-instance run is roughly 50 x (1..max-attempts)
live coding-agent runs — start with --limit 2 to smoke-test.
"""

import argparse
import asyncio
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry import BENCHMARKS, Benchmark

SELECTED_DIR = Path(__file__).resolve().parent / "selected"
RUNS_DIR = Path(__file__).resolve().parent / "bench_runs"
REPO_CACHE = Path(__file__).resolve().parent / ".cache" / "repos"
MODEL_NAME = "artisan-v2"
TEST_TIMEOUT_S = 900

_MANIFEST_NAMES = (
    "pyproject.toml", "setup.py", "setup.cfg", "package.json", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "pubspec.yaml",
)


# ----------------------------------------------------------------------------- preflight

def require_env() -> None:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "TRUE":
        sys.exit(
            "Bench runs call live Gemini on Vertex AI — set GOOGLE_GENAI_USE_VERTEXAI=TRUE "
            "(plus GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION=global)."
        )
    if shutil.which("docker") is None or subprocess.run(
        ["docker", "info"], capture_output=True, check=False
    ).returncode != 0:
        sys.exit(
            "Docker is required for benchmark test environments but isn't running.\n"
            "Install: `brew install --cask docker` (or colima), start it, re-run.\n"
            "The benchmarks' official images are x86_64 — on Apple Silicon they run under "
            "emulation; expect slow test runs."
        )


# ----------------------------------------------------------------------------- docker images

def image_for(benchmark: Benchmark, instance: dict) -> str:
    """Official per-instance environment image (all verified against Docker Hub 2026-09).

    Conventions differ per benchmark:
    - SWE-bench Verified/Multilingual: swebench/sweb.eval.x86_64.<id with __->_1776_>:latest
    - SWE-bench-Live: same naming but under the starryzhang org
    - SWE-bench Pro: single repo jefzda/sweap-images, per-instance dockerhub_tag as the TAG
    """
    if benchmark.key == "swebench-pro":
        tag = instance["extra"].get("dockerhub_tag")
        if not tag:
            raise RuntimeError(f"{instance['instance_id']}: no dockerhub_tag in frozen row")
        return f"jefzda/sweap-images:{tag}"
    if benchmark.key in ("swebench-verified", "swebench-multilingual", "swebench-live"):
        org = "starryzhang" if benchmark.key == "swebench-live" else "swebench"
        hub_name = instance["instance_id"].replace("__", "_1776_")
        return f"{org}/sweb.eval.x86_64.{hub_name}:latest"
    raise NotImplementedError(
        f"{benchmark.key}: no prebuilt per-instance images — its official harness builds "
        "environments from per-instance Dockerfiles. See README.md for the grading path; "
        "runner support for this benchmark is a follow-up."
    )


def ensure_image(image: str) -> None:
    if subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, check=False
    ).returncode == 0:
        return
    print(f"    pulling {image} ...", flush=True)
    result = subprocess.run(
        ["docker", "pull", "--platform", "linux/amd64", image],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker pull failed for {image}: {result.stderr[-500:]}")


# ----------------------------------------------------------------------------- repo checkouts

def checkout_repo(repo: str, base_commit: str, dest: Path) -> None:
    """Cached clone + cheap per-instance worktree at the base commit."""
    cache = REPO_CACHE / repo.replace("/", "__")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"    cloning {repo} (cached for future instances)...", flush=True)
        _run(["git", "clone", "--filter=blob:none", f"https://github.com/{repo}.git", str(cache)])
    _run(["git", "-C", str(cache), "fetch", "origin", base_commit], check=False)  # promisor fetch
    # Per-instance worktrees live in tempdirs — prune entries whose dirs were already deleted.
    _run(["git", "-C", str(cache), "worktree", "prune"], check=False)
    _run(["git", "-C", str(cache), "worktree", "add", "--detach", str(dest), base_commit])


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr[-500:]}")
    return result


# ----------------------------------------------------------------------------- test signal

def patch_test_files(test_patch: str) -> list[str]:
    """Test FILE PATHS touched by the oracle test patch. Used only to scope the pipeline's
    internal test signal (a dev running 'tests near the change') — patch CONTENT is never
    shown to any agent, and the pre-patch versions of these files are what actually run."""
    files = []
    for match in re.finditer(r"^\+\+\+ b/(.+)$", test_patch, re.MULTILINE):
        path = match.group(1)
        if re.search(r"(^|/)(test|tests|testing|spec)", path) and not path.endswith(".pyc"):
            files.append(path)
    return files


def internal_test_command(benchmark: Benchmark, instance: dict) -> str:
    extra = instance.get("extra") or {}
    if extra.get("test_cmds"):  # SWE-bench-Live ships per-instance commands
        return " && ".join(extra["test_cmds"])
    if extra.get("test_command"):  # SWE-PolyBench
        return extra["test_command"]
    files = patch_test_files(instance["test_patch"])
    if not files:
        return "python -m pytest -x -q"
    return "python -m pytest -x -q " + " ".join(shlex.quote(f) for f in files)


def run_tests_in_container(image: str, workdir: Path, command: str) -> tuple[bool, str]:
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--platform", "linux/amd64",
            "-v", f"{workdir}:/testbed",
            "--entrypoint", "bash",
            image, "-lc",
            f"cd /testbed && (source /opt/miniconda3/bin/activate testbed 2>/dev/null || true) && {command}",
        ],
        capture_output=True, text=True, check=False, timeout=TEST_TIMEOUT_S,
    )
    return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


# ----------------------------------------------------------------------------- pipeline stubs

class _FakeTicketStore:
    """In-memory Firestore double with a configurable retry cap (cost control)."""

    def __init__(self, repo: str, issue_number: int, max_attempts: int) -> None:
        from artisan_shared.firestore_schema import TicketDoc

        now = datetime.now(timezone.utc)
        self.max_attempts = max_attempts
        self.doc = TicketDoc(
            github_issue_number=issue_number, github_repo=repo, jira_key=f"BENCH-{issue_number}",
            status="in_progress", created_at=now, updated_at=now,
        )

    def ticket_doc_id(self, repo: str, issue_number: int) -> str:
        return f"{repo}__{issue_number}"

    async def get_ticket(self, repo: str, issue_number: int):
        return self.doc

    async def update_ticket(self, repo: str, issue_number: int, **fields) -> None:
        self.doc = self.doc.model_copy(update=fields)

    async def increment_retry_round(self, repo: str, issue_number: int) -> int:
        from artisan_agents.gcp.firestore_client import RetryCapExceeded

        new_count = self.doc.retry_count + 1
        if new_count >= self.max_attempts:
            self.doc = self.doc.model_copy(update={"retry_count": new_count, "status": "escalated"})
            raise RetryCapExceeded("bench attempt cap reached")
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


def _build_repo_context(workdir: Path, repo: str, head_sha: str):
    from artisan_shared.models import RepoContext

    files = sorted(
        str(p.relative_to(workdir))
        for p in workdir.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(workdir).parts
    )
    manifests = {name: (workdir / name).read_text() for name in _MANIFEST_NAMES if (workdir / name).exists()}
    languages: dict[str, int] = {}
    for rel in files:
        ext = Path(rel).suffix
        if ext:
            languages[ext] = languages.get(ext, 0) + 1
    return RepoContext(
        repo=repo, head_sha=head_sha, file_tree=files, manifests=manifests,
        languages=languages, fetched_at=datetime.now(timezone.utc),
    )


@contextmanager
def stubbed_externals(store: _FakeTicketStore, repo_context, executor):
    """Same fakes as the E2E mini-bench, without pytest's monkeypatch."""
    from artisan_agents import gate2
    from artisan_agents.gcp import firestore_client
    from artisan_shared.event_log import NoOpEventSink

    swaps = []

    def swap(obj, name, value):
        swaps.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    async def fake_default_branch(_repo):
        return "main"

    async def fake_open_pr(_repo, *, head, base, title, body):
        return 1, "https://bench.local/pr/1"

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_get_repo_context(_repo):
        return repo_context

    for name in ("get_ticket", "update_ticket", "increment_retry_round", "append_escalation",
                 "write_pr_pointer", "append_trace_id"):
        swap(firestore_client, name, getattr(store, name))
    swap(firestore_client, "ticket_doc_id", store.ticket_doc_id)
    swap(firestore_client, "new_event_sink", lambda *a, **k: NoOpEventSink())
    swap(gate2.github_client, "get_default_branch", fake_default_branch)
    swap(gate2.github_client, "open_pull_request", fake_open_pr)
    swap(gate2.github_client, "post_issue_comment", fake_noop)
    swap(gate2.github_client, "add_label", fake_noop)
    swap(gate2.jira_client, "add_comment", fake_noop)
    swap(gate2.jira_client, "add_label", fake_noop)
    swap(gate2.repo_context_module, "get_repo_context", fake_get_repo_context)
    swap(gate2.cloud_run_jobs, "trigger_execution", executor)
    try:
        yield
    finally:
        for obj, name, original in reversed(swaps):
            setattr(obj, name, original)


# ----------------------------------------------------------------------------- per-instance run

async def run_instance(benchmark: Benchmark, instance: dict, *, max_attempts: int) -> dict:
    from artisan_agents import gate2
    from artisan_execution_sandbox.coding_agent import run_coding_agent
    from artisan_shared.models import ExecutionResult

    iid = instance["instance_id"]
    image = image_for(benchmark, instance)
    ensure_image(image)

    repo = instance["repo"]
    issue_number = abs(hash(iid)) % 90000 + 1
    store = _FakeTicketStore(repo, issue_number, max_attempts)
    attempts: list[dict] = []
    test_cmd = internal_test_command(benchmark, instance)

    async def executor(*, repo, issue_number, branch, plan, attempt, feedback) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="artisan-bench-") as tmp:
            workdir = Path(tmp) / "repo"
            checkout_repo(repo, instance["base_commit"], workdir)
            summary = await run_coding_agent(workdir=workdir, plan=plan, prior_feedback=feedback)
            _run(["git", "-C", str(workdir), "add", "-A"])
            patch = _run(["git", "-C", str(workdir), "diff", "--cached", instance["base_commit"]]).stdout
            if not patch.strip():
                attempts.append({"attempt": attempt, "changes": False, "tests_passed": False,
                                 "patch": "", "summary": summary})
                return ExecutionResult(
                    branch=branch, diff_summary=f"coding agent made no changes. Summary: {summary}",
                    tests_passed=False, logs_uri="bench-local",
                )
            tests_ok, test_out = run_tests_in_container(image, workdir, test_cmd)
            attempts.append({"attempt": attempt, "changes": True, "tests_passed": tests_ok,
                             "patch": patch, "summary": summary, "test_output_tail": test_out[-500:]})
            return ExecutionResult(
                branch=branch, diff_summary=f"{summary}\n\n{len(patch)} patch bytes",
                tests_passed=tests_ok, logs_uri="bench-local",
            )

    # RepoContext from a throwaway checkout (the executor makes its own per attempt).
    with tempfile.TemporaryDirectory(prefix="artisan-bench-ctx-") as tmp:
        ctx_dir = Path(tmp) / "repo"
        checkout_repo(repo, instance["base_commit"], ctx_dir)
        repo_context = _build_repo_context(ctx_dir, repo, instance["base_commit"])

        title = instance["problem_statement"].strip().splitlines()[0][:120] if instance["problem_statement"] else iid
        started = time.time()
        with stubbed_externals(store, repo_context, executor):
            await gate2.start_gate2(
                repo, issue_number, f"BENCH-{issue_number}",
                issue_title=title, issue_body=instance["problem_statement"],
            )

    final_patch = attempts[-1]["patch"] if attempts else ""
    last_attempt_log = (
        {k: v for k, v in attempts[-1].items() if k != "patch"} if attempts else {}
    )
    return {
        "instance_id": iid,
        "repo": repo,
        "terminal": store.doc.status,
        "pr_opened": store.doc.status == "pr_open",
        "n_attempts": len(attempts),
        "duration_s": round(time.time() - started, 1),
        "patch": final_patch,
        # detail for run_log (patch stripped to keep the log readable)
        "log": {**last_attempt_log, "domains": store.doc.domains},
    }


# ----------------------------------------------------------------------------- main

def load_selected(benchmark: Benchmark) -> list[dict]:
    path = SELECTED_DIR / f"{benchmark.key}.json"
    if not path.exists():
        sys.exit(f"No frozen selection at {path} — run select_instances.py --benchmark {benchmark.key} first.")
    return json.loads(path.read_text())["instances"]


def load_done(predictions_path: Path) -> set[str]:
    if not predictions_path.exists():
        return set()
    return {json.loads(line)["instance_id"] for line in predictions_path.read_text().splitlines() if line.strip()}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--benchmark", required=True, choices=sorted(BENCHMARKS))
    parser.add_argument("--limit", type=int, default=None, help="only the first N frozen instances")
    parser.add_argument("--max-attempts", type=int, default=2, help="verification/retry loop cap per instance")
    args = parser.parse_args()

    require_env()
    benchmark = BENCHMARKS[args.benchmark]
    instances = load_selected(benchmark)[: args.limit]

    out_dir = RUNS_DIR / benchmark.key
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / "predictions.jsonl"
    log_path = out_dir / "run_log.json"

    done = load_done(predictions_path)
    todo = [i for i in instances if i["instance_id"] not in done]
    print(f"{benchmark.key}: {len(done)} already attempted, {len(todo)} to run "
          f"(max {args.max_attempts} attempts each).", flush=True)

    log = json.loads(log_path.read_text()) if log_path.exists() else {}
    for n, instance in enumerate(todo, 1):
        iid = instance["instance_id"]
        print(f"[{n}/{len(todo)}] {iid}", flush=True)
        try:
            result = await run_instance(benchmark, instance, max_attempts=args.max_attempts)
        except Exception as exc:  # one bad instance must not kill a 50-instance run
            print(f"    FAILED: {exc}", flush=True)
            log[iid] = {"instance_id": iid, "terminal": "runner_error", "error": str(exc)[:500]}
            log_path.write_text(json.dumps(log, indent=2))
            continue
        with predictions_path.open("a") as fh:
            fh.write(json.dumps({
                "instance_id": iid,
                "model_name_or_path": MODEL_NAME,
                "model_patch": result["patch"],
            }) + "\n")
        log[iid] = {k: v for k, v in result.items() if k != "patch"} | result["log"]
        log_path.write_text(json.dumps(log, indent=2))
        print(f"    -> {result['terminal']} after {result['n_attempts']} attempt(s), "
              f"{result['duration_s']}s, patch {len(result['patch'])} bytes", flush=True)

    print(f"\nDone. Predictions: {predictions_path}")
    print("Grade with the benchmark's OFFICIAL harness — see README.md.")


if __name__ == "__main__":
    asyncio.run(main())
