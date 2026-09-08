"""GET /health, and POST /llm/key so a key added in the app takes effect without a restart."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.envfile import masked, write_key
from dubizzle_assistant.services.llm import build_embedder, build_llm

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    today = settings.now().date().isoformat()
    requests_today = conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE ts >= ?", (today,)
    ).fetchone()[0]
    db_ok = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] > 0
    # The client that is actually answering, not the configured id. With LLM_PROVIDER=mock, or
    # with no key at all, llm_model still reads gemini-... and the page claimed a model that
    # never ran. Someone cloning the repo offline was told the replies came from Gemini.
    client = getattr(request.app.state, "llm", None)
    active_model = getattr(client, "model", None) or settings.llm_model
    offline = not str(active_model).startswith("gemini/")
    return {
        "status": "ok" if db_ok else "degraded",
        "now": settings.now().isoformat(timespec="minutes"),
        "started_at": getattr(request.app.state, "started_at", None),
        "inventory_count": getattr(request.app.state, "inventory_count", 0),
        "inventory": getattr(request.app.state, "inventory", {}),
        "db_ok": db_ok,
        "llm": {
            "configured": settings.llm_configured,
            "provider": settings.llm_provider,
            "model": active_model,
            "configured_model": settings.llm_model,
            "offline": offline,
            "fallback_model": settings.usable_fallback_model,
            "requests_today": requests_today,
            "budget": settings.daily_llm_budget,
            "last_error": getattr(request.app.state, "llm_error", None),
            "cassette_mode": settings.llm_cassette_mode,
            "verify_mode": settings.verify_mode,
            "structured_reply": settings.use_structured_reply,
        },
        "retrieval_mode": settings.retrieval_mode,
        "debug_endpoints": settings.debug_endpoints,
        "ablations_active": settings.ablations_active,
        "demo_clock": settings.demo_now.isoformat() if settings.demo_now else None,
    }


class NewKey(BaseModel):
    key: str


@router.post("/llm/key")
def set_llm_key(body: NewKey, request: Request) -> dict[str, Any]:
    """Take a Gemini key from the app, save it, and start using it without a restart.

    Only the machine running the app may call this, the key is never sent back, and only the
    key and provider are replaced, so a run pointed at another database or put in mock mode by
    flag keeps everything else it started with.
    """
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="only the machine running the app may do this")

    settings: Settings = request.app.state.settings
    try:
        write_key(settings.dotenv_path, body.key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # A run that fell back to the stand-in for want of a key should stop doing that now.
    update: dict[str, Any] = {"gemini_api_key": body.key.strip(), "llm_provider": "litellm"}
    if not settings.llm_model.startswith("gemini/"):
        # Someone adding a Gemini key wants Gemini, not the local model the file still names.
        update["llm_model"] = Settings.model_fields["llm_model"].default
        update["llm_api_base"] = None
    updated = settings.model_copy(update=update)
    request.app.state.settings = updated
    request.app.state.llm = build_llm(updated)
    request.app.state.embedder = build_embedder(updated, request.app.state.llm)
    request.app.state.llm_error = None
    active = getattr(request.app.state.llm, "model", None)
    return {
        "saved": True,
        "key": masked(body.key),
        "model": active,
        "offline": not str(active).startswith("gemini/"),
    }
