"""Slot rules in code: Sunday, hours, notice, export-only stock, double booking, the availability grid."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

from dubizzle_assistant.config import DUBAI
from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.services import booking, inventory, memory

NOW = datetime(2026, 9, 5, 14, 30, tzinfo=DUBAI)  # a Saturday


def fresh(tmp_path, app_settings):
    db = tmp_path / "b.db"
    init_db(db)
    conn = connect(db)
    inventory.load_inventory(conn, app_settings.inventory_path)
    memory.identify_user(conn, NOW, user_id="u1", name="Sara")
    return conn


def at(day_offset, hour):
    return (NOW + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)


def test_rules(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    assert "Sunday" in booking.validate_slot(conn, "C-003", at(1, 10), NOW)
    assert "08:00" in booking.validate_slot(conn, "C-003", at(2, 7), NOW)
    assert "08:00" in booking.validate_slot(conn, "C-003", at(2, 20), NOW)
    assert "past" in booking.validate_slot(conn, "C-003", at(0, 9), NOW)
    assert "notice" in booking.validate_slot(conn, "C-003", at(0, 15), NOW)
    assert booking.validate_slot(conn, "C-003", at(0, 19), NOW) is None, (
        "Saturday 19:00 is the last slot"
    )
    assert booking.validate_slot(conn, "C-003", at(2, 8), NOW) is None
    export_id = conn.execute("SELECT id FROM listings WHERE is_export_only = 1 LIMIT 1").fetchone()[
        0
    ]
    assert "export" in booking.validate_slot(conn, export_id, at(2, 10), NOW)
    assert "no listing" in booking.validate_slot(conn, "Z-999", at(2, 10), NOW)
    assert "30 days" in booking.validate_slot(conn, "C-003", at(40, 10), NOW)


def test_tomorrow_is_sunday_and_alternatives_skip_it(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    start, steps, err = booking.parse_slot("tomorrow", None, 9, NOW)
    assert err is None and start.weekday() == 6 and start.hour == 9
    assert any("(tomorrow)" in s for s in steps)
    assert "Sunday" in booking.validate_slot(conn, "C-003", start, NOW)
    alts = booking.next_free_slots(conn, "C-003", start, NOW)
    assert len(alts) == 3 and all("Monday" in a["label"] for a in alts)
    assert alts[0]["start"].startswith("2026-09-07T08:00")


def test_text_wins_over_model_iso_and_default_hour():
    start, steps, _ = booking.parse_slot("next friday", "2026-09-06", None, NOW)
    assert start.strftime("%A") == "Friday" and start.hour == 10
    assert any("text wins" in s for s in steps) and any("defaulted to 10:00" in s for s in steps)
    start, _, _ = booking.parse_slot("2026-09-08", None, 14, NOW)
    assert start.isoformat().startswith("2026-09-08T14:00")


def test_double_booking_and_caps(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    memory.identify_user(conn, NOW, user_id="u2", name="Omar")
    ok = booking.create_booking(conn, app_settings, "u1", "C-003", at(2, 10), NOW)
    assert ok["ok"] and ok["ref"] == "BK-0001"
    clash = booking.create_booking(conn, app_settings, "u2", "C-003", at(2, 10), NOW)
    assert (
        not clash["ok"]
        and clash["alternatives"]
        and clash["alternatives"][0]["start"].startswith("2026-09-07T11:00")
    )
    same_hour = booking.create_booking(conn, app_settings, "u1", "C-044", at(2, 10), NOW)
    assert not same_hour["ok"]
    booking.create_booking(conn, app_settings, "u1", "C-044", at(2, 11), NOW)
    booking.create_booking(conn, app_settings, "u1", "C-010", at(2, 12), NOW)
    fourth = booking.create_booking(conn, app_settings, "u1", "C-011", at(2, 13), NOW)
    assert not fourth["ok"] and "upcoming viewings" in fourth["reason"]
    assert booking.cancel_booking(conn, app_settings, "u1", "bk-0001", NOW)["ok"]
    again = booking.create_booking(conn, app_settings, "u2", "C-003", at(2, 10), NOW)
    assert again["ok"], "a cancelled slot is free again"
    rows = list(csv.DictReader(app_settings.bookings_csv.open(encoding="utf-8-sig", newline="")))
    assert {r["status"] for r in rows} == {"confirmed", "cancelled"}
    assert (app_settings.outbox_dir / "BK-0001-confirmation.txt").exists()
    assert (app_settings.outbox_dir / "BK-0001-cancellation.txt").exists()


def test_availability_grid_states(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    booking.create_booking(conn, app_settings, "u1", "C-003", at(2, 10), NOW)
    # The week of the booking: Monday 7 Sep has the taken slot, Sunday 13 Sep is closed.
    grid = booking.availability_grid(conn, "C-003", at(2, 10), NOW)
    by_day = {d["weekday"]: d for d in grid["days"]}
    assert grid["week_start"] == "2026-09-07"
    assert {s["state"] for s in by_day["Sunday"]["slots"]} == {"closed"}
    monday = {s["hour"]: s["state"] for s in by_day["Monday"]["slots"]}
    assert monday[10] == "taken" and monday[11] == "free" and len(monday) == 12
    # The current week: Saturday afternoon, so the morning is past and the last slot is still free.
    this_week = booking.availability_grid(conn, "C-003", NOW, NOW)
    saturday = {
        s["hour"]: s["state"]
        for s in next(d for d in this_week["days"] if d["weekday"] == "Saturday")["slots"]
    }
    assert saturday[9] == "past" and saturday[19] == "free"
