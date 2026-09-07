"""Alternatives to one car: the car itself never appears, and every result says how it differs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.mock_client import ScriptedLLM
from tests.conftest import make_settings
from tests.test_agent_offline import chat, tools_used

TROC = "R-085"  # 2024 Volkswagen T-Roc at AED 89,900, the only T-Roc in the inventory
UNPRICED_SEDAN = "C-002"  # 2019 Mercedes C-Class with no price in the ad


def test_similar_excludes_the_anchor_and_explains_each_result(client):
    out = client.get(f"/inventory/{TROC}/similar").json()
    ids = [c["id"] for c in out["results"]]
    assert ids and TROC not in ids and out["anchor"]["id"] == TROC
    assert out["total_matches"] >= len(ids)
    for c in out["results"]:
        ex = c["explain"]
        assert "body_type" in ex["matched_filters"] or "price_band" in ex["matched_filters"]
        assert ex["rank_reason"].startswith("#") and ex["vs_anchor"]
    top = out["results"][0]
    assert top["body_type"] == "suv" and abs(top["price_aed"] - 89900) <= 0.3 * 89900
    assert "30%" in out["criteria"] and "89,900" in out["criteria"]


def test_similar_unknown_id_is_404(client):
    assert client.get("/inventory/Z-999/similar").status_code == 404


def test_similar_for_an_unpriced_car_falls_back_to_body_type(client):
    out = client.get(f"/inventory/{UNPRICED_SEDAN}/similar").json()
    ids = [c["id"] for c in out["results"]]
    assert ids and UNPRICED_SEDAN not in ids
    assert all(c["body_type"] == "sedan" for c in out["results"])
    assert out["criteria"] == "same body type"


def test_similar_cars_never_include_the_car_under_discussion(client):
    """The transcript that started this: 'compare this to other similar cars' handed back the same car."""
    e = chat(client, f"Tell me more about the 2024 Volkswagen T-Roc ({TROC})", name="Probe Similar")
    uid, sid = e["user_id"], e["session_id"]
    assert [c["id"] for c in e["cars"]] == [TROC]
    assert f"Similar cars to {TROC}" in e["suggested_actions"]
    e = chat(client, "can you compare this price and features to other similar cars", uid, sid)
    assert e["resolver"]["resolved"] == TROC and e["resolver"]["rule"] == "pronoun:focus"
    assert tools_used(e) == ["similar_listings"] and e["intent"] == "similar"
    ids = [c["id"] for c in e["cars"]]
    assert ids and TROC not in ids
    # The anchor is named in the prose, never numbered: ids stay out of what the user reads.
    assert e["focus_id"] == TROC and TROC not in e["reply"]
    assert "T-Roc" in e["reply"]
    assert e["query_explain"]["stage_counts"]["similar"] >= len(ids)
    assert e["grounding"]["ungrounded"] == []


def test_search_that_only_finds_the_focus_car_is_flagged_not_reshown(tmp_path):
    """A model that searches on the focus car's own make and model is told that is not an alternative."""
    scripted = ScriptedLLM(
        [
            {"tool_calls": [{"name": "get_listing", "arguments": {"listing_id": TROC}}]},
            {"text": "The T-Roc is listed at AED 89,900 with 39,000 km."},
            {
                "tool_calls": [
                    {
                        "name": "search_inventory",
                        "arguments": {"make": "volkswagen", "model": "t-roc"},
                    }
                ]
            },
            {"tool_calls": [{"name": "similar_listings", "arguments": {"listing_id": TROC}}]},
            {"text": "Other SUVs near that price are listed below."},
        ]
    )
    with TestClient(create_app(make_settings(tmp_path))) as c:
        c.app.state.llm = scripted
        e = c.post("/chat", json={"message": f"tell me about {TROC}", "name": "Sam"}).json()
        e = c.post(
            "/chat",
            json={
                "message": "what else is similar to it?",
                "user_id": e["user_id"],
                "session_id": e["session_id"],
            },
        ).json()
    assert tools_used(e) == ["search_inventory", "similar_listings"]
    # The loop appends to one message list, so any call's view holds the whole turn.
    seen = next(
        m["content"]
        for m in scripted.calls[-1]["messages"]
        if m.get("role") == "tool" and m.get("name") == "search_inventory"
    )
    assert f"{TROC} is the car already on screen" in seen
    ids = [c["id"] for c in e["cars"]]
    assert ids and TROC not in ids
