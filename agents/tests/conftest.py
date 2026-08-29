"""Shared test fixtures. `FakeLlm` mirrors test_intake_agent.py's stubbing approach (a minimal
fake `BaseLlm` yielding one canned JSON response) so every Gate 2 reasoning-agent test can stub the
underlying model without ever calling live Gemini."""

from collections.abc import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from artisan_agents import event_context
from artisan_agents.gcp import firestore_client
from artisan_shared.event_log import NoOpEventSink


@pytest.fixture(autouse=True)
def _no_real_event_sink(monkeypatch):
    """dispatch.evaluate_intake/gate2.start_gate2/gate3.start_gate3 each construct a real
    EventSink via firestore_client.new_event_sink, which would otherwise try to write to the real
    artisan-multiagent-ai Firestore database on every test run (this environment has live ADC
    credentials). Autouse so no test can forget this and accidentally perform a live write."""
    monkeypatch.setattr(firestore_client, "new_event_sink", lambda *args, **kwargs: NoOpEventSink())


@pytest.fixture(autouse=True)
def _no_duplicate_check(monkeypatch):
    """Gate 1's duplicate check (dispatch.evaluate_intake) would hit the live GitHub Search API +
    Gemini on every issue-opened test — stub it to return no candidates by default so no test
    performs live calls. Duplicate-flow tests override `dispatch.run_duplicate_check` /
    `dispatch.run_duplicate_confirm` with their own fakes."""
    from artisan_agents import dispatch

    async def _no_candidates(**kwargs):
        return []

    async def _must_stub_confirm(**kwargs):
        raise AssertionError("run_duplicate_confirm must be stubbed in duplicate-review tests")

    monkeypatch.setattr(dispatch, "run_duplicate_check", _no_candidates)
    monkeypatch.setattr(dispatch, "run_duplicate_confirm", _must_stub_confirm)


@pytest.fixture(autouse=True)
def _reset_ambient_event_sink():
    """The event-sink ContextVar isn't reset between sync pytest test functions on its own — a
    test that installs its own sink (e.g. to record emitted events) would otherwise leak it into
    whichever test runs next. Reset to the safe default both before and after every test."""
    event_context.set_sink(NoOpEventSink())
    yield
    event_context.set_sink(NoOpEventSink())


class FakeLlm(BaseLlm):
    model: str = "fake"
    response_text: str = ""

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.response_text)])
        )
