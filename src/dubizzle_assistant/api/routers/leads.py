"""Leads: the contact form that bypasses the model, and the CSV a reviewer opens afterwards."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import leads, memory

router = APIRouter(tags=["leads"])


class Contact(BaseModel):
    user_id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None


@router.post("/leads/contact")
def contact(
    body: Contact,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not memory.get_user(conn, body.user_id):
        raise HTTPException(status_code=404, detail="no such user")
    if not (body.name or body.phone or body.email):
        raise HTTPException(status_code=422, detail="give a name, phone, or email")
    return leads.set_contact(
        conn,
        settings,
        body.user_id,
        settings.now(),
        name=body.name,
        phone=body.phone,
        email=body.email,
    )


@router.get("/leads")
def list_leads(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, Any]]:
    return leads.all_leads(conn)


@router.get("/leads.csv")
def leads_csv(
    settings: Settings = Depends(get_settings_dep), conn: sqlite3.Connection = Depends(get_conn)
) -> FileResponse:
    leads.export_csv(conn, settings.leads_csv)
    return FileResponse(settings.leads_csv, media_type="text/csv", filename="leads.csv")
