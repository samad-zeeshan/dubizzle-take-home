"""The evaluation report, the transcript export, structured replies, and the event stream."""

from __future__ import annotations

import json

from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.evaluation import evaluate, render
from dubizzle_assistant.services.inventory import load_inventory
from dubizzle_assistant.services.llm.mock_client import ScriptedLLM
from dubizzle_assistant.text import PHONE_RE


def test_evaluation_report(tmp_path, app_settings):
    db = tmp_path / "e.db"
    init_db(db)
    conn = connect(db)
    load_inventory(conn, app_settings.inventory_path)
    report = evaluate(
        conn, app_settings.inventory_path, ("structured", "fts", "hybrid", "embeddings")
    )
    hybrid = report["summary"]["hybrid"]
    assert hybrid["passed"] == hybrid["cases"], [
        r["name"] for r in report["results"]["hybrid"] if not r["passed"]
    ]
    assert report["summary"]["structured"]["passed"] < hybrid["cases"], (
        "structured alone should miss keyword cases"
    )
    assert report["summary"]["fts"]["passed"] < hybrid["cases"], (
        "fts alone should miss filter cases"
    )
    assert report["summary"]["embeddings"]["unavailable"]
    md = render(report)
    assert "| hybrid |" in md and "white suv under $20k" in md
    out = tmp_path / "retrieval_eval.md"
    out.write_text(md, encoding="utf-8")
    assert out.read_text(encoding="utf-8").count("\n") > 30


def test_export_markdown_and_json(client):
    e = client.post("/chat", json={"message": "show me a bmw", "name": "Exporter"}).json()
    client.post(
        "/chat",
        json={
            "message": "what's the mileage on the first one?",
            "user_id": e["user_id"],
            "session_id": e["session_id"],
        },
    )
    md = client.get(f"/sessions/{e['session_id']}/export").text
    assert md.startswith("# Session ") and "## Turn 1" in md and "## Turn 2" in md
    assert "search_inventory" in md and "grounding:" in md
    assert not PHONE_RE.search(md)
    js = client.get(f"/sessions/{e['session_id']}/export", params={"format": "json"}).json()
    assert len(js["traces"]) == 2 and js["messages"][0]["role"] == "user"
    assert "dealer_contact" not in json.dumps(js)
    assert (
        client.get(f"/sessions/{e['session_id']}/export", params={"format": "xml"}).status_code
        == 422
    )
    assert client.get("/sessions/nope/export").status_code == 404


def test_structured_reply_cited_ids_are_validated(client):
    scripted = [
        {"tool_calls": [{"name": "search_inventory", "arguments": {"make": "honda"}}]},
        {
            "text": json.dumps(
                {
                    "reply_markdown": "One Honda: R-078, 79,000 km.",
                    "cited_listing_ids": ["R-078", "Z-999"],
                    "fields_used": ["mileage_km"],
                }
            )
        },
    ]
    real = client.app.state.llm
    try:
        client.app.state.llm = ScriptedLLM(scripted)
        e = client.post("/chat", json={"message": "hondas?", "name": "Structured"}).json()
    finally:
        client.app.state.llm = real
    assert e["structured_reply"] is True and e["cited_listing_ids"] == ["R-078"]
    # The id is dropped from the prose and survives only in cited_listing_ids.
    assert e["reply"] == "One Honda: 79,000 km."
    assert e["post_filter"]["id_leak"] is True
    st = next(s for s in e["trace"]["stages"] if s["stage"] == "structured_reply")
    assert st["dropped_unknown"] == ["Z-999"]
    assert e["grounding"]["ungrounded"] == []


def test_plain_text_reply_still_works(client):
    real = client.app.state.llm
    try:
        client.app.state.llm = ScriptedLLM([{"text": "Happy to help with cars in our inventory."}])
        e = client.post("/chat", json={"message": "thanks!", "name": "Plain"}).json()
    finally:
        client.app.state.llm = real
    assert e["structured_reply"] is False and e["reply"].startswith("Happy to help")


