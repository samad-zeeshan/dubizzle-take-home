"""
Per-turn flight recorder: every stage of a chat turn, with timing and payload.

A trace is a by-product of work the turn does anyway. It is stored, returned
in the envelope, and shown in the client, so a reviewer can watch retrieval
and the model work instead of trusting prose. Redaction runs before storage
so a trace can never carry a key, a dealer's number, or a user's contact.
"""

from __future__ import annotations

import re
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from dubizzle_assistant.text import API_KEY_RE, EMAIL_RE, PHONE_RE

FORBIDDEN_KEYS = frozenset(
    {
        "dealer_contact",
        "dealer_contact_json",
        "description_raw",
        "description_original",
        "phone",
        "email",
        "gemini_api_key",
        "api_key",
        "authorization",
        "x-api-key",
    }
)

_KEY_HINT_RE = re.compile(r"(?i)(api[_-]?key|token(?!s)|secret|password|bearer)")


def redact(value: Any) -> Any:
    """Drop forbidden keys and scrub secrets and contact details from strings, recursively."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if _KEY_HINT_RE.search(str(k)) else redact(v))
            for k, v in value.items()
            if k not in FORBIDDEN_KEYS
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        out = API_KEY_RE.sub("[key]", value)
        out = EMAIL_RE.sub("[email]", out)
        out = PHONE_RE.sub("[phone]", out)
        return out
    return value


class TurnTrace:
    def __init__(
        self, session_id: str, turn: int, request_id: str, ablations: list[str] | None = None
    ) -> None:
        self.session_id = session_id
        self.turn = turn
        self.request_id = request_id
        self.ablations = list(ablations or [])
        self.stages: list[dict[str, Any]] = []
        self._t0 = time.monotonic()
        self.listeners: list[Any] = []

    def _emit(self, record: dict[str, Any]) -> None:
        self.stages.append(record)
        for fn in self.listeners:
            fn(record)

    def add(self, stage_name: str, ms: int = 0, **payload: Any) -> dict[str, Any]:
        record = {
            "stage": stage_name,
            "at_ms": int((time.monotonic() - self._t0) * 1000),
            "ms": ms,
            **payload,
        }
        self._emit(record)
        return record

    @contextmanager
    def stage(self, stage_name: str, **payload: Any) -> Generator[dict[str, Any]]:
        """Time a block. Anything the block puts into the yielded dict lands in the record."""
        record: dict[str, Any] = {
            "stage": stage_name,
            "at_ms": int((time.monotonic() - self._t0) * 1000),
            **payload,
        }
        start = time.monotonic()
        try:
            yield record
        finally:
            record["ms"] = int((time.monotonic() - start) * 1000)
            self._emit(record)

    def find(self, stage_name: str) -> list[dict[str, Any]]:
        return [s for s in self.stages if s["stage"] == stage_name]

    def to_dict(self) -> dict[str, Any]:
        return redact(
            {
                "session_id": self.session_id,
                "turn": self.turn,
                "request_id": self.request_id,
                "stages": self.stages,
                "ablations_active": self.ablations,
                "total_ms": int((time.monotonic() - self._t0) * 1000),
            }
        )

    def label(self, record: dict[str, Any]) -> str:
        """Short human line for the live event stream."""
        s = record["stage"]
        if s == "prefilter":
            return (
                "checked message"
                if record.get("result") == "passed"
                else f"declined by rule {record.get('rule')}"
            )
        if s == "resolver":
            return (
                f"resolved '{record.get('input')}' to {record.get('resolved')}"
                if record.get("resolved")
                else "nothing to resolve"
            )
        if s == "llm_call":
            return f"model call {record.get('n')} ({record.get('model')})"
        if s == "tool":
            name = record.get("name")
            if name == "search_inventory":
                counts = record.get("stage_counts") or {}
                last = list(counts.items())[-1] if counts else None
                return (
                    f"searched inventory: {last[1]} matches"
                    + (f", relaxed {record.get('relaxed')}" if record.get("relaxed") else "")
                    if last
                    else "searched inventory"
                )
            return f"ran {name}"
        if s == "grounding":
            return (
                f"grounding check: {record.get('grounded')}/{record.get('checked')} figures sourced"
            )
        if s == "reply":
            return "composed reply"
        return s.replace("_", " ")
