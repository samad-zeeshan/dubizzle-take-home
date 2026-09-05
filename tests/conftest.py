"""Shared fixtures: the built inventory file and the workbook path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
