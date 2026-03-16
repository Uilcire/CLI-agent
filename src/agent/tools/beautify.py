"""Beautify text using an LLM for clearer, more human-readable output."""

from agent.config.settings import load_settings
from agent.llm.client import create_client

BEAUTIFY_PROMPT = """Rewrite the following text to be clearer and more human-readable. Preserve all factual content.
Use shorter sentences, better structure, and clearer formatting where helpful.
Output only the rewritten text, no meta-commentary."""


def beautify(
    text: str,
    client=None,
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """
    Use an LLM to reformat text into a more human-readable form.

    Args:
        text: Raw text to beautify.
        client: Optional OpenAI/Azure client. If None, loads settings and creates one.
        model: Model name (required if client is provided from external source).
        max_tokens: Max tokens for the beautify completion.

    Returns:
        Beautified text, or original text on error.
    """
    if not text or not text.strip():
        return text

    try:
        if client is None:
            settings = load_settings()
            client = create_client(settings)
            model = settings.model

        if not model:
            return text

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BEAUTIFY_PROMPT},
                {"role": "user", "content": text},
            ],
            max_completion_tokens=min(max_tokens, 4096),
        )
        result = (response.choices[0].message.content or "").strip()
        return result if result else text
    except Exception:
        return text
