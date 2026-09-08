"""GET /health: is the service up, is the model configured, what modes and ablations are active."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings

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
