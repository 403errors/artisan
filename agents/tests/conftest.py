"""Shared test fixtures. `FakeLlm` mirrors test_intake_agent.py's stubbing approach (a minimal
fake `BaseLlm` yielding one canned JSON response) so every Gate 2 reasoning-agent test can stub the
underlying model without ever calling live Gemini."""

from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class FakeLlm(BaseLlm):
    model: str = "fake"
    response_text: str = ""

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.response_text)])
        )
