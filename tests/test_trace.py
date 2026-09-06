"""The flight recorder: every stage present and ordered, nothing sensitive stored."""

from __future__ import annotations

import json

from dubizzle_assistant.services.trace import TurnTrace, redact
from dubizzle_assistant.text import PHONE_RE


def test_redact_drops_forbidden_keys_and_scrubs_strings():
    obj = {
        "dealer_contact": {"phones": ["971501234567"]},
        "description_raw": "call 050 123 4567",
        "gemini_api_key": "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "nested": {
            "phone": "x",
            "text": "ring +971 55 123 4567 or mail a@b.ae, key AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        },
        "tokens": 42,
        "auth_token": "secret",
    }
    out = redact(obj)
    assert (
        "dealer_contact" not in out and "description_raw" not in out and "gemini_api_key" not in out
    )
    assert "phone" not in out["nested"]
    assert out["tokens"] == 42
    assert out["auth_token"] == "[redacted]"
    text = out["nested"]["text"]
    assert "[phone]" in text and "[email]" in text and "[key]" in text
    assert not PHONE_RE.search(text) and "AIza" not in text


def test_stage_records_time_and_payload():
    t = TurnTrace("s", 1, "r", ["sanitizer"])
    with t.stage("tool", name="search_inventory") as rec:
        rec["total_matches"] = 3
    t.add("reply", chars=10)
    d = t.to_dict()
    assert [s["stage"] for s in d["stages"]] == ["tool", "reply"]
    assert d["stages"][0]["name"] == "search_inventory" and d["stages"][0]["total_matches"] == 3
    assert "ms" in d["stages"][0] and d["ablations_active"] == ["sanitizer"]


def test_turn_trace_is_stored_and_served(client):
    e = client.post("/chat", json={"message": "show me hondas", "name": "Trace Tester"}).json()
    sid = e["session_id"]
    stages = [s["stage"] for s in e["trace"]["stages"]]
    for expected in (
        "received",
        "prefilter",
        "resolver",
        "memory_read",
        "prompt",
        "llm_call",
        "tool",
        "llm_call",
        "structured_reply",
        "postfilter",
        "grounding",
        "persist",
        "reply",
    ):
        assert expected in stages, expected
    assert (
        stages.index("prompt")
        < stages.index("llm_call")
        < stages.index("tool")
        < stages.index("grounding")
    )
    tool = next(s for s in e["trace"]["stages"] if s["stage"] == "tool")
    assert tool["executed"]["sql"].startswith("SELECT") and tool["stage_counts"]
    listed = client.get(f"/debug/turns/{sid}").json()
    assert listed[0]["tools"] == ["search_inventory"] and listed[0]["intent"] == "inventory_search"
    full = client.get(f"/debug/turns/{sid}/1").json()
    assert full["request_id"] == e["request_id"]
    text = json.dumps(full, ensure_ascii=False)
    assert "dealer_contact" not in text and not PHONE_RE.search(text)


def test_prompt_inspector(client):
    e = client.post("/chat", json={"message": "show me toyotas", "name": "Prompt Tester"}).json()
    client.post(
        "/chat",
        json={
            "message": "what's the mileage on the first one?",
            "user_id": e["user_id"],
            "session_id": e["session_id"],
        },
    )
    p = client.get(f"/debug/prompt/{e['session_id']}").json()
    names = [b["name"] for b in p["blocks"]]
    assert names[0] == "static" and "datetime" in names and "focus" in names and "resolved" in names
    assert all(isinstance(b["tokens"], int) and b["tokens"] > 0 for b in p["blocks"])
    assert p["diff_vs_previous_turn"]
    assert "Cars on screen" in next(b["text"] for b in p["blocks"] if b["name"] == "focus")


def test_debug_endpoints_absent_when_disabled(tmp_path):
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path, debug_endpoints=False))) as c:
        assert c.get("/debug/config").status_code == 404
        assert c.get("/health").json()["debug_endpoints"] is False
