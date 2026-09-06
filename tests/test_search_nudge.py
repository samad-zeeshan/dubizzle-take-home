"""A model that answers a stock question from memory is sent back to search once."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.base import LLMResponse, ToolCall
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
    """Answers from a fixed queue, the way a small model that skipped its tools would."""

    name = "scripted"
    model = "scripted"

    def __init__(self, queue: list[LLMResponse]) -> None:
        self.queue = queue
        self.seen: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]], tools: Any = None, **kw: Any) -> LLMResponse:
        self.seen.append(list(messages))
        return self.queue.pop(0)

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("no embeddings in this test")


def test_stock_question_without_a_search_is_sent_back(tmp_path: Path) -> None:
    llm = Scripted(
        [
            _resp("There are no convertibles in the current inventory."),
            _resp(
                "",
                [ToolCall(id="1", name="search_inventory", arguments={"body_type": "convertible"})],
            ),
            _resp("Here are the convertibles in stock."),
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post(
            "/chat", json={"message": "what convertibles do you have?", "name": "Nudge"}
        ).json()
    assert any(s["stage"] == "search_nudge" for s in e["trace"]["stages"])
    assert [x["id"] for x in e["cars"]]
    assert e["reply"].startswith("Here are the convertibles")
    # The nudge reached the model as a system note after the user's message.
    assert llm.seen[1][-1]["role"] == "system" and "search_inventory" in llm.seen[1][-1]["content"]


def test_reference_questions_are_left_alone(tmp_path: Path) -> None:
    llm = Scripted([_resp("Hello! What are you looking for today?")])
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": "hi", "name": "Nudge"}).json()
    assert not any(s["stage"] == "search_nudge" for s in e["trace"]["stages"])
    assert not llm.queue
