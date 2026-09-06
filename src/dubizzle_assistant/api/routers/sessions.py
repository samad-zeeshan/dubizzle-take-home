"""Sessions: mint one, read it back with messages and context, export it with traces."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import memory
from dubizzle_assistant.services.trace import redact

router = APIRouter(prefix="/sessions", tags=["sessions"])


class NewSession(BaseModel):
    user_id: str


@router.post("")
def create(
    body: NewSession,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    now = settings.now()
    if not memory.get_user(conn, body.user_id):
        memory.identify_user(conn, now, user_id=body.user_id, name=body.user_id)
    return {"session_id": memory.create_session(conn, body.user_id, now), "user_id": body.user_id}


@router.get("/{session_id}")
def read(session_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    s = memory.get_session(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="no such session")
    ctx = memory.get_context(conn, session_id)
    return {"session": s, "messages": redact(memory.all_messages(conn, session_id)), "context": ctx}
