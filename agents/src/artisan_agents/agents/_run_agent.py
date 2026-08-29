"""Shared boilerplate for running a stateless ADK `Agent` once and reading back its structured
output. Factored out because `intake_agent.py`'s five-step shape (fresh session -> build message ->
drain runner -> re-fetch session -> validate output_key into a Pydantic model) is repeated
identically by every Gate 2 reasoning agent (routing, domain-expert, planning, verification, per
MILESTONE.md Phase 3.1-3.3/3.5). Every call is a fresh, isolated session — Firestore, not agent
memory, is the state authority (SYSTEM_DESIGN.md §7)."""

import uuid
from typing import TypeVar

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from artisan_agents.event_context import current_sink

T = TypeVar("T", bound=BaseModel)

_USER_ID = "artisan-orchestrator"


async def run_structured(
    *, agent: Agent, app_name: str, output_key: str, output_model: type[T], prompt: str
) -> T:
    """Runs `agent` once against `prompt` in a fresh session and validates
    `final_session.state[output_key]` into `output_model`.

    Sprint 6: emits `agent_invoked`/`agent_completed` around the call. No ADK event-stream
    interception needed here — these agents use `output_schema`/`output_key` with no `tools`, so
    per ADK 2.8.0's own dispatch logic the structured result never arrives as a function call, only
    as plain `content.parts[].text` that ADK itself folds into `session.state[output_key]`. The
    completion summary is derived from the already-validated Pydantic result instead, which is
    deterministic and sidesteps that entirely."""
    sink = current_sink().child(actor=agent.name)
    await sink.emit(type="agent_invoked", summary=f"{agent.name} invoked")

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name, user_id=_USER_ID, session_id=str(uuid.uuid4())
    )
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for _event in runner.run_async(
        user_id=_USER_ID, session_id=session.id, new_message=message
    ):
        pass
    final_session = await session_service.get_session(
        app_name=app_name, user_id=_USER_ID, session_id=session.id
    )
    result = output_model.model_validate(final_session.state[output_key])

    await sink.emit(
        type="agent_completed",
        summary=f"{agent.name} completed",
        detail=result.model_dump_json(),
    )
    return result
