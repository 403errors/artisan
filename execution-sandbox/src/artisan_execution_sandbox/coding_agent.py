"""Gate 2's coding step (SPRINT.md Phase 3.4): a bounded ADK agent with file/shell tools that
carries out a Plan's steps against a cloned repo checkout. Per docs/PRD.md §5's non-goal, this is
Artisan's own Gemini/ADK-driven coding capability — never a shelled-out external coding CLI.

Deliberately does NOT use ADK's built-in bash tool (`google.adk.tools.bash_tool.ExecuteBashTool`):
that tool unconditionally calls `tool_context.request_confirmation(...)` before every command with
no override to disable it (confirmed by reading its `run_async`), which would stall forever in
this unattended Cloud Run Job with no human present to approve. Plain Python functions passed via
`tools=[...]` are wrapped as `FunctionTool` with `require_confirmation=False` by default, so
custom tools are used here instead.

This agent does not use `output_schema`/`output_key` like the reasoning-only agents (routing,
domain-expert, planning, verification) — its real output is the diff it leaves on disk, captured
afterward via `git diff --stat` into `ExecutionResult.diff_summary`, not a single structured
verdict. That's a deliberate exception to "typed I/O only" (SPRINT.md cross-cutting rule 2), which
targets *inter-agent* exchange, not a tool-use side-effect loop like this one."""

import subprocess
import uuid
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from artisan_execution_sandbox.config import GEMINI_MODEL_ID, MAX_CODING_AGENT_TOOL_CALLS
from artisan_shared.models import Plan

APP_NAME = "artisan-execution-coding-agent"
_USER_ID = "artisan-execution-sandbox"

CODING_INSTRUCTION = """You are Artisan's coding agent, working inside a cloned git checkout on a \
fresh branch. You will be given an implementation plan: an ordered list of steps, files you're \
expected to touch, test cases to add/update, and documentation to update. Use `read_file`, \
`write_file`, `list_directory`, and `run_shell_command` to carry out every step of the plan \
against the files on disk, including writing the test cases and updating the documentation the \
plan calls for. Never run `git commit`, `git push`, or modify git remotes yourself — committing \
and pushing happen outside your control, after you finish. When you have completed every step of \
the plan, call `finish` exactly once with a short summary of what you changed, and stop."""

_FORBIDDEN_SHELL_SNIPPETS = ("git commit", "git push", "git remote")


class ToolCallLimitExceeded(Exception):
    """Raised when the coding agent exceeds MAX_CODING_AGENT_TOOL_CALLS without calling `finish`
    — a safety cap so a stuck model can't loop past the job's own execution timeout."""


def _build_tools(workdir: Path):
    call_count = 0
    finished: dict[str, str] = {}

    def _tick() -> None:
        nonlocal call_count
        call_count += 1
        if call_count > MAX_CODING_AGENT_TOOL_CALLS:
            raise ToolCallLimitExceeded(
                f"exceeded {MAX_CODING_AGENT_TOOL_CALLS} tool calls without calling finish"
            )

    def read_file(path: str) -> str:
        """Reads a file's contents, relative to the repo checkout root."""
        _tick()
        return (workdir / path).read_text()

    def write_file(path: str, content: str) -> str:
        """Writes (creating or overwriting) a file's contents, relative to the repo checkout
        root. Creates parent directories as needed."""
        _tick()
        target = workdir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"wrote {path}"

    def list_directory(path: str = ".") -> list[str]:
        """Lists entries in a directory, relative to the repo checkout root."""
        _tick()
        return sorted(p.name for p in (workdir / path).iterdir())

    def run_shell_command(command: str) -> str:
        """Runs a shell command with cwd set to the repo checkout root — e.g. to run a linter or
        a quick syntax check. Never use this for git commit/push/remote commands; those are not
        permitted here and happen outside your control after you finish."""
        _tick()
        if any(snippet in command for snippet in _FORBIDDEN_SHELL_SNIPPETS):
            return "error: git commit/push/remote are not permitted from this tool"
        result = subprocess.run(
            command, shell=True, cwd=str(workdir), capture_output=True, text=True, timeout=120
        )
        return f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    def finish(summary: str) -> str:
        """Call this exactly once, when every step of the plan is complete, with a short summary
        of what you changed."""
        finished["summary"] = summary
        return "done"

    tools = [read_file, write_file, list_directory, run_shell_command, finish]
    return tools, finished


def _build_prompt(plan: Plan, prior_feedback: str | None) -> str:
    prompt = (
        f"Steps:\n" + "\n".join(f"- {s}" for s in plan.steps) + "\n\n"
        f"Files you're expected to touch: {', '.join(plan.touched_files) or '(unspecified)'}\n\n"
        f"Test cases to add/update:\n" + "\n".join(f"- {t}" for t in plan.test_cases) + "\n\n"
        f"Documentation to update:\n" + "\n".join(f"- {d}" for d in plan.doc_updates)
    )
    if prior_feedback:
        prompt += f"\n\nPRIOR ATTEMPT FEEDBACK (address this explicitly):\n{prior_feedback}"
    return prompt


async def run_coding_agent(
    *, workdir: Path, plan: Plan, prior_feedback: str | None = None, model: str | object = GEMINI_MODEL_ID
) -> str:
    """Runs the bounded coding-agent loop against `workdir` (an already-cloned, already-branched
    repo checkout) and returns the agent's final summary string. If the tool-call cap is hit
    before the agent calls `finish`, returns whatever partial summary is available (there may be
    none) rather than raising — a capped-out coding attempt is a failed *attempt*, not a sandbox
    crash, and should still flow into `ExecutionResult`/verification like any other outcome.

    `model` defaults to the pinned Gemini model id, but accepts a `BaseLlm` instance instead —
    this `Agent` is built fresh per call (its tools close over this call's `workdir`), so unlike
    the module-level agent singletons in `agents/`, there's no persistent object whose `.model`
    tests can monkeypatch after construction; this parameter is that seam instead."""
    tools, finished = _build_tools(workdir)
    agent = Agent(
        model=model,
        name="coding_agent",
        instruction=CODING_INSTRUCTION,
        tools=tools,
    )

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=_USER_ID, session_id=str(uuid.uuid4())
    )
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=_build_prompt(plan, prior_feedback))])

    try:
        async for _event in runner.run_async(
            user_id=_USER_ID, session_id=session.id, new_message=message
        ):
            pass
    except ToolCallLimitExceeded:
        pass

    return finished.get("summary", "(coding agent did not call finish)")
