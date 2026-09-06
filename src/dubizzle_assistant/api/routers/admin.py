"""Admin tables behind DEBUG_ENDPOINTS: leads, bookings, users, sessions, and today's model calls."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import leads

router = APIRouter(prefix="/admin", tags=["admin"])


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params)]


@router.get("/leads")
def admin_leads(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return leads.all_leads(conn)


@router.get("/bookings")
def admin_bookings(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return _rows(
        conn,
        "SELECT b.*, l.year, l.make, l.model FROM bookings b LEFT JOIN listings l ON l.id = b.listing_id ORDER BY b.slot_start",
    )


@router.get("/users")
def admin_users(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return _rows(
        conn,
        (
            "SELECT u.user_id, u.name, u.created_at, u.last_seen_at, "
            "(SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.user_id) AS sessions, "
            "(SELECT COUNT(*) FROM liked_cars c WHERE c.user_id = u.user_id) AS likes, "
            "(SELECT COUNT(*) FROM bookings b WHERE b.user_id = u.user_id AND b.status = 'confirmed') AS bookings "
            "FROM users u ORDER BY u.last_seen_at DESC"
        ),
    )


@router.get("/sessions")
def admin_sessions(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return _rows(
        conn,
        "SELECT s.*, u.name FROM sessions s LEFT JOIN users u ON u.user_id = s.user_id ORDER BY s.last_active_at DESC LIMIT 200",
    )


@router.get("/llm_calls")
def admin_llm_calls(
    settings: Settings = Depends(get_settings_dep), conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    today = settings.now().strftime("%Y-%m-%d")
    rows = _rows(conn, "SELECT * FROM llm_calls WHERE ts >= ? ORDER BY id DESC LIMIT 200", (today,))
    totals = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
        "COALESCE(AVG(latency_ms),0) AS avg_latency_ms FROM llm_calls WHERE ts >= ?",
        (today,),
    ).fetchone()
    return {
        "date": today,
        "budget": settings.daily_llm_budget,
        "totals": dict(totals),
        "calls": rows,
    }
