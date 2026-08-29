"""Unit tests for the Verification Agent (Phase 3.5 DoD). A red test run must short-circuit to
green=false WITHOUT ever calling the model — a red test run can never be verified green regardless
of what the model would say. Stubs the underlying model for the green-path call only."""

import pytest

from artisan_agents import event_context
from artisan_agents.agents import verification_agent as verification_agent_module
from artisan_agents.agents.verification_agent import run_verification
from artisan_shared.event_log import NoOpEventSink
from artisan_shared.models import ExecutionResult, Plan
from tests.conftest import FakeLlm

_PLAN = Plan(steps=["do the thing"], touched_files=["a.py"], test_cases=["t1"], doc_updates=["d1"])


@pytest.mark.asyncio
async def test_failed_tests_short_circuits_to_not_green_without_calling_model(monkeypatch) -> None:
    calls = []

    class _ExplodingLlm(FakeLlm):
        async def generate_content_async(self, *args, **kwargs):
            calls.append(1)
            raise AssertionError("model must not be called when tests_passed is False")
            yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(verification_agent_module.verification_agent, "model", _ExplodingLlm())

    result = ExecutionResult(
        branch="artisan/ART-1", diff_summary="x", tests_passed=False, logs_uri="gs://logs/1"
    )
    verdict = await run_verification(
        plan=_PLAN, execution_result=result, issue_title="Title", issue_body="Body"
    )
    assert verdict.green is False
    assert verdict.feedback is not None
    assert calls == []


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"

    def child(self, **kwargs):
        return self


@pytest.mark.asyncio
async def test_short_circuit_still_emits_an_agent_completed_event() -> None:
    sink = _RecordingSink()
    event_context.set_sink(sink)

    result = ExecutionResult(
        branch="artisan/ART-1", diff_summary="x", tests_passed=False, logs_uri="gs://logs/1"
    )
    await run_verification(plan=_PLAN, execution_result=result, issue_title="Title", issue_body="Body")

    assert len(sink.events) == 1
    assert sink.events[0]["type"] == "agent_completed"
    assert "skipped" in sink.events[0]["summary"]


@pytest.mark.asyncio
async def test_passed_tests_and_matching_diff_is_verified_green(monkeypatch) -> None:
    monkeypatch.setattr(
        verification_agent_module.verification_agent,
        "model",
        FakeLlm(response_text='{"green": true}'),
    )
    result = ExecutionResult(
        branch="artisan/ART-1", diff_summary="changed button color to blue", tests_passed=True,
        logs_uri="gs://logs/1",
    )
    verdict = await run_verification(
        plan=_PLAN, execution_result=result, issue_title="Title", issue_body="Body"
    )
    assert verdict.green is True


@pytest.mark.asyncio
async def test_passed_tests_but_mismatched_diff_is_not_green(monkeypatch) -> None:
    monkeypatch.setattr(
        verification_agent_module.verification_agent,
        "model",
        FakeLlm(response_text='{"green": false, "feedback": "diff does not address the issue"}'),
    )
    result = ExecutionResult(
        branch="artisan/ART-1", diff_summary="unrelated refactor", tests_passed=True,
        logs_uri="gs://logs/1",
    )
    verdict = await run_verification(
        plan=_PLAN, execution_result=result, issue_title="Title", issue_body="Body"
    )
    assert verdict.green is False
    assert verdict.feedback
