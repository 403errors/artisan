"""Gate 2's coding step (MILESTONE.md Phase 3.4): a bounded ADK agent with file/shell tools that
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

import shlex
import subprocess
import uuid
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from artisan_execution_sandbox.config import GEMINI_MODEL_ID, MAX_CODING_AGENT_TOOL_CALLS
from artisan_shared.event_log import EventSink, NoOpEventSink
from artisan_shared.models import Plan
from artisan_shared.prompt_safety import UNTRUSTED_CONTENT_NOTICE, wrap_untrusted

APP_NAME = "artisan-execution-coding-agent"
_USER_ID = "artisan-execution-sandbox"

CODING_INSTRUCTION = """You are Artisan's coding agent, working inside a cloned git checkout on a \
fresh branch. You will be given an implementation plan: an ordered list of steps, files you're \
expected to touch, test cases to add/update, documentation to update, and any code the plan \
identifies as stale and safe to remove. Use `read_file`, `write_file`, `list_directory`, and \
`run_shell_command` to carry out every step of the plan against the files on disk, including \
writing the test cases, updating the documentation, and deleting the stale code the plan calls \
for. Never run `git commit`, `git push`, or modify git remotes yourself — committing and pushing \
happen outside your control, after you finish. When you have completed every step of the plan, \
call `finish` exactly once with a short summary of what you changed, and stop."""

CODING_INSTRUCTION = CODING_INSTRUCTION + "\n\n" + UNTRUSTED_CONTENT_NOTICE

#: Fail-closed allowlist for `run_shell_command` (Sprint 7 WS2) — replaces a bypassable blocklist
#: of forbidden git subcommands with an explicit allowlist of permitted top-level commands, since
#: issue text flows issue -> Plan -> this agent's prompt -> a tool with shell-command access, and a
#: blocklist can always be defeated (aliasing, quoting tricks, etc.) in a way an allowlist can't.
_ALLOWED_COMMANDS = {"npm", "pnpm", "python", "python3", "pytest", "node", "yarn"}
_ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "add", "log", "show", "checkout"}


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
        a quick syntax check. Only an allowlisted set of commands is permitted (npm/pnpm/python/
        python3/pytest/node/yarn, plus a narrow set of read-only/staging git subcommands); git
        commit/push/remote and any other command are not permitted here and happen outside your
        control after you finish."""
        _tick()
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"error: could not parse command: {exc}"

        if not argv:
            return "error: empty command"

        if argv[0] == "git":
            if len(argv) < 2 or argv[1] not in _ALLOWED_GIT_SUBCOMMANDS:
                return "error: command not permitted"
        elif argv[0] not in _ALLOWED_COMMANDS:
            return "error: command not permitted"

        result = subprocess.run(
            argv, shell=False, cwd=str(workdir), capture_output=True, text=True, timeout=120
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
    steps = "\n".join(f"- {s}" for s in plan.steps)
    touched_files = ", ".join(plan.touched_files) or "(unspecified)"
    test_cases = "\n".join(f"- {t}" for t in plan.test_cases)
    doc_updates = "\n".join(f"- {d}" for d in plan.doc_updates)
    removed_code = (
        "\n".join(
            f"- {item.file} — {item.symbol} ({item.reason})" for item in plan.removed_code
        )
        or "(none)"
    )
    prompt = (
        f"Steps:\n{wrap_untrusted(steps)}\n\n"
        f"Files you're expected to touch: {wrap_untrusted(touched_files)}\n\n"
        f"Test cases to add/update:\n{wrap_untrusted(test_cases)}\n\n"
        f"Documentation to update:\n{wrap_untrusted(doc_updates)}\n\n"
        "Code to remove (this change makes it stale — delete it as part of this work):\n"
        f"{wrap_untrusted(removed_code)}"
    )
    if prior_feedback:
        prompt += (
            f"\n\nPRIOR ATTEMPT FEEDBACK (address this explicitly):\n{wrap_untrusted(prior_feedback)}"
        )
    return prompt


def _preview_args(args: dict | None) -> str:
    if not args:
        return ""
    parts = []
    for key, value in args.items():
        text = str(value)
        if len(text) > 60:
            text = text[:60] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


async def _run_bounded_agent(
    *, workdir: Path, instruction: str, prompt: str, model: str | object, sink: EventSink | None = None
) -> str:
    """Shared ADK Runner/session boilerplate behind both `run_coding_agent` (Gate 2) and
    `run_conflict_resolution_agent` (Gate 3) — only the instruction/prompt differ; the tool set,
    tool-call cap, and session wiring are identical for both.

    Sprint 6: translates each streamed ADK event into a `tool_call` event on `sink`, using
    `event.get_function_calls()`/`get_function_responses()` (confirmed present and their exact
    behavior in the installed google-adk==2.8.0: `llm_response.py:196-212`). `event.partial` frames
    are skipped — they're streaming deltas ADK's own session services never persist either. A
    tool's result is patched onto the SAME event doc as its call, correlated by
    `FunctionCall.id`/`FunctionResponse.id` (ADK sets the response id to mirror the call's id, so a
    pair is always both-present or both-absent — never a silent mismatch); if `id` is ever absent,
    the result becomes its own standalone event instead of being lost."""
    sink = sink or NoOpEventSink()
    tools, finished = _build_tools(workdir)
    agent = Agent(
        model=model,
        name="coding_agent",
        instruction=instruction,
        tools=tools,
    )

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=_USER_ID, session_id=str(uuid.uuid4())
    )
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    pending: dict[str, str] = {}  # FunctionCall.id -> this call's event doc id

    try:
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=session.id, new_message=message
        ):
            if event.partial:
                continue

            for call in event.get_function_calls():
                doc_id = await sink.emit(
                    type="tool_call",
                    tool_name=call.name,
                    tool_args=call.args or {},
                    summary=f"{call.name}({_preview_args(call.args)})",
                )
                if call.id and doc_id:
                    pending[call.id] = doc_id

            for response in event.get_function_responses():
                # ADK wraps a non-dict tool return as {"result": <value>} (functions.py:1615-1616)
                # — every coding-agent tool returns str/list[str], so this is always the shape.
                raw = (response.response or {}).get("result", response.response)
                doc_id = pending.pop(response.id, None) if response.id else None
                if doc_id:
                    await sink.patch(doc_id, tool_result_summary=str(raw))
                else:
                    await sink.emit(
                        type="tool_call",
                        tool_name=response.name,
                        tool_result_summary=str(raw),
                        summary=f"{response.name} result",
                    )
    except ToolCallLimitExceeded as exc:
        # Previously silently swallowed — a real failure that should be visible, not just capped.
        await sink.emit(type="error", summary=str(exc))

    return finished.get("summary", "(coding agent did not call finish)")


