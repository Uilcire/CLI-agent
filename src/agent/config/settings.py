"""Settings for the CLI agent. Loads config from environment variables."""

import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """
    Holds API config for OpenAI, ByteDance GPT, or DeepSeek.

    - backend: "openai" | "bytedance" | "deepseek"
    - api_key: key for the chosen backend
    - model: model name
    - max_tokens: max completion tokens
    - For ByteDance: gpt_endpoint, gpt_api_version (optional overrides)
    - For DeepSeek: base_url (OpenAI-compatible endpoint)
    """

    backend: Literal["openai", "bytedance", "deepseek"]
    api_key: str
    model: str
    max_tokens: int
    gpt_endpoint: str = ""
    gpt_api_version: str = "2024-02-01"
    base_url: str = ""
    model_pro: str = ""
    model_flash: str = ""


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
    deepseek_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    use_bytedance_raw = os.environ.get("USE_BYTEDANCE")
    use_bytedance = _parse_bool(use_bytedance_raw) if use_bytedance_raw else None
    use_deepseek_raw = os.environ.get("USE_DEEPSEEK")
    use_deepseek = _parse_bool(use_deepseek_raw) if use_deepseek_raw else None

    # Determine backend: manual override or auto-detect.
    # Auto-detect priority: DeepSeek (default) → ByteDance → OpenAI.
    backend: Literal["openai", "bytedance", "deepseek"]
    if use_deepseek is True:
        if not deepseek_key:
            raise ValueError("USE_DEEPSEEK=true but DEEPSEEK_API_KEY is not set.")
        backend = "deepseek"
    elif use_bytedance is True:
        if not gpt_ak:
            raise ValueError("USE_BYTEDANCE=true but GPT_AK is not set.")
        backend = "bytedance"
    elif use_bytedance is False and use_deepseek is not False:
        if deepseek_key:
            backend = "deepseek"
        elif openai_key:
            backend = "openai"
        else:
            raise ValueError(
                "USE_BYTEDANCE=false but no DEEPSEEK_API_KEY or OPENAI_API_KEY set."
            )
    elif use_deepseek is False:
        if gpt_ak:
            backend = "bytedance"
        elif openai_key:
            backend = "openai"
        else:
            raise ValueError(
                "USE_DEEPSEEK=false but no GPT_AK or OPENAI_API_KEY set."
            )
    elif deepseek_key:
        backend = "deepseek"
    elif gpt_ak:
        backend = "bytedance"
    elif openai_key:
        backend = "openai"
    else:
        raise ValueError(
            "No API key configured. Set DEEPSEEK_API_KEY (DeepSeek), "
            "GPT_AK (ByteDance), or OPENAI_API_KEY (OpenAI) in .env."
        )

    # Set credentials and config for the chosen backend
    base_url = ""
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
    elif backend == "deepseek":
        api_key = deepseek_key
        model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-pro").strip()
        base_url = (
            os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        ).strip()
        gpt_endpoint = ""
        gpt_api_version = "2024-02-01"
        model_pro = (os.environ.get("DEEPSEEK_MODEL_PRO") or "deepseek-v4-pro").strip()
        model_flash = (
            os.environ.get("DEEPSEEK_MODEL_FLASH") or "deepseek-v4-flash"
        ).strip()
    else:
        api_key = openai_key
        model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
        gpt_endpoint = ""
        gpt_api_version = "2024-02-01"

    if backend != "deepseek":
        model_pro = ""
        model_flash = ""

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
        base_url=base_url,
        model_pro=model_pro,
        model_flash=model_flash,
    )
