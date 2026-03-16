"""Shared OpenAI/AzureOpenAI client factory."""

from openai import AzureOpenAI, OpenAI

from agent.config.settings import Settings


def create_client(settings: Settings):
    """
    Create OpenAI or AzureOpenAI client based on settings.backend.

    ByteDance: Use AzureOpenAI with endpoint + ?ak=KEY (auth via query param).
    Tested: https://search.bytedance.net/gpt/openapi/online/v2/crawl
    """
    if settings.backend == "bytedance":
        base = settings.gpt_endpoint.rstrip("/").split("?")[0]
        endpoint = f"{base}?ak={settings.api_key}"
        return AzureOpenAI(
            api_key=settings.api_key,
            api_version=settings.gpt_api_version,
            azure_endpoint=endpoint,
        )
    return OpenAI(api_key=settings.api_key)
