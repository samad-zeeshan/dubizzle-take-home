"""
Record and replay model calls, so the screenshot conversation runs offline.

A recording is keyed by a hash of everything that shapes the answer: model,
messages, tools, schema, reasoning, temperature. Replay serves the stored
response and fails loudly on a miss rather than guessing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dubizzle_assistant.services.llm.base import LLMClient, LLMError, LLMResponse, ToolCall
from dubizzle_assistant.services.trace import redact


class CassetteMissError(LLMError):
    """Replay mode had no recording for this call. Surfaces as a 503 with the reason."""


def _key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


class CassetteClient:
    name = "cassette"

    def __init__(self, inner: LLMClient | None, path: Path, mode: str) -> None:
        if mode not in ("record", "replay"):
            raise ValueError("cassette mode must be record or replay")
        if mode == "record" and inner is None:
            raise ValueError("recording needs a real client underneath")
        self.inner = inner
        self.path = path
        self.mode = mode
        self.model = inner.model if inner else "cassette"
        self._store: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._store[rec["key"]] = rec

    def _payload(self, kind: str, **fields: Any) -> dict[str, Any]:
        return {"kind": kind, **fields}

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
        # Keyed on the conversation only, so a recording made with one provider replays under another.
        payload = self._payload("complete", messages=messages, tools=tools, schema=response_schema)
        key = _key(payload)
        if key in self._store:
            rec = self._store[key]["response"]
            rec["tool_calls"] = [ToolCall(**tc) for tc in rec.get("tool_calls", [])]
            resp = LLMResponse(**rec)
            resp.cassette_hit = True
            return resp
        if self.mode == "replay":
            last_user = next(
                (m.get("content") for m in reversed(messages) if m.get("role") == "user"), ""
            )
            raise CassetteMissError(
                f"no recording for this call (purpose={purpose}, last user message={str(last_user)[:60]!r}). "
                f"Run the same conversation with LLM_CASSETTE_MODE=record first."
            )
        assert self.inner is not None
        resp = self.inner.complete(
            messages,
            tools,
            reasoning=reasoning,
            response_schema=response_schema,
            temperature=temperature,
            model=model,
            purpose=purpose,
        )
        self._write(key, payload, asdict(resp))
        return resp

    def embed(self, text: str) -> list[float]:
        payload = self._payload(
            "embed", text=text, model=getattr(self.inner, "embedding_model", "embed")
        )
        key = _key(payload)
        if key in self._store:
            return list(self._store[key]["response"]["vector"])
        if self.mode == "replay" or self.inner is None:
            raise CassetteMissError(f"no recorded embedding for {text[:40]!r}")
        vec = self.inner.embed(text)
        self._write(key, payload, {"vector": vec})
        return vec

    def _write(self, key: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
        # Contact details never enter a prompt, and redaction makes that a guarantee of the file too.
        last_user = next(
            (
                m.get("content")
                for m in reversed(payload.get("messages") or [])
                if m.get("role") == "user"
            ),
            None,
        )
        request = redact({k: v for k, v in payload.items() if k != "messages"})
        request["last_user"] = redact(last_user)
        rec = {"key": key, "request": request, "response": redact(response)}
        self._store[key] = rec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
