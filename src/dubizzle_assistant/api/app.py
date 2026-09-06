"""
Build the FastAPI application. The lifespan loads the inventory and picks the model client.

The app object holds settings and a few shared services. Every request opens
its own SQLite connection, so two Streamlit reruns firing at once never share
a cursor. Debug and admin routers exist only when DEBUG_ENDPOINTS is on.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dubizzle_assistant.api.routers import chat, debug, health, inventory, sessions, users
from dubizzle_assistant.config import Settings, get_settings
from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.services.inventory import RetrievalUnavailableError, load_inventory
from dubizzle_assistant.services.llm import build_embedder, build_llm

log = logging.getLogger("dubizzle")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        init_db(settings.db_path)
        conn = connect(settings.db_path)
        try:
            app.state.inventory_count = load_inventory(conn, settings.inventory_path)
        finally:
            conn.close()
        app.state.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        app.state.llm = build_llm(settings)
        app.state.embedder = build_embedder(settings, app.state.llm)
        app.state.llm_error = None
        if app.state.llm is None:
            # Inventory endpoints and tests still work without a key; only /chat is dark.
            log.warning(
                "GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/apikey and copy "
                ".env.example to .env, or run with LLM_PROVIDER=mock. Chat is disabled until then."
            )
        log.info(
            "inventory loaded: %d listings, retrieval=%s, provider=%s, model=%s, cassette=%s, ablations=%s",
            app.state.inventory_count,
            settings.retrieval_mode,
            settings.llm_provider,
            settings.llm_model,
            settings.llm_cassette_mode,
            settings.ablations_active or "none",
        )
        yield

    app = FastAPI(
        title="dubizzle cars assistant",
        version="0.1.0",
        description="Conversational search over a used-car inventory with bookings, leads, memory, and a per-turn trace.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    for r in (health.router, chat.router, sessions.router, users.router, inventory.router):
        app.include_router(r)
    if settings.debug_endpoints:
        app.include_router(debug.router)
        try:
            from dubizzle_assistant.api.routers import admin

            app.include_router(admin.router)
        except ImportError:
            pass
    for name in ("bookings", "leads", "stream"):
        try:
            module = __import__(f"dubizzle_assistant.api.routers.{name}", fromlist=["router"])
            app.include_router(module.router)
        except ImportError:
            pass

    async def retrieval_unavailable(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.add_exception_handler(RetrievalUnavailableError, retrieval_unavailable)

    return app
