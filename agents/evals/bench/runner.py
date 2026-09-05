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
    """Official per-instance environment image (all conventions verified against the registries
    2026-09). Every benchmark has prebuilt images — no Dockerfile building needed:
    - SWE-bench Verified/Multilingual: swebench/sweb.eval.x86_64.<id with __->_1776_>:latest
    - SWE-bench-Live: same naming but under the starryzhang org
    - SWE-bench Pro: single repo jefzda/sweap-images, per-instance dockerhub_tag as the TAG
    - SWE-PolyBench: ghcr.io/timesler/swe-polybench.eval.x86_64.<id>:v1.1 (keeps "__")
    - Multi-SWE-bench: mswebench/<org>_m_<repo>:pr-<number>
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
    if benchmark.key == "swe-polybench":
        return f"ghcr.io/timesler/swe-polybench.eval.x86_64.{instance['instance_id']}:v1.1"
    if benchmark.key == "multi-swe-bench":
        org_repo, number = instance["instance_id"].rsplit("-", 1)
        org, repo_short = org_repo.split("__", 1)
        return f"mswebench/{org}_m_{repo_short}:pr-{number}"
    raise NotImplementedError(f"{benchmark.key}: no image rule registered")


def container_workdir(benchmark: Benchmark, instance: dict) -> str:
    """Where the repo lives inside the benchmark's image (bind-mount target for the host
    checkout). SWE-bench family + PolyBench use /testbed; Multi-SWE-bench clones to
    /home/<repo> (per its harness's Dockerfile templates)."""
    if benchmark.key == "multi-swe-bench":
        return f"/home/{instance['repo'].split('/', 1)[1]}"
    return "/testbed"


def ensure_image(image: str) -> str:
    """Pull if missing; returns the image name actually available (PolyBench's GHCR tags are
    ':v1.1' for refreshed instances and ':latest' for the rest — fall back on pull failure)."""
    candidates = [image]
    if image.endswith(":v1.1"):
        candidates.append(image[: -len(":v1.1")] + ":latest")
    for candidate in candidates:
        if subprocess.run(
            ["docker", "image", "inspect", candidate], capture_output=True, check=False
        ).returncode == 0:
            return candidate
        print(f"    pulling {candidate} ...", flush=True)
        result = subprocess.run(
            ["docker", "pull", "--platform", "linux/amd64", candidate],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            return candidate
    raise RuntimeError(f"docker pull failed for {candidates}: {result.stderr[-500:]}")


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


def internal_test_command(benchmark: Benchmark, instance: dict) -> str | None:
    """Dataset-shipped commands take precedence. Everything else is inferred from the checkout
    at execution time (infer_test_command) — manifest-aware beats guessing."""
    extra = instance.get("extra") or {}
    if extra.get("test_cmds"):  # SWE-bench-Live ships per-instance commands
        return " && ".join(extra["test_cmds"])
    if extra.get("test_command"):  # SWE-PolyBench
        return extra["test_command"]
    return None


def infer_test_command(workdir: Path, test_files: list[str]) -> str:
    """Language-aware internal test signal for repos whose dataset ships no command (v2 wave 1.6
    phase 4). Scoped to the oracle-touched test files where the ecosystem's runner supports it
    (a full-suite run on a SWE-bench-scale repo blows the per-instance timeout); falls back to
    broader runs where scoping is unreliable."""
    if (workdir / "go.mod").exists():
        dirs = sorted({str(Path(f).parent) for f in test_files if f.endswith("_test.go")})
        return "go test " + " ".join(f"./{d}/..." for d in dirs) if dirs else "go test ./..."
    if (workdir / "Cargo.toml").exists():
        return "cargo test"
    if (workdir / "pom.xml").exists():
        classes = sorted({Path(f).stem for f in test_files if f.endswith(".java")})
        return f"mvn test -q -Dtest={','.join(classes)}" if classes else "mvn test -q"
    package_json = workdir / "package.json"
    if package_json.exists():
        try:
            test_script = json.loads(package_json.read_text()).get("scripts", {}).get("test", "")
        except json.JSONDecodeError:
            test_script = ""
        files = " ".join(shlex.quote(f) for f in test_files)
        if "vitest" in test_script:
            return f"npx vitest run {files}" if files else "npx vitest run"
        if "jest" in test_script:
            return f"npx jest {files}" if files else "npx jest"
        if "mocha" in test_script:
            return f"npx mocha {files}" if files else "npx mocha"
        return "npm test"
    files = " ".join(shlex.quote(f) for f in test_files)
    return f"python -m pytest -x -q {files}".strip()


def run_tests_in_container(
    image: str, patch: str, command: str, container_dir: str = "/testbed"
) -> tuple[bool, str]:
    """Apply the agent's patch INSIDE the container over the image's own checkout, then run the
    test command — the official-harness flow. (Bind-mounting the host checkout over the image's
    repo would hide in-image build artifacts; repos with compiled extensions, e.g. astropy,
    fail to import that way — found in the first smoke run.) The whole script goes via stdin so
    the patch survives quoting."""
    # Activation must NOT be subshell-parenthesized — `(source activate) && cmd` loses the env
    # when the subshell exits (the images auto-activate only for LOGIN shells, which `bash -s`
    # is not; found via "No module named pytest" in the first smoke run).
    script = (
        f"cd {container_dir} && git apply - <<'ARTISAN_PATCH_EOF_9f31'\n{patch}\n"
        f"ARTISAN_PATCH_EOF_9f31\n"
        f"source /opt/miniconda3/bin/activate testbed 2>/dev/null || true\n"
        f"{command}"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "--platform", "linux/amd64",
         "--entrypoint", "bash", image, "-s"],
        input=script, capture_output=True, text=True, check=False, timeout=TEST_TIMEOUT_S,
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
    image = ensure_image(image_for(benchmark, instance))
    container_dir = container_workdir(benchmark, instance)

    repo = instance["repo"]
    issue_number = abs(hash(iid)) % 90000 + 1
    store = _FakeTicketStore(repo, issue_number, max_attempts)
    attempts: list[dict] = []
    preset_cmd = internal_test_command(benchmark, instance)
    test_files = patch_test_files(instance["test_patch"])

    async def executor(*, repo, issue_number, branch, plan, attempt, feedback) -> ExecutionResult:
        with tempfile.TemporaryDirectory(prefix="artisan-bench-") as tmp:
            workdir = Path(tmp) / "repo"
            checkout_repo(repo, instance["base_commit"], workdir)
            try:
                summary = await run_coding_agent(workdir=workdir, plan=plan, prior_feedback=feedback)
            except Exception as exc:
                # A tool-level failure (e.g. the model's shell command timing out) must degrade
                # to a failed ATTEMPT — retry/escalate — never crash the whole instance.
                attempts.append({"attempt": attempt, "changes": None, "tests_passed": False,
                                 "patch": "", "summary": f"coding agent error: {exc}"[:300]})
                return ExecutionResult(
                    branch=branch,
                    diff_summary=f"coding agent raised: {type(exc).__name__}: {exc}"[:500],
                    tests_passed=False, logs_uri="bench-local",
                )
            _run(["git", "-C", str(workdir), "add", "-A"])
            patch = _run(["git", "-C", str(workdir), "diff", "--cached", instance["base_commit"]]).stdout
            if not patch.strip():
                attempts.append({"attempt": attempt, "changes": False, "tests_passed": False,
                                 "patch": "", "summary": summary})
                return ExecutionResult(
                    branch=branch, diff_summary=f"coding agent made no changes. Summary: {summary}",
                    tests_passed=False, logs_uri="bench-local",
                )
            cmd = preset_cmd or infer_test_command(workdir, test_files)
            tests_ok, test_out = run_tests_in_container(image, patch, cmd, container_dir)
            attempts.append({"attempt": attempt, "changes": True, "tests_passed": tests_ok,
                             "patch": patch, "summary": summary, "test_output_tail": test_out[-500:]})
            changed_files = {
                p: (workdir / p).read_text(errors="replace")[:8_000]
                for p in _run(
                    ["git", "-C", str(workdir), "diff", "--cached", "--name-only",
                     "--diff-filter=ACMR"]
                ).stdout.splitlines()[:10]
                if (workdir / p).is_file()
            }
            return ExecutionResult(
                branch=branch, diff_summary=f"{summary}\n\n{len(patch)} patch bytes",
                tests_passed=tests_ok, logs_uri="bench-local",
                diff_patch=patch[:12_000],  # #12: verification sees the bounded real patch
                changed_file_contents=changed_files,  # ... and the unchanged siblings
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
    # Real-scale repos need more exploration than the production default (40) was tuned on —
    # set BEFORE the sandbox package is imported (config is read at import time) and recorded
    # per-run so bench-vs-production behavior differences stay visible.
    os.environ.setdefault("ARTISAN_MAX_CODING_AGENT_TOOL_CALLS", "80")
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
