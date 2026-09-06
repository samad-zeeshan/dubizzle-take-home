"""Model clients and the factory that picks one from settings."""

from __future__ import annotations

from collections.abc import Callable

from dubizzle_assistant.config import Settings
from dubizzle_assistant.services.llm.base import LLMClient


def build_llm(settings: Settings) -> LLMClient | None:
    """Mock, LiteLLM, or a cassette around either. None when chat cannot run at all."""
    inner: LLMClient | None = None
    if settings.llm_provider == "mock":
        from dubizzle_assistant.services.llm.mock_client import HeuristicLLM

        inner = HeuristicLLM()
    elif settings.gemini_api_key or settings.llm_local:
        from dubizzle_assistant.services.llm.litellm_client import LiteLLMClient

        inner = LiteLLMClient(
            settings.llm_model,
            settings.gemini_api_key,
            api_base=settings.llm_api_base,
            api_base_key=settings.llm_api_key,
            local=settings.llm_local,
            max_tokens=settings.effective_max_tokens,
            fallback_model=settings.usable_fallback_model,
            embedding_model=settings.embedding_model,
        )
    if settings.llm_cassette_mode != "off":
        from dubizzle_assistant.services.llm.cassette import CassetteClient

        if settings.llm_cassette_mode == "record" and inner is None:
            return None
        return CassetteClient(inner, settings.llm_cassette_path, settings.llm_cassette_mode)
    return inner


def build_embedder(
    settings: Settings, llm: LLMClient | None
) -> Callable[[str], list[float]] | None:
    if llm is None or settings.llm_provider == "mock":
        return None
    return llm.embed
