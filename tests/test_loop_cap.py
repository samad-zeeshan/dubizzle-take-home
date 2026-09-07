"""Running out of tool steps must not throw away an answer the tools already produced."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.agent import LOOP_CAP_REPLY
from dubizzle_assistant.services.llm.base import LLMError, LLMResponse, ToolCall
from dubizzle_assistant.services.prompts import is_repair_note
from tests.conftest import make_settings


def _resp(text: str, calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=calls or [],
        finish_reason="tool_calls" if calls else "stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        raw_message={},
        model="scripted",
        latency_ms=1,
    )


class Scripted:
    """A model that keeps reaching for one more tool instead of answering."""

    name = "scripted"
    model = "scripted"

    def __init__(self, queue: list[LLMResponse | LLMError]) -> None:
        self.queue = queue
        self.seen: list[list[dict[str, Any]]] = []
        self.tools_seen: list[Any] = []

    def complete(self, messages: list[dict[str, Any]], tools: Any = None, **kw: Any) -> LLMResponse:
        self.seen.append(list(messages))
        self.tools_seen.append(tools)
        item = self.queue.pop(0)
        if isinstance(item, LLMError):
            raise item
        return item

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("no embeddings in this test")


def _bookkeeping() -> list[LLMResponse]:
    # One useful call, then the pattern that burned the live budget: likes and preference writes.
    return [
        _resp("", [ToolCall(id="1", name="search_inventory", arguments={"make": "honda"})]),
        _resp("", [ToolCall(id="2", name="get_listing", arguments={"listing_id": "R-078"})]),
        _resp("", [ToolCall(id="3", name="like_listing", arguments={"listing_id": "R-078"})]),
        _resp(
            "",
            [
                ToolCall(
                    id="4", name="remember_preference", arguments={"kind": "make", "value": "honda"}
                )
            ],
        ),
        _resp("", [ToolCall(id="5", name="like_listing", arguments={"listing_id": "R-078"})]),
        _resp(
            "",
            [
                ToolCall(
                    id="6", name="remember_preference", arguments={"kind": "body", "value": "suv"}
                )
            ],
        ),
    ]


def test_the_cap_gets_one_last_call_with_no_tools(tmp_path: Path) -> None:
    llm = Scripted([*_bookkeeping(), _resp("The 2021 Honda CR-V is the only Honda listed.")])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": "show me hondas", "name": "Cap"}).json()

    assert e["reply"].startswith("The 2021 Honda CR-V")
    assert e["reply"] != LOOP_CAP_REPLY
    cap = next(s for s in e["trace"]["stages"] if s["stage"] == "loop_cap")
    assert cap["recovered"] is True and cap["iterations"] == 7
    # The last call has to arrive with no tools, or the model reaches for a seventh one.
    assert llm.tools_seen[0] is not None and llm.tools_seen[6] is None
    note = llm.seen[6][-1]
    assert note["role"] == "user" and is_repair_note(note["content"])
    # The work the tools already did survives instead of being apologised away.
    assert [x["id"] for x in e["cars"]] == ["R-078"]


def test_the_template_is_the_last_resort(tmp_path: Path) -> None:
    llm = Scripted([*_bookkeeping(), LLMError("no capacity")])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": "show me hondas", "name": "Cap"}).json()

    assert e["reply"] == LOOP_CAP_REPLY
    cap = next(s for s in e["trace"]["stages"] if s["stage"] == "loop_cap")
    assert cap["recovered"] is False
