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
from collections.abc import Callable
from typing import Any, NoReturn

from dubizzle_assistant.services.llm.base import LLMError, LLMResponse, RateLimitedError, ToolCall

_RETRY_RE = re.compile(
    r"retry(?:Delay|\s+in|\s+after)[\"']?\s*[:=]?\s*[\"']?(\d+(?:\.\d+)?)\s*s", re.I
)
_DAILY_RE = re.compile(r"per[_ ]day|daily|PerDay|RequestsPerDay|quota_exceeded", re.I)

# The corpus build is a one-off, so it can afford to wait out a per-minute limit.
_EMBED_MAX_WAIT = 90.0

# Wordings seen when a provider refuses a reply schema, usually next to function tools.
_SCHEMA_REJECT = ("schema", "mime type", "response_format", "structured output")


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
        embedding_dimensions: int | None = None,
        # Gemini's free tier asks for 23 to 29 seconds under load; a 20 second ceiling
        # turned every one of those into a failed turn.
        max_retry_wait: float = 45.0,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
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

    def _raise_mapped(self, e: Exception) -> NoReturn:
        litellm = self._lib()
        text = str(e)
        # A 429 raised inside a stream, or during a fallback hop, arrives under a different class
        # with the original body stapled on. Reading the text keeps the retryDelay and the retry
        # instead of surfacing a quota pause as a dead turn.
        mid = getattr(litellm, "MidStreamFallbackError", None)
        if (
            isinstance(e, litellm.RateLimitError)  # type: ignore[attr-defined]
            or (mid is not None and isinstance(e, mid))
            or "RateLimitError" in text
            or "RESOURCE_EXHAUSTED" in text
        ):
            m = _RETRY_RE.search(text)
            raise RateLimitedError(
                "model rate limit hit",
                retry_after=float(m.group(1)) if m else None,
                daily=bool(_DAILY_RE.search(text)),
            ) from e
        if isinstance(e, litellm.AuthenticationError):  # type: ignore[attr-defined]
            raise LLMError(
                "The model endpoint rejected the API key. Check GEMINI_API_KEY or LLM_API_KEY in .env."
            ) from e
        if isinstance(e, litellm.BadRequestError):  # type: ignore[attr-defined]
            raise LLMError(f"The model rejected the request: {e}") from e
        if isinstance(e, litellm.APIConnectionError):  # type: ignore[attr-defined]
            where = self.api_base or "the model provider"
            raise LLMError(
                f"could not reach {where}. Is the server running with a model loaded? {str(e)[:200]}"
            ) from e
        raise LLMError(f"model call failed: {type(e).__name__}: {e}") from e

    def _call(self, model: str, kwargs: dict[str, Any]) -> Any:
        litellm = self._lib()
        try:
            return litellm.completion(model=model, **kwargs, **self._endpoint(model))
        except Exception as e:  # noqa: BLE001
            self._raise_mapped(e)

    def _stream(self, model: str, kwargs: dict[str, Any], on_token: Callable[[str], None]) -> Any:
        """Forward text deltas as they arrive, then rebuild the full response so parsing stays shared."""
        litellm = self._lib()
        chunks: list[Any] = []
        try:
            for chunk in litellm.completion(
                model=model, **kwargs, **self._endpoint(model), stream=True
            ):
                chunks.append(chunk)
                choices = getattr(chunk, "choices", None) or []
                delta = getattr(choices[0], "delta", None) if choices else None
                text = getattr(delta, "content", None) if delta is not None else None
                if isinstance(text, str) and text:
                    on_token(text)
            if not chunks:
                raise LLMError("the model returned an empty stream")
            return litellm.stream_chunk_builder(chunks, messages=kwargs["messages"])
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            self._raise_mapped(e)

    def _kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        reasoning: str,
        response_schema: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
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
        # A per-call budget wins: one enrichment batch needs far more room than a chat turn,
        # and the shared ceiling exists to stop a small model looping inside a JSON grammar.
        if max_tokens or self.max_tokens:
            kwargs["max_tokens"] = max_tokens or self.max_tokens
        return kwargs

    def _run(
        self, kwargs: dict[str, Any], runner: Callable[[dict[str, Any]], Any]
    ) -> tuple[Any, str | None]:
        """One attempt, one retry after a short rate limit, one fallback out of json schema mode."""
        note = None
        try:
            resp = runner(kwargs)
        except RateLimitedError as e:
            if e.daily or e.retry_after is None or e.retry_after > self.max_retry_wait:
                raise
            time.sleep(e.retry_after + 0.5)
            note = f"retried once after {e.retry_after}s rate limit"
            resp = runner(kwargs)
        except LLMError as e:
            # Providers word this rejection differently. Gemini says "response mime type", never
            # "schema", so matching on one word alone let a 400 through as a dead turn.
            msg = str(e).lower()
            if "response_format" in kwargs and any(k in msg for k in _SCHEMA_REJECT):
                # Plain text plus the post-filter still works, so one retry beats failing the turn.
                kwargs.pop("response_format")
                note = "model rejected json schema mode, fell back to text"
                resp = runner(kwargs)
            else:
                raise
        return resp, note

    def _parse(self, resp: Any, use_model: str, latency: int, note: str | None) -> LLMResponse:
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
        max_tokens: int | None = None,
    ) -> LLMResponse:
        use_model = model or self.model
        kwargs = self._kwargs(
            messages,
            tools,
            reasoning=reasoning,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        start = time.monotonic()
        resp, note = self._run(kwargs, lambda kw: self._call(use_model, kw))
        return self._parse(resp, use_model, int((time.monotonic() - start) * 1000), note)

    def complete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        on_token: Callable[[str], None],
        reasoning: str = "low",
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        model: str | None = None,
        purpose: str = "chat",
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Like complete, but text deltas reach on_token while the model is still generating."""
        use_model = model or self.model
        kwargs = self._kwargs(
            messages,
            tools,
            reasoning=reasoning,
            response_schema=response_schema,
            temperature=temperature,
        )
        start = time.monotonic()
        resp, note = self._run(kwargs, lambda kw: self._stream(use_model, kw, on_token))
        out = self._parse(resp, use_model, int((time.monotonic() - start) * 1000), note)
        out.note = f"{out.note}; streamed" if out.note else "streamed"
        return out

    def _embedding_width(self) -> dict[str, Any]:
        # Asked for on both embedding paths, or a query would not match the stored matrix.
        if self.embedding_dimensions and not self.local:
            return {"dimensions": self.embedding_dimensions}
        return {}

    def _embed_batch(self, batch: list[str]) -> Any:
        litellm = self._lib()
        for attempt in range(2):
            try:
                return litellm.embedding(
                    model=self.embedding_model,
                    input=batch,
                    **self._embedding_width(),
                    **self._endpoint(self.embedding_model),
                )
            except Exception as e:  # noqa: BLE001
                m = _RETRY_RE.search(str(e))
                delay = float(m.group(1)) if m else None
                if attempt or delay is None or delay > _EMBED_MAX_WAIT:
                    raise LLMError(f"embedding call failed: {type(e).__name__}: {e}") from e
                time.sleep(delay + 1)
        raise LLMError("embedding call failed after one retry")

    def embed_many(
        self, texts: list[str], batch_size: int = 16, *, pause: float | None = None
    ) -> list[list[float]]:
        """Embeddings for the one-time corpus build, paced for a metered endpoint.

        Gemini embeds one input per request, so a batch of sixteen counts as sixteen
        against the per-minute cap rather than one, and the whole inventory overruns it
        if the batches go out back to back. A local server has no such cap.
        """
        wait = (0.0 if self.local else 8.0) if pause is None else pause
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            if i and wait:
                time.sleep(wait)
            resp = self._embed_batch(texts[i : i + batch_size])
            out.extend(
                list(item["embedding"])
                for item in sorted(resp.data, key=lambda d: d.get("index", 0))
            )
        return out

    def embed(self, text: str) -> list[float]:
        litellm = self._lib()
        try:
            out = litellm.embedding(
                model=self.embedding_model,
                input=[text],
                **self._embedding_width(),
                **self._endpoint(self.embedding_model),
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"embedding call failed: {type(e).__name__}: {e}") from e
        return list(out.data[0]["embedding"])
