"""Tests for the bounded coding-agent loop (Phase 3.4). Stubs the model with a fake `BaseLlm` that
either behaves (writes a file, then finishes) or misbehaves (always requests another tool call) —
never calls live Gemini. The tool-call ceiling test is the key safety-net case: a stuck model must
terminate at the cap instead of hanging past the job's own execution timeout."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from artisan_execution_sandbox.coding_agent import run_coding_agent
from artisan_execution_sandbox.config import MAX_CODING_AGENT_TOOL_CALLS
from artisan_shared.models import Plan

_PLAN = Plan(
    steps=["Create hello.txt with a greeting"],
    touched_files=["hello.txt"],
    test_cases=[],
    doc_updates=[],
)


class _ScriptedLlm(BaseLlm):
    model: str = "fake"
    step: int = 0

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.step += 1
        if self.step == 1:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id=str(uuid.uuid4()),
                                name="write_file",
                                args={"path": "hello.txt", "content": "hi\n"},
                            )
                        )
                    ],
                )
            )
        elif self.step == 2:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id=str(uuid.uuid4()),
                                name="finish",
                                args={"summary": "wrote hello.txt"},
                            )
                        )
                    ],
                )
            )
        else:
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="done")])
            )


class _AlwaysRequestsAnotherToolCallLlm(BaseLlm):
    model: str = "fake"

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            id=str(uuid.uuid4()),
                            name="run_shell_command",
                            args={"command": "echo still going"},
                        )
                    )
                ],
            )
        )


@pytest.mark.asyncio
async def test_well_behaved_agent_writes_file_and_finishes(tmp_path) -> None:
    summary = await run_coding_agent(workdir=tmp_path, plan=_PLAN, model=_ScriptedLlm())

    assert summary == "wrote hello.txt"
    assert (tmp_path / "hello.txt").read_text() == "hi\n"


@pytest.mark.asyncio
async def test_stuck_model_terminates_at_the_tool_call_ceiling_instead_of_hanging(tmp_path) -> None:
    summary = await run_coding_agent(
        workdir=tmp_path, plan=_PLAN, model=_AlwaysRequestsAnotherToolCallLlm()
    )

    # Never called `finish`, so no summary was ever recorded — but crucially, this line is
    # reached at all, proving the loop terminated rather than running forever.
    assert summary == "(coding agent did not call finish)"


@pytest.mark.asyncio
async def test_forbidden_git_commands_are_rejected_by_the_shell_tool(tmp_path) -> None:
    from artisan_execution_sandbox.coding_agent import _build_tools

    tools, _finished = _build_tools(tmp_path)
    run_shell_command = next(t for t in tools if t.__name__ == "run_shell_command")

    result = run_shell_command("git commit -am 'sneaky'")
    assert "not permitted" in result
