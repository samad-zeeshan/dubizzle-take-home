"""Each ablation flag switches one control off and the expected failure appears. That is the demo of what it prevents."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.mock_client import ScriptedLLM
from dubizzle_assistant.text import PHONE_RE
from tests.conftest import make_settings


def _app(tmp_path, **flags):
    return TestClient(create_app(make_settings(tmp_path, **flags)))


def test_prefilter_off_lets_trivia_reach_the_model(tmp_path):
    with _app(tmp_path, ablate_prefilter=True) as c:
        e = c.post("/chat", json={"message": "who won the 1998 world cup?", "name": "A"}).json()
        assert e["llm_used"] is True
        assert (
            next(s for s in e["trace"]["stages"] if s["stage"] == "prefilter")["result"]
            == "skipped (ablated)"
        )
        assert e["trace"]["ablations_active"] == ["prefilter"]
        assert c.get("/health").json()["ablations_active"] == ["prefilter"]


def test_postfilter_off_leaks_a_phone_from_the_model(tmp_path):
    scripted = [{"text": "Call the dealer on +971 50 123 4567 or try YallaMotor."}]
    # Grounding is off in both runs so only the post-filter separates them; a phone is also a run of digits.
    with _app(tmp_path, ablate_postfilter=True, ablate_grounding_check=True) as c:
        c.app.state.llm = ScriptedLLM(scripted)
        e = c.post("/chat", json={"message": "hello there", "name": "B"}).json()
        assert PHONE_RE.search(e["reply"]) and "yallamotor" in e["reply"].lower()
    with _app(tmp_path / "on", ablate_grounding_check=True) as c:
        c.app.state.llm = ScriptedLLM(scripted)
        e = c.post("/chat", json={"message": "hello there", "name": "B"}).json()
        assert not PHONE_RE.search(e["reply"]) and "yallamotor" not in e["reply"].lower()
        assert {
            h["kind"]
            for h in next(s for s in e["trace"]["stages"] if s["stage"] == "postfilter")["hits"]
        } == {"phone", "competitor"}


def test_grounding_off_lets_an_invented_price_through(tmp_path):
    scripted = [
        {"tool_calls": [{"name": "search_inventory", "arguments": {"make": "honda"}}]},
        {"text": "The Honda CR-V is a bargain at AED 999,999."},
        {"text": "The Honda CR-V is a bargain at AED 999,999."},
    ]
    with _app(tmp_path, ablate_grounding_check=True) as c:
        c.app.state.llm = ScriptedLLM(list(scripted))
        e = c.post("/chat", json={"message": "any hondas?", "name": "C"}).json()
        assert "999,999" in e["reply"] and e["grounding"] is None
    with _app(tmp_path / "on") as c:
        c.app.state.llm = ScriptedLLM(list(scripted))
        e = c.post("/chat", json={"message": "any hondas?", "name": "C"}).json()
        assert "999,999" not in e["reply"]
        stages = [s["stage"] for s in e["trace"]["stages"]]
        assert "grounding_retry" in stages and "grounding_fallback" in stages
        assert e["reply"].startswith("Here is what the listing data shows")
        assert e["grounding"]["ungrounded"] == []


def test_relaxation_off_returns_nothing_for_an_impossible_query(tmp_path):
    with _app(tmp_path, ablate_relaxation=True) as c:
        r = c.get("/inventory/search", params={"make": "honda", "color": "purple"}).json()
        assert r["total_matches"] == 0 and r["relaxed_filters"] == []
    with _app(tmp_path / "on") as c:
        r = c.get("/inventory/search", params={"make": "honda", "color": "purple"}).json()
        assert r["total_matches"] == 1 and r["relaxed_filters"] == ["drop_color"]


def test_resolver_off_leaves_the_first_one_unresolved(tmp_path):
    with _app(tmp_path, ablate_resolver=True) as c:
        e = c.post("/chat", json={"message": "show me hondas", "name": "D"}).json()
        e = c.post(
            "/chat",
            json={
                "message": "what's the mileage on the first one?",
                "user_id": e["user_id"],
                "session_id": e["session_id"],
            },
        ).json()
        assert e["resolver"] is None
        assert (
            next(s for s in e["trace"]["stages"] if s["stage"] == "resolver")["result"]
            == "skipped (ablated)"
        )


def test_sanitizer_off_exposes_seller_contacts_to_the_model(tmp_path, app_settings):
    from dubizzle_assistant.db import connect, init_db
    from dubizzle_assistant.services import inventory, tools
    from dubizzle_assistant.services.context import TurnContext
    from dubizzle_assistant.services.trace import TurnTrace

    db = tmp_path / "s.db"
    init_db(db)
    conn = connect(db)
    inventory.load_inventory(conn, app_settings.inventory_path)
    listing = conn.execute(
        "SELECT id FROM listings WHERE dealer_contact_json LIKE '%971%' LIMIT 1"
    ).fetchone()[0]
    for flag, expect in ((False, False), (True, True)):
        settings = make_settings(tmp_path, db_file=db, ablate_sanitizer=flag)
        ctx = TurnContext(
            settings=settings,
            conn=conn,
            user_id="u",
            session_id="s",
            turn=1,
            trace=TurnTrace("s", 1, "r"),
            now=settings.now(),
        )
        result = tools.run_tool(ctx, "get_listing", {"listing_id": listing})
        assert bool(PHONE_RE.search(result["listing_text"])) is expect, (flag, listing)
