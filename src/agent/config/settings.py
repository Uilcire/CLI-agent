"""Settings for the CLI agent. Loads config from environment variables."""

import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """
    Holds API config for OpenAI or ByteDance GPT.

    - backend: "openai" or "bytedance" (chosen by env: GPT_AK → bytedance)
    - api_key: key for the chosen backend
    - model: model name
    - max_tokens: max completion tokens
    - For ByteDance: gpt_endpoint, gpt_api_version (optional overrides)
    """

    backend: Literal["openai", "bytedance"]
    api_key: str
    model: str
    max_tokens: int
    gpt_endpoint: str = ""
    gpt_api_version: str = "2024-02-01"


def _parse_bool(value: str) -> bool | None:
    """Parse USE_BYTEDANCE: 'true'/'1'/'yes' -> True, 'false'/'0'/'no' -> False, else None."""
    v = (value or "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def load_settings() -> Settings:
    """
    Load .env file, read env vars, choose backend, and return Settings.

    Backend selection (in order):
    - USE_BYTEDANCE=true → ByteDance (requires GPT_AK)
    - USE_BYTEDANCE=false → OpenAI (requires OPENAI_API_KEY)
    - Else auto-detect: GPT_AK set → ByteDance, else OpenAI

    Raises:
        ValueError: If no valid API key is found.
    """
    load_dotenv()

    gpt_ak = (os.environ.get("GPT_AK") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    use_bytedance_raw = os.environ.get("USE_BYTEDANCE")
    use_bytedance = _parse_bool(use_bytedance_raw) if use_bytedance_raw else None

    # Determine backend: manual override or auto-detect
    if use_bytedance is True:
        if not gpt_ak:
            raise ValueError("USE_BYTEDANCE=true but GPT_AK is not set.")
        backend: Literal["openai", "bytedance"] = "bytedance"
    elif use_bytedance is False:
        if not openai_key:
            raise ValueError("USE_BYTEDANCE=false but OPENAI_API_KEY is not set.")
        backend = "openai"
    elif gpt_ak:
        backend = "bytedance"
    elif openai_key:
        backend = "openai"
    else:
        raise ValueError(
            "No API key configured. Set either GPT_AK (ByteDance) or "
            "OPENAI_API_KEY (OpenAI) in .env or environment."
        )

    # Set credentials and config for the chosen backend
    if backend == "bytedance":
        api_key = gpt_ak
        model = (
            os.environ.get("GPT_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or "gpt-5.2-2025-12-11"
        ).strip()
        gpt_endpoint = (
            os.environ.get("GPT_ENDPOINT")
            or "https://search.bytedance.net/gpt/openapi/online/v2/crawl"
        ).strip()
        gpt_api_version = (
            os.environ.get("GPT_API_VERSION") or "2024-02-01"
        ).strip()
    else:
        api_key = openai_key
        model = (os.environ.get("OPENAI_MODEL") or "gpt-4o--mini").strip()
        gpt_endpoint = ""
        gpt_api_version = "2024-02-01"

    max_tokens_str = (os.environ.get("OPENAI_MAX_TOKENS") or "4096").strip()
    try:
        max_tokens = int(max_tokens_str)
    except ValueError:
        max_tokens = 4096

    return Settings(
        backend=backend,
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        gpt_endpoint=gpt_endpoint,
        gpt_api_version=gpt_api_version,
    )
