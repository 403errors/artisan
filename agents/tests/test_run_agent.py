"""Unit tests for `run_structured`'s Sprint 6 event-log wrap — every Gate 2/3 reasoning agent
(routing, domain-expert, planning, verification, conflict-classification, and Gate 1's intake
agent since its Sprint 6 refactor) funnels through this one function."""

import pytest
from artisan_agents import event_context
from artisan_agents.agents._run_agent import run_structured
from artisan_agents.config import GEMINI_MODEL_ID
from artisan_shared.event_log import NoOpEventSink
from google.adk import Agent
from pydantic import BaseModel

from tests.conftest import FakeLlm


class _Verdict(BaseModel):
    ok: bool


class _RecordingSink(NoOpEventSink):
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True
        self.events: list[dict] = []
        self.children: list[_RecordingSink] = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)
        return f"doc-{len(self.events)}"

    def child(self, **kwargs):
        child = _RecordingSink()
        self.children.append(child)
        return child


@pytest.mark.asyncio
async def test_run_structured_emits_invoked_then_completed_on_a_child_sink_named_for_the_agent() -> (
    None
):
    parent_sink = _RecordingSink()
    event_context.set_sink(parent_sink)

    agent = Agent(
        model=GEMINI_MODEL_ID,
        name="fake_agent",
        instruction="x",
        output_schema=_Verdict,
        output_key="verdict",
    )
    agent.model = FakeLlm(response_text='{"ok": true}')

    result = await run_structured(
        agent=agent, app_name="test-app", output_key="verdict", output_model=_Verdict, prompt="go"
    )

    assert result.ok is True
    assert parent_sink.events == []  # emitted on the child, not the parent, sink
    assert len(parent_sink.children) == 1
    child = parent_sink.children[0]
    assert [e["type"] for e in child.events] == ["agent_invoked", "agent_completed"]
    assert "fake_agent" in child.events[0]["summary"]
    assert '"ok":true' in child.events[1]["detail"]
