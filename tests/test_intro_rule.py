"""A typed introduction identifies an unnamed user in code, without waiting for the model."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _chat(client: TestClient, message: str, **body: object) -> dict:
    return client.post("/chat", json={"message": message, **body}).json()


def test_typed_introduction_identifies_an_unnamed_user(client: TestClient) -> None:
    e = _chat(client, "Hi, I'm Layla")
    assert e["identified_user"] and e["identified_user"]["name"] == "Layla"
    assert any(s["stage"] == "tool" and s["name"] == "identify_user" for s in e["trace"]["stages"])
    # Coming back by name in a fresh session finds the same profile.
    e2 = _chat(client, "hi, it's Layla again")
    assert e2["identified_user"]["user_id"] == e["identified_user"]["user_id"]


def test_named_user_is_not_switched_by_a_first_name(client: TestClient) -> None:
    e = _chat(client, "show me hondas", name="Sara Recall")
    uid = e["user_id"]
    e2 = _chat(client, "hi, it's Sara again", user_id=uid)
    assert e2["user_id"] == uid
    assert not any(
        s["stage"] == "tool" and s["name"] == "identify_user" for s in e2["trace"]["stages"]
    )
