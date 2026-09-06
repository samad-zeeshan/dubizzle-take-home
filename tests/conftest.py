"""Shared fixtures: the built inventory, and an app wired to a throwaway database with the mock model."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dubizzle_assistant.config import DUBAI, Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def inventory() -> dict:
    return json.loads((ROOT / "data" / "inventory.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def listings(inventory: dict) -> dict[str, dict]:
    return {row["id"]: row for row in inventory["listings"]}


@pytest.fixture(scope="session")
def xlsx_path() -> Path:
    return ROOT / "data" / "cars.xlsx"


def make_settings(tmp: Path, **overrides) -> Settings:
    base = {
        "gemini_api_key": None,
        "llm_provider": "mock",
        "debug_endpoints": True,
        "db_file": tmp / "app.db",
        "logs_dir": tmp / "logs",
        "outbox_dir": tmp / "outbox",
        "leads_file": tmp / "leads.csv",
        "bookings_file": tmp / "bookings.csv",
        "llm_cassette_path": tmp / "cassette.jsonl",
        "rate_limit_per_min": 1000,
        "rate_limit_per_day": 10000,
        # A Saturday afternoon, so "tomorrow" is the Sunday the booking rules reject.
        "demo_now": datetime(2026, 9, 5, 14, 30, tzinfo=DUBAI),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture(scope="session")
def app_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return make_settings(tmp_path_factory.mktemp("state"))


@pytest.fixture(scope="session")
def client(app_settings: Settings) -> Iterator[TestClient]:
    from dubizzle_assistant.api.app import create_app

    with TestClient(create_app(app_settings)) as c:
        yield c
