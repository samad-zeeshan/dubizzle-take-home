"""Everything one chat turn needs in one place, handed to every tool handler."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dubizzle_assistant.config import Settings
from dubizzle_assistant.services.trace import TurnTrace


@dataclass
class TurnContext:
    settings: Settings
    conn: sqlite3.Connection
    user_id: str
    session_id: str
    turn: int
    trace: TurnTrace
    now: datetime
    request_id: str = ""
    shown: list[dict[str, Any]] = field(default_factory=list)
    focus_id: str | None = None
    pending_booking: dict[str, Any] | None = None
    new_cards: list[dict[str, Any]] = field(default_factory=list)
    memory_writes: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    embedder: Callable[[str], list[float]] | None = None
    user_name: str | None = None
    raw_message: str = ""
    locale: str = "en"
    # True when the customer plainly asked to see stock, which decides whether a result already
    # on screen is worth a card again.
    stock_request: bool = False
    on_token: Callable[[str], None] | None = None
    streamed_text: str | None = None

    def note_write(self, table: str, by: str, **detail: Any) -> None:
        self.memory_writes.append({"table": table, "by": by, **detail})
