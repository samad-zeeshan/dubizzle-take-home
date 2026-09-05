"""
Build the FastAPI application. The lifespan loads the inventory, routers hang off it.

The app object holds settings and a few shared services. Every request opens
its own SQLite connection, so two Streamlit reruns firing at once never share
a cursor.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dubizzle_assistant.api.routers import health, inventory
from dubizzle_assistant.config import Settings, get_settings
from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.services.inventory import RetrievalUnavailableError, load_inventory

log = logging.getLogger("dubizzle")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(settings.db_path)
        conn = connect(settings.db_path)
        try:
            app.state.inventory_count = load_inventory(conn, settings.inventory_path)
        finally:
            conn.close()
        app.state.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        app.state.llm = None
        app.state.llm_error = None
        app.state.embedder = None
        if not settings.llm_configured:
            # Inventory endpoints and tests still work without a key; only /chat is dark.
            log.warning(
                "GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/apikey and copy "
                ".env.example to .env. Chat is disabled until then."
            )
        log.info(
            "inventory loaded: %d listings, retrieval=%s, provider=%s, model=%s, ablations=%s",
            app.state.inventory_count,
            settings.retrieval_mode,
            settings.llm_provider,
            settings.llm_model,
            settings.ablations_active or "none",
        )
        yield

    app = FastAPI(
        title="dubizzle cars assistant",
        version="0.1.0",
        description="Conversational search over a used-car inventory with bookings, leads, and memory.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(inventory.router)

    @app.exception_handler(RetrievalUnavailableError)
    async def _retrieval_unavailable(_: Request, exc: RetrievalUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app