def test_stream_emits_stages_then_envelope(client):
    with client.stream(
        "POST", "/chat/stream", json={"message": "show me hondas", "name": "Streamer"}
    ) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [
        (blk.split("\n", 1)[0].removeprefix("event: "), json.loads(blk.split("\ndata: ", 1)[1]))
        for blk in body.strip().split("\n\n")
        if blk.startswith("event: ")
    ]
    kinds = [k for k, _ in events]
    assert kinds[-1] == "envelope" and kinds.count("stage") >= 6
    labels = [d["label"] for k, d in events if k == "stage"]
    assert any(label.startswith("searched inventory") for label in labels)
    env = events[-1][1]
    assert [c["id"] for c in env["cars"]] == ["R-078"]


def test_summary_kicks_in_on_long_sessions(tmp_path):
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    with TestClient(
        create_app(make_settings(tmp_path, summary_after_turns=4, history_turns=2))
    ) as c:
        e = c.post("/chat", json={"message": "show me toyotas", "name": "Long"}).json()
        uid, sid = e["user_id"], e["session_id"]
        for m in (
            "show me hondas",
            "show me bmws",
            "show me a bentley",
            "show me audis",
            "show me kias",
        ):
            e = c.post("/chat", json={"message": m, "user_id": uid, "session_id": sid}).json()
        stages = [s["stage"] for s in e["trace"]["stages"]]
        assert "summary" in stages
        ctx = c.get(f"/sessions/{sid}", params={"user_id": uid}).json()["context"]
        assert ctx["summary_text"] and ctx["summary_through_turn"] >= 2
        prompt = c.get(f"/debug/prompt/{sid}").json()
        e = c.post(
            "/chat", json={"message": "show me a mini", "user_id": uid, "session_id": sid}
        ).json()
        prompt = c.get(f"/debug/prompt/{sid}").json()
        assert "summary" in [b["name"] for b in prompt["blocks"]]


def test_a_refresh_gets_the_whole_transcript_back(tmp_path):
    """F5 rebuilds the chat from GET /sessions/{id}, so the window the prompt uses must not reach it."""
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    asked = [f"show me hondas {i}" if i % 3 else "hi" for i in range(15)]
    with TestClient(create_app(make_settings(tmp_path, history_turns=2))) as c:
        uid = sid = None
        for m in asked:
            body = {"message": m}
            body.update({"user_id": uid, "session_id": sid} if sid else {"name": "Refresh"})
            e = c.post("/chat", json=body).json()
            uid, sid = e["user_id"], e["session_id"]
        got = c.get(f"/sessions/{sid}", params={"user_id": uid}).json()

    assert got["session"]["turn_counter"] == 15
    assert sorted({m["turn"] for m in got["messages"]}) == list(range(1, 16))
    # What the client keeps after the filter in views.common.restore_history.
    kept = [
        m
        for m in got["messages"]
        if m["role"] in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
        and not m["content"].startswith("{")
    ]
    assert [m["content"] for m in kept if m["role"] == "user"] == asked
    assert sum(1 for m in kept if m["role"] == "assistant") == 15


def test_a_transcript_is_only_returned_to_its_owner(tmp_path):
    """The session id travels in the client's URL, so knowing one must not be enough to read it."""
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path))) as c:
        mine = c.post("/chat", json={"message": "show me hondas", "name": "Owner"}).json()
        theirs = c.post("/chat", json={"message": "show me bmws", "name": "Stranger"}).json()
        sid, uid = mine["session_id"], mine["user_id"]
        assert theirs["user_id"] != uid

        ok = c.get(f"/sessions/{sid}", params={"user_id": uid})
        snooped = c.get(f"/sessions/{sid}", params={"user_id": theirs["user_id"]})
        anonymous = c.get(f"/sessions/{sid}")
        ghost = c.get("/sessions/s_doesnotexist", params={"user_id": uid})

    assert ok.status_code == 200 and ok.json()["messages"]
    # The same 404 either way, so the reply never confirms the id exists.
    assert snooped.status_code == 404 and snooped.json()["detail"] == ghost.json()["detail"]
    assert ghost.status_code == 404
    # Asking without saying who you are is a 422 from the missing parameter, never a transcript.
    assert anonymous.status_code == 422
