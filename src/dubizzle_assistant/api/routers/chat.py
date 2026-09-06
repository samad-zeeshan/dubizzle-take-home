"""
POST /chat: the one endpoint the client talks to for conversation.

Everything around the model call is deterministic and happens here or in the
agent: idempotency, rate limits, session rotation, and the daily budget that
swaps in the offline stand-in rather than failing.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import memory, ratelimit
from dubizzle_assistant.services.agent import ChatUnavailableError, run_turn

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's message")
    user_id: str | None = Field(None, description="Known user id. Omit on first contact.")
    session_id: str | None = Field(None, description="Omit to start a new session")
    name: str | None = Field(None, description="Display name when there is no user id yet")

    model_config = {
        "json_schema_extra": {
            "examples": [{"message": "show me SUVs with warranty under AED 150k", "name": "Sara"}]
        }
    }


def prepare(
    req: ChatRequest,
    request: Request,
    settings: Settings,
    conn: sqlite3.Connection,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Validation, idempotency, limits, user and session resolution shared by /chat and /chat/stream."""
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="message is empty")
    if len(text) > settings.max_message_chars:
        raise HTTPException(
            status_code=422,
            detail=f"message is longer than {settings.max_message_chars} characters",
        )
    now = settings.now()

    if req.user_id and memory.get_user(conn, req.user_id):
        user_id = req.user_id
    else:
        user_id = memory.identify_user(conn, now, name=req.name, user_id=req.user_id)["user_id"]

    if idempotency_key:
        row = conn.execute(
            "SELECT envelope_json FROM idempotency WHERE key = ? AND user_id = ? AND created_at >= ?",
            (
                idempotency_key,
                user_id,
                (now - timedelta(seconds=settings.idempotency_ttl_seconds)).isoformat(
                    timespec="seconds"
                ),
            ),
        ).fetchone()
        if row:
            env = json.loads(row["envelope_json"])
            env["idempotent_replay"] = True
            return {"replay": env}

    limited = ratelimit.check(
        conn,
        now,
        user_id=user_id,
        client_ip=request.client.host if request.client else None,
        per_min=settings.rate_limit_per_min,
        per_day=settings.rate_limit_per_day,
    )
    if limited:
        raise HTTPException(status_code=429, detail=limited, headers={"Retry-After": "60"})

    new_session = True
    session_id = None
    if req.session_id:
        s = memory.get_session(conn, req.session_id)
        if (
            s
            and s["user_id"] == user_id
            and not memory.is_idle(s, now, settings.session_idle_minutes)
        ):
            session_id, new_session = req.session_id, False
    if session_id is None:
        session_id = memory.create_session(conn, user_id, now)

    llm = request.app.state.llm
    degraded = False
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail="Chat is not configured: set GEMINI_API_KEY in .env (free key at https://aistudio.google.com/apikey) or run with LLM_PROVIDER=mock.",
        )
    if (
        settings.llm_provider == "litellm"
        and ratelimit.llm_calls_today(conn, now) >= settings.daily_llm_budget
    ):
        from dubizzle_assistant.services.llm.mock_client import HeuristicLLM

        llm, degraded = HeuristicLLM(), True
    return {
        "text": text,
        "user_id": user_id,
        "session_id": session_id,
        "new_session": new_session,
        "llm": llm,
        "degraded": degraded,
        "key": idempotency_key,
        "now": now,
    }


def store_idempotent(
    conn: sqlite3.Connection, prep: dict[str, Any], envelope: dict[str, Any]
) -> None:
    if prep.get("key"):
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency (key, user_id, envelope_json, created_at) VALUES (?,?,?,?)",
                (
                    prep["key"],
                    prep["user_id"],
                    json.dumps(envelope, ensure_ascii=False, default=str),
                    prep["now"].isoformat(timespec="seconds"),
                ),
            )


@router.post("/chat")
def chat(
    req: ChatRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    prep = prepare(req, request, settings, conn, idempotency_key)
    if "replay" in prep:
        return prep["replay"]
    try:
        envelope = run_turn(
            settings=settings,
            conn=conn,
            llm=prep["llm"],
            user_id=prep["user_id"],
            session_id=prep["session_id"],
            message=prep["text"],
            request_id=secrets.token_hex(6),
            embedder=getattr(request.app.state, "embedder", None),
        )
    except ChatUnavailableError as e:
        request.app.state.llm_error = str(e)
        headers = {"Retry-After": str(int(e.retry_after))} if e.retry_after else None
        raise HTTPException(status_code=e.status, detail=str(e), headers=headers) from e
    envelope["new_session"] = prep["new_session"]
    envelope["degraded"] = prep["degraded"]
    store_idempotent(conn, prep, envelope)
    return envelope
