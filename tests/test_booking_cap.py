"""The open-viewing cap is visible when a slot is proposed, not only when it is confirmed."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from dubizzle_assistant.config import DUBAI
from dubizzle_assistant.services.booking import create_booking, open_booking_cap


def test_open_booking_cap_is_visible_before_a_proposal(client: TestClient, app_settings) -> None:  # noqa: ANN001
    conn = sqlite3.connect(app_settings.db_path)
    conn.row_factory = sqlite3.Row
    now = datetime(2026, 9, 7, 9, 0, tzinfo=DUBAI)
    assert open_booking_cap(conn, "u_cap", now) is None
    for i, lid in enumerate(("C-003", "R-005", "R-048")):
        res = create_booking(
            conn, app_settings, "u_cap", lid, now + timedelta(days=1, hours=i), now
        )
        assert res["ok"], res
    assert "3 upcoming viewings" in (open_booking_cap(conn, "u_cap", now) or "")
