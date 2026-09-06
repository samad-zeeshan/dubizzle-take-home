"""
Gemini or any OpenAI-compatible server through LiteLLM: lazy import, flat tool schemas, rate limits, fallback.

litellm takes about ten seconds to import and tries to fetch a price table
from GitHub unless told otherwise, so the import happens on first use and the
local table is forced. A 429 carries a retryDelay that is honoured once. A
local server such as LM Studio is reached by passing api_base on each call.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from dubizzle_assistant.services.llm.base import LLMError, LLMResponse, RateLimitedError, ToolCall

_RETRY_RE = re.compile(
    r"retry(?:Delay|\s+in|\s+after)[\"']?\s*[:=]?\s*[\"']?(\d+(?:\.\d+)?)\s*s", re.I
)
_DAILY_RE = re.compile(r"per[_ ]day|daily|PerDay|RequestsPerDay|quota_exceeded", re.I)


class LiteLLMClient:
    name = "litellm"

    def __init__(
        self,
        model: str,
        api_key: str | None,
        *,
        api_base: str | None = None,
        api_base_key: str | None = None,
        local: bool = False,
        max_tokens: int | None = None,
        fallback_model: str | None = None,
        embedding_model: str = "gemini/gemini-embedding-001",
        max_retry_wait: float = 20.0,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.embedding_model = embedding_model
        self.max_retry_wait = max_retry_wait
        self.api_base = api_base
        self.local = local
        self.max_tokens = max_tokens
        # The openai-compatible path insists on a non-empty key even when the server ignores it.
        self.api_base_key = api_base_key or ("lm-studio" if api_base else None)
        if api_key:
            os.environ["GEMINI_API_KEY"] = api_key
        os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        self._litellm: Any = None

    def _lib(self) -> Any:
        if self._litellm is None:
            import litellm

            litellm.suppress_debug_info = True
            litellm.drop_params = (
                True  # Gemini rejects parallel_tool_calls and a few OpenAI-only knobs
            )
            self._litellm = litellm
        return self._litellm

    def _endpoint(self, model: str) -> dict[str, Any]:
        # Only the local model goes to api_base; a Gemini fallback still needs the real endpoint.
        if self.api_base and not model.startswith("gemini/"):
            return {"api_base": self.api_base, "api_key": self.api_base_key}
        return {}

    def _call(self, model: str, kwargs: dict[str, Any]) -> Any:
        litellm = self._lib()
        try:
            return litellm.completion(model=model, **kwargs, **self._endpoint(model))
        except litellm.RateLimitError as e:  # type: ignore[attr-defined]
            text = str(e)
            m = _RETRY_RE.search(text)
            raise RateLimitedError(
                "model rate limit hit",
                retry_after=float(m.group(1)) if m else None,
                daily=bool(_DAILY_RE.search(text)),
            ) from e
        except litellm.AuthenticationError as e:  # type: ignore[attr-defined]
            raise LLMError(
                "The model endpoint rejected the API key. Check GEMINI_API_KEY or LLM_API_KEY in .env."
            ) from e
        except litellm.BadRequestError as e:  # type: ignore[attr-defined]
            raise LLMError(f"The model rejected the request: {e}") from e
        except litellm.APIConnectionError as e:  # type: ignore[attr-defined]
            where = self.api_base or "the model provider"
            raise LLMError(
                f"could not reach {where}. Is the server running with a model loaded? {str(e)[:200]}"
            ) from e
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"model call failed: {type(e).__name__}: {e}") from e

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        reasoning: str = "low",
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        model: str | None = None,
        purpose: str = "chat",
    ) -> LLMResponse:
        use_model = model or self.model
        kwargs: dict[str, Any] = {"messages": messages, "num_retries": 0}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": response_schema, "strict": False},
            }
        if reasoning and not self.local:
            kwargs["reasoning_effort"] = reasoning  # a Gemini knob; local servers may reject it
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        note = None
        start = time.monotonic()
        try:
            resp = self._call(use_model, kwargs)
        except RateLimitedError as e:
            if e.daily or e.retry_after is None or e.retry_after > self.max_retry_wait:
                raise
            time.sleep(e.retry_after + 0.5)
            note = f"retried once after {e.retry_after}s rate limit"
            resp = self._call(use_model, kwargs)
        except LLMError as e:
            if response_schema and "response_format" in kwargs and "schema" in str(e).lower():
                # Some models reject json_schema mode; plain text plus the post-filter still works.
                kwargs.pop("response_format")
                note = "model rejected json schema mode, fell back to text"
                resp = self._call(use_model, kwargs)
            else:
                raise
        latency = int((time.monotonic() - start) * 1000)

        choice = resp.choices[0]
        msg = choice.message
        raw = msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
        calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            fn = tc.function
            try:
                args = json.loads(fn.arguments) if fn.arguments else {}
            except json.JSONDecodeError:
                args = {"_raw": fn.arguments}
            calls.append(ToolCall(id=tc.id, name=fn.name, arguments=args))
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=msg.content if isinstance(msg.content, str) else None,
            tool_calls=calls,
            finish_reason=str(choice.finish_reason or ""),
            usage={
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            },
            raw_message=raw,
            model=use_model,
            latency_ms=latency,
            note=note,
        )

    def embed_many(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """Batched embeddings for the one-time corpus build; about a dozen calls for the whole inventory."""
        litellm = self._lib()
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            try:
                resp = litellm.embedding(
                    model=self.embedding_model,
                    input=texts[i : i + batch_size],
                    **self._endpoint(self.embedding_model),
                )
            except Exception as e:  # noqa: BLE001
                raise LLMError(f"embedding call failed: {type(e).__name__}: {e}") from e
            out.extend(
                list(item["embedding"])
                for item in sorted(resp.data, key=lambda d: d.get("index", 0))
            )
        return out

    def embed(self, text: str) -> list[float]:
        litellm = self._lib()
        try:
            out = litellm.embedding(
                model=self.embedding_model, input=[text], **self._endpoint(self.embedding_model)
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"embedding call failed: {type(e).__name__}: {e}") from e
        return list(out.data[0]["embedding"])
