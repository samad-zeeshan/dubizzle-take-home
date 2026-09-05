"""Per-request dependencies: settings and a fresh SQLite connection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from dubizzle_assistant.config import Settings
from dubizzle_assistant.db import connect


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_embedder(request: Request):  # noqa: ANN201
    return getattr(request.app.state, "embedder", None)
