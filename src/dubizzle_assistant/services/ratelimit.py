"""Fixed-window counters in SQLite, per user and per client address, minute and day."""

from __future__ import annotations

import sqlite3
from datetime import datetime


def _bump(conn: sqlite3.Connection, scope: str, window: str, limit: int) -> tuple[bool, int]:
    with conn:
        conn.execute(
            "INSERT INTO rate_counters (scope, window_start, count) VALUES (?,?,1) "
            "ON CONFLICT(scope, window_start) DO UPDATE SET count = count + 1",
            (scope, window),
        )
        count = int(
            conn.execute(
                "SELECT count FROM rate_counters WHERE scope = ? AND window_start = ?",
                (scope, window),
            ).fetchone()[0]
        )
    return count <= limit, count


def check(
    conn: sqlite3.Connection,
    now: datetime,
    *,
    user_id: str,
    client_ip: str | None,
    per_min: int,
    per_day: int,
) -> str | None:
    """Return a human message when a limit is exceeded, else None. Counts the request either way."""
    minute = now.strftime("%Y-%m-%dT%H:%M")
    day = now.strftime("%Y-%m-%d")
    ok, n = _bump(conn, f"user:{user_id}:min", minute, per_min)
    if not ok:
        return f"Too many messages this minute ({n}). Please wait a moment."
    ok, n = _bump(conn, f"user:{user_id}:day", day, per_day)
    if not ok:
        return f"Daily message limit reached ({n}). Please come back tomorrow."
    if client_ip:
        ok, n = _bump(conn, f"ip:{client_ip}:min", minute, per_min * 3)
        if not ok:
            return "Too many requests from this address. Please wait a moment."
    return None


def llm_calls_today(conn: sqlite3.Connection, now: datetime) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE ts >= ?", (now.strftime("%Y-%m-%d"),)
        ).fetchone()[0]
    )
