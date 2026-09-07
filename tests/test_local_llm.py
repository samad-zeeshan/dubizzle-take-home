"""Local endpoint wiring: settings, client kwargs, and error hints, without importing litellm."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dubizzle_assistant.config import Settings, gemini_generation
from dubizzle_assistant.services.llm import build_llm
from dubizzle_assistant.services.llm.base import LLMError
from dubizzle_assistant.services.llm.litellm_client import LiteLLMClient
from tests.conftest import make_settings

BASE = "http://localhost:1234/v1"


def local_settings(tmp: Path, **kw: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_provider": "litellm",
        "gemini_api_key": None,
        "llm_model": "openai/qwen/qwen3-4b-2507",
        "llm_api_base": BASE,
    }
    base.update(kw)
    return make_settings(tmp, **base)


def test_local_endpoint_counts_as_configured(tmp_path: Path) -> None:
    s = local_settings(tmp_path)
    assert s.llm_local and s.llm_configured
    # The default Gemini fallback is useless without a Gemini key, so it must vanish.
    assert s.usable_fallback_model is None
    assert s.temperature_for(s.llm_model) == 0.2
    assert s.effective_max_tokens == 1500
    assert s.use_structured_reply is False and s.use_brief_replies is True
    assert local_settings(tmp_path, structured_reply=True).use_structured_reply is True
    assert local_settings(tmp_path, llm_max_tokens=800).effective_max_tokens == 800
    gemini = make_settings(tmp_path, llm_provider="litellm", gemini_api_key="k")
    assert gemini.effective_max_tokens is None and gemini.use_structured_reply is True
    assert gemini.use_brief_replies is False
    assert (
        local_settings(tmp_path, gemini_api_key="k").usable_fallback_model
        == "gemini/gemini-3.1-flash-lite"
    )
    assert local_settings(tmp_path, llm_fallback_model="").usable_fallback_model is None


def test_reply_schema_only_on_gemini_3(tmp_path: Path) -> None:
    def gem(model: str, **kw: Any) -> Settings:
        return make_settings(
            tmp_path, llm_provider="litellm", gemini_api_key="k", llm_model=model, **kw
        )

    assert gem("gemini/gemini-3.5-flash-lite").use_structured_reply is True
    assert gem("gemini/gemini-3.1-flash-lite").use_structured_reply is True
    assert gem("gemini/gemini-2.5-flash-lite").use_structured_reply is False
    assert local_settings(tmp_path).use_structured_reply is False
    assert gem("gemini/gemini-2.5-flash-lite", structured_reply=True).use_structured_reply is True
    # A turn that fell back mid-flight has to ask about the model it actually reached.
    assert (
        gem("gemini/gemini-3.5-flash-lite").structured_reply_for("gemini/gemini-2.5-flash") is False
    )
    # Replay reports the recorded model, and the recording is keyed on the schema, so an
    # unrecognised name must not flip the flag or every cassette turn misses.
    assert gem("gemini/gemini-3.5-flash-lite").structured_reply_for("cassette") is True
    assert gemini_generation("gemini/gemini-3.5-flash-lite") == 3.5
    assert gemini_generation("gemini/gemini-embedding-001") is None
    assert gemini_generation("openai/qwen/qwen3-4b-2507") is None


def test_prefix_alone_marks_local(tmp_path: Path) -> None:
    s = make_settings(
        tmp_path, llm_provider="litellm", gemini_api_key=None, llm_model="lm_studio/qwen3"
    )
    assert s.llm_local and s.llm_configured


class FakeLiteLLM:
    class RateLimitError(Exception): ...

    class AuthenticationError(Exception): ...

    class BadRequestError(Exception): ...

    class APIConnectionError(Exception): ...

    suppress_debug_info = False
    drop_params = False

    def __init__(self, fail: Exception | None = None, *, once: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail
        self.once = once

    def completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.fail:
            err = self.fail
            if self.once:
                self.fail = None
            raise err
        msg = SimpleNamespace(content="ok", tool_calls=[], model_dump=lambda: {"content": "ok"})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
        )

    def embedding(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(data=[{"index": 0, "embedding": [0.1, 0.2]}])


def make_client(monkeypatch: pytest.MonkeyPatch, fake: FakeLiteLLM, **kw: Any) -> LiteLLMClient:
    c = LiteLLMClient(
        "openai/qwen/qwen3-4b-2507", None, api_base=BASE, local=True, max_tokens=1500, **kw
    )
    monkeypatch.setattr(c, "_lib", lambda: fake)
    return c


def test_client_routes_to_api_base_without_reasoning_knob(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLiteLLM()
    c = make_client(monkeypatch, fake, embedding_model="openai/nomic")
    r = c.complete([{"role": "user", "content": "hi"}], [{"type": "function"}], reasoning="low")
    sent = fake.calls[0]
    assert sent["api_base"] == BASE and sent["api_key"] == "lm-studio"
    assert "reasoning_effort" not in sent and sent["tool_choice"] == "auto"
    assert sent["max_tokens"] == 1500
    assert r.text == "ok"
    c.embed("x")
    assert fake.calls[1]["api_base"] == BASE


def test_gemini_fallback_skips_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLiteLLM()
    c = make_client(monkeypatch, fake)
    c.complete([{"role": "user", "content": "hi"}], None, model="gemini/gemini-3.1-flash-lite")
    assert "api_base" not in fake.calls[0]


def test_connection_error_names_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLiteLLM(fail=FakeLiteLLM.APIConnectionError("refused"))
    c = make_client(monkeypatch, fake)
    with pytest.raises(LLMError, match="localhost:1234"):
        c.complete([{"role": "user", "content": "hi"}], None)


def test_schema_rejection_retries_as_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gemini's wording for this 400 never contains the word "schema".
    refusal = FakeLiteLLM.BadRequestError(
        "Function calling with a response mime type: 'application/json' is unsupported"
    )
    fake = FakeLiteLLM(fail=refusal, once=True)
    c = make_client(monkeypatch, fake)
    r = c.complete(
        [{"role": "user", "content": "hi"}],
        [{"type": "function"}],
        response_schema={"type": "object"},
    )
    assert len(fake.calls) == 2
    assert "response_format" in fake.calls[0] and "response_format" not in fake.calls[1]
    assert r.text == "ok" and r.note is not None and "fell back to text" in r.note


def test_factory_builds_local_client(tmp_path: Path) -> None:
    llm = build_llm(local_settings(tmp_path, llm_api_key="abc"))
    assert isinstance(llm, LiteLLMClient)
    assert llm.api_base == BASE and llm.api_base_key == "abc" and llm.fallback_model is None
