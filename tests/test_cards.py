"""What a card says: every result of a search, no word standing in for an empty field, honest prices."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from views import common
from views.i18n import stated

from dubizzle_assistant.api.app import create_app
from tests.conftest import make_settings


def test_a_search_shows_its_result_even_when_that_car_is_the_one_in_focus(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as c:
        e = c.post("/chat", json={"message": "show me hondas", "name": "Cards"}).json()
        uid, sid = e["user_id"], e["session_id"]
        assert [x["id"] for x in e["cars"]] == ["R-078"]
        rest = {"user_id": uid, "session_id": sid}
        # The follow-up pins the focus without showing a card, which is right.
        e = c.post("/chat", json={"message": "does it have a warranty?", **rest}).json()
        assert e["cars"] == []
        # Asking to see stock again must not come back as an empty grid.
        e = c.post("/chat", json={"message": "show me hondas", **rest}).json()
        assert [x["id"] for x in e["cars"]] == ["R-078"]


def test_the_word_for_empty_is_not_a_value():
    for word in ("null", "None", " N/A ", "unknown", "-", ""):
        assert stated(word) == ""
    assert stated("white") == "white" and stated("GCC") == "GCC"
    card = {"id": "X-001", "year": 2020, "make": "kia", "model": "seltos", "exterior_color": "null"}
    assert "null" not in common.car_card(card, show_index=False, show_id=False).lower()


def test_a_monthly_only_card_says_the_cash_price_is_not_listed():
    card = {"id": "R-078", "year": 2021, "make": "honda", "model": "cr-v", "monthly_aed": 1048}
    html = common.car_card(card, show_index=False, show_id=False)
    assert "AED 1,048/mo · cash price not listed" in html
    assert "Price not listed" not in html
    # A cash price still leads, with the instalment beside it.
    both = common.car_card({**card, "price_aed": 79000}, show_index=False, show_id=False)
    assert "AED 79,000" in both and "or AED 1,048/mo" in both


def test_an_arabic_customer_sees_the_card_too(tmp_path: Path) -> None:
    """The English-only stock test left the empty grid in place for half the sheet's Level 9."""
    with TestClient(create_app(make_settings(tmp_path))) as c:
        e = c.post("/chat", json={"message": "corolla", "name": "Arabic"}).json()
        rest = {"user_id": e["user_id"], "session_id": e["session_id"]}
        assert [x["id"] for x in e["cars"]] == ["R-066"]
        # The same search, asked in Arabic, with that car now on screen and in focus.
        ar = c.post("/chat", json={"message": "أريد تويوتا كورولا", **rest}).json()

    ran = [s["name"] for s in ar["trace"]["stages"] if s["stage"] == "tool"]
    assert "search_inventory" in ran
    assert [x["id"] for x in ar["cars"]] == ["R-066"]


def test_a_detail_question_in_arabic_is_not_a_stock_request() -> None:
    from dubizzle_assistant.services.agent import _stock_question

    for asks_for_stock in ("عندك تويوتا كورولا؟", "أبغى سيارة سبع مقاعد", "أريد تويوتا كورولا"):
        assert _stock_question(asks_for_stock), asks_for_stock
    # A follow-up about the car already in focus must not force a search.
    for follow_up in ("كم ممشى الأولى؟", "هل عليها ضمان؟", "كم ممشى بي واي دي هان", "نعم"):
        assert not _stock_question(follow_up), follow_up
