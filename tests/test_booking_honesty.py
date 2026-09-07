"""A slot the customer did not ask for is never proposed as if they had.

Report breaks 5 and 6: "last Monday" was answered with a Monday seven days later, and
"tomorrow at 10:30" was read back as 10:00, both without a word of explanation.
"""

from __future__ import annotations

from datetime import datetime

from dubizzle_assistant.config import DUBAI
from dubizzle_assistant.services import booking
from tests.test_booking import fresh

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=DUBAI)  # a Tuesday, the day the report was written


def test_last_monday_reads_backwards_and_is_refused(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    start, steps, err = booking.parse_slot("last Monday", None, 15, NOW, said="last Monday at 3pm")
    assert err is None and start is not None
    # Monday the 7th, the day that has gone, not the 14th a week ahead.
    assert start.date().isoformat() == "2026-09-07"
    assert any("last monday" in s.lower() for s in steps)
    assert "in the past" in booking.validate_slot(conn, "C-088", start, NOW)


def test_the_model_and_the_text_disagreeing_about_a_past_day_asks(tmp_path, app_settings):
    """The model guesses the next occurrence, the text reads the one that has gone."""
    start, steps, err = booking.parse_slot("last Monday", "2026-09-14", 15, NOW)
    assert start is None
    assert "has passed" in err and "Which day did you mean?" in err
    assert any("text wins" in s for s in steps)


def test_yesterday_is_yesterday(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    start, _, err = booking.parse_slot("yesterday", None, 15, NOW)
    assert err is None and start.date().isoformat() == "2026-09-07"
    assert "in the past" in booking.validate_slot(conn, "C-088", start, NOW)


def test_a_half_hour_is_refused_rather_than_rounded_down(tmp_path, app_settings):
    conn = fresh(tmp_path, app_settings)
    # The model can only pass a whole hour, so the half hour has to come from the message.
    start, steps, err = booking.parse_slot(
        "tomorrow", None, 10, NOW, said="Book me in to see R-077 tomorrow at 10:30"
    )
    assert err is None and start.hour == 10 and start.minute == 30
    assert any("kept as typed" in s for s in steps)
    reason = booking.validate_slot(conn, "R-077", start, NOW)
    assert reason is not None and "start on the hour" in reason
    # And the customer is offered real slots rather than being moved without being told.
    alts = booking.next_free_slots(conn, "R-077", start, NOW)
    assert alts and all(a["start"].endswith(":00+04:00") for a in alts)


def test_a_whole_hour_still_goes_straight_through(tmp_path, app_settings):
    start, steps, err = booking.parse_slot(
        "tomorrow", None, 9, NOW, said="book a viewing for the velar tomorrow at 9am"
    )
    assert err is None and start.hour == 9 and start.minute == 0
    assert not any("kept as typed" in s for s in steps)
