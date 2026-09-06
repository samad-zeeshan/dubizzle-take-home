"""Record once, replay forever: the cassette makes the demo reproducible without a key."""

from __future__ import annotations

import json

import pytest

from dubizzle_assistant.services.llm.cassette import CassetteClient, CassetteMissError
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
