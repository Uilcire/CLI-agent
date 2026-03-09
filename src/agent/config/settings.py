"""Settings for the CLI agent. Loads config from environment variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Holds API key, model name, and max tokens. Loaded from env."""

    api_key: str
    model: str = "gpt-5-mini-2025-08-07"
    max_tokens: int = 4096


def load_settings() -> Settings:
    """
    Load .env file, read env vars, validate API key, and return Settings.

    Raises:
        ValueError: If OPENAI_API_KEY is missing or empty.
    """
    load_dotenv()

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Add it to .env or export it."
        )

    model = (
        os.environ.get("OPENAI_MODEL") or "gpt-5-mini-2025-08-07"
    ).strip()
    max_tokens_str = (os.environ.get("OPENAI_MAX_TOKENS") or "4096").strip()

    try:
        max_tokens = int(max_tokens_str)
    except ValueError:
        max_tokens = 4096

    return Settings(api_key=api_key, model=model, max_tokens=max_tokens)
