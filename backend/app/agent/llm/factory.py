"""Builds the configured LLM provider (``LLM_PROVIDER``). SDKs are imported lazily."""

from __future__ import annotations

from app.agent.llm.base import LLMProvider
from app.config import Settings


def provider_from_settings(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        from app.agent.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider.from_settings(settings)
    from app.agent.llm.gemini_provider import GeminiProvider

    return GeminiProvider.from_settings(settings)
