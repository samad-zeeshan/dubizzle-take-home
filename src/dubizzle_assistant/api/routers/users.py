"""Users: identify by name or id, read the materialised profile, like a car, forget everything."""

from __future__ import annotations

import contextlib
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services import memory

router = APIRouter(prefix="/users", tags=["users"])


class Identify(BaseModel):
    name: str | None = None
    user_id: str | None = None


class Like(BaseModel):
    listing_id: str


@router.post("/identify")
def identify(
    body: Identify,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not body.name and not body.user_id:
        raise HTTPException(status_code=422, detail="give a name or a user_id")
    now = settings.now()
    info = memory.identify_user(conn, now, name=body.name, user_id=body.user_id)
    prof = memory.profile(conn, info["user_id"], now)
    return {**info, "profile_summary": memory.recall_block(prof), "profile": prof}


@router.get("/{user_id}/profile")
def get_profile(
    user_id: str,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    prof = memory.profile(conn, user_id, settings.now())
    if not prof.get("known"):
        raise HTTPException(status_code=404, detail="no such user")
    prof["recall_block"] = memory.recall_block(prof)
    return prof


@router.get("/{user_id}/history")
def history(
    user_id: str,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not memory.get_user(conn, user_id):
        raise HTTPException(status_code=404, detail="no such user")
    q = lambda sql: [dict(r) for r in conn.execute(sql, (user_id,))]  # noqa: E731
    return {
        "searches": q(
            "SELECT raw_query, parsed_filters_json, result_count, ts, session_id FROM search_history WHERE user_id = ? ORDER BY id DESC LIMIT 50"
        ),
        "likes": q(
            "SELECT listing_id, snapshot_json, ts FROM liked_cars WHERE user_id = ? ORDER BY ts DESC"
        ),
        "bookings": q(
            "SELECT ref, listing_id, slot_start, slot_end, status, created_at FROM bookings WHERE user_id = ? ORDER BY slot_start"
        ),
        "preferences": q(
            "SELECT kind, value, source, ts FROM preference_events WHERE user_id = ? ORDER BY id"
        ),
        "sessions": q(
            "SELECT session_id, created_at, last_active_at, turn_counter FROM sessions WHERE user_id = ? ORDER BY created_at"
        ),
    }


@router.post("/{user_id}/likes")
def like(
    user_id: str,
    body: Like,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not memory.get_user(conn, user_id):
        raise HTTPException(status_code=404, detail="no such user")
    cards = inv.get_cards(conn, [body.listing_id.upper()])
    if not cards:
        raise HTTPException(status_code=404, detail="no such listing")
    return memory.like(conn, user_id, cards[0], None, settings.now())


@router.delete("/{user_id}")
def forget(user_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    if not memory.get_user(conn, user_id):
        raise HTTPException(status_code=404, detail="no such user")
    counts = memory.forget_user(conn, user_id)
    with contextlib.suppress(ImportError):
        from dubizzle_assistant.services import leads

        leads.export_csv(conn, None)
    return {"forgotten": user_id, "deleted": counts}
