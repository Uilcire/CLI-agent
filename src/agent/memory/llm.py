"""LLM client abstraction for non-streaming completion (digest, merge)."""

from typing import Protocol

from agent.config.settings import Settings
from agent.core.loop import _create_client


class LLMClient(Protocol):
    """Protocol for LLM completion. Caller handles timeout via threading."""

    def complete(self, system: str, user: str) -> str:
        """Run a non-streaming completion. Returns model response text."""
        ...


class RealLLMClient:
    """Uses OpenAI/AzureOpenAI via agent.core.loop._create_client."""

    def __init__(self, settings: Settings) -> None:
        self._client = _create_client(settings)
        self._model = settings.model

    def complete(self, system: str, user: str) -> str:
        """Call chat completions (non-streaming). Returns content or empty string."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        return response.choices[0].message.content or ""


class MockLLMClient:
    """Returns a fixed response. Used in tests."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system: str, user: str) -> str:
        """Return the stored response unconditionally."""
        return self._response
