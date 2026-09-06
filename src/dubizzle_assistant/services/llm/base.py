"""
The seam between the agent loop and any language model.

The loop talks to this protocol only. Behind it sit the LiteLLM client, a
rule-based stand-in for offline runs, and a cassette that records or replays
either one, so every test and demo can run without a key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: dict[str, int]
    # The provider's own message object, replayed verbatim so thought signatures survive.
    raw_message: dict[str, Any]
    model: str
    latency_ms: int
    cassette_hit: bool = False
    note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.text and self.text.strip()) and not self.tool_calls


class LLMError(RuntimeError):
    """The model could not be called or answered unusably."""


class RateLimitedError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None, daily: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily


class LLMClient(Protocol):
    name: str
    model: str

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
    ) -> LLMResponse: ...

    def embed(self, text: str) -> list[float]: ...


def tool_result_message(call_id: str, name: str, content: Any) -> dict[str, Any]:
    body = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, default=str)
    )
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": body}


def assistant_message(resp: LLMResponse) -> dict[str, Any]:
    """The message to append to history. Prefer the provider's raw object; fall back to a plain one."""
    if resp.raw_message:
        msg = dict(resp.raw_message)
        msg.setdefault("role", "assistant")
        if msg.get("content") is None and not msg.get("tool_calls"):
            msg["content"] = resp.text or ""
        return msg
    msg: dict[str, Any] = {"role": "assistant", "content": resp.text or ""}
    if resp.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in resp.tool_calls
        ]
    return msg


def estimate_tokens(text: str) -> int:
    # Four characters per token is close enough for a budget display; real counts come from usage.
    return max(1, len(text) // 4)