async def run_coding_agent(
    *,
    workdir: Path,
    plan: Plan,
    prior_feedback: str | None = None,
    model: str | object = GEMINI_MODEL_ID,
    sink: EventSink | None = None,
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
    return await _run_bounded_agent(
        workdir=workdir,
        instruction=CODING_INSTRUCTION,
        prompt=_build_prompt(plan, prior_feedback),
        model=model,
        sink=sink,
    )


CONFLICT_RESOLUTION_INSTRUCTION = """You are Artisan's coding agent, resolving a real git merge \
conflict inside a cloned checkout (Gate 3, MILESTONE.md Phase 4.3 — this attempt was already \
classified "trivial" by the Conflict Agent, so a sensible reconciliation is expected to exist). \
You will be given the conflicted file paths and their literal contents, including the \
<<<<<<</=======/>>>>>>> conflict markers. Use `read_file`, `write_file`, `list_directory`, and \
`run_shell_command` to reconcile each conflicted file: keep BOTH sides' intended changes where \
they don't truly overlap, remove every conflict marker, and leave each file in a coherent, \
syntactically valid state. Never run `git commit`, `git push`, or modify git remotes yourself — \
those happen outside your control, after you finish. When every conflicted file is resolved, \
call `finish` exactly once with a short summary of how you reconciled them, and stop."""


def _build_conflict_resolution_prompt(conflicted_files: list[str], conflict_markers: str) -> str:
    return (
        f"Conflicted files: {', '.join(conflicted_files)}\n\n"
        f"Conflict markers:\n{conflict_markers}"
    )


async def run_conflict_resolution_agent(
    *,
    workdir: Path,
    conflicted_files: list[str],
    conflict_markers: str,
    model: str | object = GEMINI_MODEL_ID,
    sink: EventSink | None = None,
) -> str:
    """Gate 3's conflict-resolution coding step (MILESTONE.md Phase 4.3) — reuses the exact same
    bounded tool set/cap as `run_coding_agent`, with a conflict-specific instruction/prompt instead
    of a `Plan`'s steps."""
    return await _run_bounded_agent(
        workdir=workdir,
        instruction=CONFLICT_RESOLUTION_INSTRUCTION,
        prompt=_build_conflict_resolution_prompt(conflicted_files, conflict_markers),
        model=model,
        sink=sink,
    )
