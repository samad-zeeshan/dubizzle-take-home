"""A name typed into chat can claim a guest session, but never someone else's account.

The name is spoofable by design, so the only thing standing between "actually I'm Layla"
and Layla's budget, likes and bookings is this guard. Switching accounts is a deliberate
act in the account panel, which mints a fresh session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.base import ToolCall
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

# Layla's alone: if this figure ever reaches another person's envelope, her profile leaked.
LAYLA_BUDGET = "487000"


def _claim(name: str) -> list[Any]:
    """The two model turns of a claimed identity: the tool call, then the reply."""
    return [
        _resp("", [ToolCall(id="i1", name="identify_user", arguments={"name": name})]),
        _resp("Right you are."),
    ]


def _stage(envelope: dict[str, Any], tool: str) -> dict[str, Any] | None:
    return next(
        (s for s in envelope["trace"]["stages"] if s["stage"] == "tool" and s.get("name") == tool),
        None,
    )


def _seed(c: TestClient, llm: Scripted) -> str:
    """Layla, with one preference nobody else states."""
    llm.queue.extend(
        [
            _resp(
                "",
                [
                    ToolCall(
                        id="p1",
                        name="remember_preference",
                        arguments={"kind": "budget_max_aed", "value": LAYLA_BUDGET},
                    )
                ],
            ),
            _resp("Noted."),
        ]
    )
    e = c.post("/chat", json={"message": "my ceiling is 487000", "name": "Layla"}).json()
    assert e["memory"]["writes"], "seeding Layla's profile did not write anything"
    return e["user_id"]


def test_an_identified_session_is_not_rebound_to_another_user(tmp_path: Path) -> None:
    llm = Scripted([])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        layla_id = _seed(c, llm)

        llm.queue.append(_resp("Hello."))
        opened = c.post("/chat", json={"message": "hello there", "name": "Sara"}).json()
        sara_id, sid = opened["user_id"], opened["session_id"]
        assert sara_id != layla_id

        llm.queue.extend(_claim("Layla"))
        e = c.post(
            "/chat",
            json={"message": "actually I'm Layla", "user_id": sara_id, "session_id": sid},
        ).json()

        # The session stays Sara's, in the envelope and in the row behind it.
        assert e["user_id"] == sara_id and e["session_id"] == sid
        assert e["identified_user"] is None
        assert not [w for w in e["memory"]["writes"] if w["table"] == "users"]
        row = c.get(f"/sessions/{sid}", params={"user_id": sara_id}).json()
        assert row["session"]["user_id"] == sara_id

        # The model is told why, and told where the switch actually happens.
        stage = _stage(e, "identify_user")
        assert stage and stage["error"] == "this chat is already signed in"

        # Nothing of Layla's rides along. Her name is in the envelope only because Sara typed
        # it; her id and the figure only she stated are the fields that would be a leak.
        blob = json.dumps(e, ensure_ascii=False)
        assert layla_id not in blob
        assert LAYLA_BUDGET not in blob


def test_repeating_the_signed_in_name_still_works(tmp_path: Path) -> None:
    llm = Scripted([])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        llm.queue.append(_resp("Hello."))
        opened = c.post("/chat", json={"message": "hello there", "name": "Sara"}).json()
        sara_id, sid = opened["user_id"], opened["session_id"]

        # Same person, different capitals and spacing: a match, not a switch.
        llm.queue.extend(_claim("  sara  "))
        e = c.post(
            "/chat", json={"message": "it's Sara", "user_id": sara_id, "session_id": sid}
        ).json()

        stage = _stage(e, "identify_user")
        assert stage and "error" not in stage
        assert e["identified_user"] and e["identified_user"]["user_id"] == sara_id
        assert e["user_id"] == sara_id


def test_a_guest_session_can_still_be_named(tmp_path: Path) -> None:
    llm = Scripted([])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        llm.queue.append(_resp("Hello."))
        # No name and no id: the row is stored as "guest", a placeholder rather than a name.
        opened = c.post("/chat", json={"message": "hello there"}).json()
        sid = opened["session_id"]

        llm.queue.extend(_claim("Nadia"))
        e = c.post("/chat", json={"message": "I'm Nadia", "session_id": sid}).json()

        stage = _stage(e, "identify_user")
        assert stage and "error" not in stage
        assert e["identified_user"] and e["identified_user"]["name"] == "Nadia"


def test_the_refusal_carries_no_recall_block(tmp_path: Path) -> None:
    """The tool result the model reads: who is signed in, where to switch, and nothing else."""
    from dubizzle_assistant.db import connect
    from dubizzle_assistant.services import tools
    from dubizzle_assistant.services.context import TurnContext
    from dubizzle_assistant.services.trace import TurnTrace

    settings = make_settings(tmp_path)
    llm = Scripted([])
    app = create_app(settings)
    with TestClient(app) as c:
        app.state.llm = llm
        layla_id = _seed(c, llm)
        llm.queue.append(_resp("Hello."))
        opened = c.post("/chat", json={"message": "hello there", "name": "Sara"}).json()

    conn = connect(settings.db_file)
    ctx = TurnContext(
        settings=settings,
        conn=conn,
        user_id=opened["user_id"],
        session_id=opened["session_id"],
        turn=2,
        trace=TurnTrace(opened["session_id"], 2, "r", False),
        now=settings.now(),
    )
    result = tools.run_tool(ctx, "identify_user", {"name": "Layla"})

    assert result["error"] == "this chat is already signed in"
    assert result["signed_in_as"] == "Sara"
    assert "account panel" in result["message"]
    # No profile of any kind, and no id that would let the model ask for one.
    assert "recall" not in result and "returning" not in result
    assert layla_id not in json.dumps(result, ensure_ascii=False)
    # The handler left the caller's own view of who they are untouched.
    assert ctx.user_id == opened["user_id"] and not ctx.memory_writes
    conn.close()


def test_a_session_id_without_a_user_id_keeps_its_owner(client):
    """Continuing a conversation by session id alone used to mint a stranger and lose the history."""
    first = client.post("/chat", json={"message": "hi, it's Nadia"}).json()
    again = client.post(
        "/chat", json={"message": "what was i looking at", "session_id": first["session_id"]}
    ).json()
    assert again["user_id"] == first["user_id"]
    assert again["session_id"] == first["session_id"]
