"""Record once, replay forever: the cassette makes the demo reproducible without a key."""

from __future__ import annotations

import json

import pytest

from dubizzle_assistant.services.llm.base import ToolCall
from dubizzle_assistant.services.llm.cassette import CassetteClient, CassetteMissError, _key
from dubizzle_assistant.services.llm.mock_client import ScriptedLLM
from dubizzle_assistant.text import PHONE_RE


def test_record_then_replay(tmp_path):
    path = tmp_path / "c.jsonl"
    inner = ScriptedLLM(
        [
            {"tool_calls": [{"name": "search_inventory", "arguments": {"make": "honda"}}]},
            {"text": "one honda, R-078, 79,000 km"},
        ]
    )
    rec = CassetteClient(inner, path, "record")
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "show me hondas, my number is +971 50 123 4567"},
    ]
    a = rec.complete(msgs, [{"type": "function", "function": {"name": "search_inventory"}}])
    b = rec.complete(
        [*msgs, {"role": "assistant", "content": ""}, {"role": "tool", "content": "{}"}]
    )
    assert a.tool_calls[0].name == "search_inventory" and b.text.startswith("one honda")
    assert path.exists() and len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert not PHONE_RE.search(path.read_text(encoding="utf-8"))

    rep = CassetteClient(None, path, "replay")
    a2 = rep.complete(msgs, [{"type": "function", "function": {"name": "search_inventory"}}])
    assert a2.cassette_hit and a2.tool_calls[0].arguments == {"make": "honda"}
    b2 = rep.complete(
        [*msgs, {"role": "assistant", "content": ""}, {"role": "tool", "content": "{}"}]
    )
    assert b2.text == b.text
    with pytest.raises(CassetteMissError):
        rep.complete([{"role": "user", "content": "something never recorded"}])


def test_replay_through_the_api(tmp_path):
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    path = tmp_path / "demo.jsonl"
    with TestClient(
        create_app(
            make_settings(tmp_path / "a", llm_cassette_mode="record", llm_cassette_path=path)
        )
    ) as c:
        first = c.post("/chat", json={"message": "show me hondas", "name": "Cassette"}).json()
    assert path.exists()
    recorded = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(recorded) >= 2 and recorded[0]["request"]["last_user"] == "show me hondas"
    with TestClient(
        create_app(
            make_settings(
                tmp_path / "b",
                llm_provider="litellm",
                gemini_api_key=None,
                llm_cassette_mode="replay",
                llm_cassette_path=path,
            )
        )
    ) as c:
        assert c.get("/health").json()["llm"]["cassette_mode"] == "replay"
        second = c.post("/chat", json={"message": "show me hondas", "name": "Cassette"}).json()
        assert second["reply"] == first["reply"]
        assert all(
            s.get("cassette_hit") for s in second["trace"]["stages"] if s["stage"] == "llm_call"
        )
        miss = c.post(
            "/chat",
            json={
                "message": "something never recorded",
                "user_id": second["user_id"],
                "session_id": second["session_id"],
            },
        )
        assert miss.status_code == 503 and "no recording" in miss.json()["detail"]


def test_one_recording_replays_more_than_once(tmp_path):
    """Building the response edited the store in place, so the second replay raised TypeError."""
    client = CassetteClient(inner=None, path=tmp_path / "none.jsonl", mode="replay")
    messages = [{"role": "user", "content": "show me a white SUV under 150k"}]
    tools = [{"type": "function", "function": {"name": "search_inventory"}}]
    key = _key(client._payload("complete", messages=messages, tools=tools, schema=None))
    client._store[key] = {
        "key": key,
        "response": {
            "text": None,
            "tool_calls": [{"id": "c1", "name": "search_inventory", "arguments": {}}],
            "finish_reason": "tool_calls",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "raw_message": {},
            "model": "gemini/gemini-3.5-flash-lite",
            "latency_ms": 3,
        },
    }
    for attempt in range(3):
        out = client.complete(messages, tools)
        assert isinstance(out.tool_calls[0], ToolCall), (
            f"replay {attempt + 1} returned the wrong type"
        )
        assert out.tool_calls[0].name == "search_inventory"
