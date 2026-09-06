"""Bookings over REST, backed by the same service the chat tools call, so a reviewer can curl the rules."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import DUBAI, Settings
from dubizzle_assistant.services import booking, memory

router = APIRouter(tags=["bookings"])


class NewBooking(BaseModel):
    user_id: str
    listing_id: str
    slot_start: str  # ISO 8601, Dubai time if no offset


@router.get("/inventory/{listing_id}/availability")
def availability(
    listing_id: str,
    week: str | None = Query(
        None, description="Any date in the week, YYYY-MM-DD. Defaults to this week."
    ),
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    lid = listing_id.upper()
    if not conn.execute("SELECT 1 FROM listings WHERE id = ?", (lid,)).fetchone():
        raise HTTPException(status_code=404, detail=f"no listing {lid}")
    now = settings.now()
    anchor = now
    if week:
        try:
            anchor = datetime.fromisoformat(week).replace(tzinfo=DUBAI, hour=12)
        except ValueError as e:
            raise HTTPException(status_code=422, detail="week must be YYYY-MM-DD") from e
    return booking.availability_grid(conn, lid, anchor, now)


@router.post("/bookings")
def create(
    body: NewBooking,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not memory.get_user(conn, body.user_id):
        raise HTTPException(status_code=404, detail="no such user")
    try:
        start = datetime.fromisoformat(body.slot_start)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="slot_start must be ISO 8601") from e
    start = start.astimezone(DUBAI) if start.tzinfo else start.replace(tzinfo=DUBAI)
    result = booking.create_booking(
        conn, settings, body.user_id, body.listing_id.upper(), start, settings.now()
    )
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/bookings")
def list_for_user(
    user_id: str = Query(...), conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict[str, Any]]:
    return booking.list_bookings(conn, user_id)


@router.delete("/bookings/{ref}")
def cancel(
    ref: str,
    user_id: str = Query(...),
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    result = booking.cancel_booking(conn, settings, user_id, ref, settings.now())
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result
