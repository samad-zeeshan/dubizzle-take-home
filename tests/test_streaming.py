"""Token streaming: the sentence gate, the structured-reply extractor, and SSE token events end to end."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services import guardrails
from dubizzle_assistant.services.llm.base import LLMResponse
from dubizzle_assistant.services.streaming import ReplyFieldExtractor, SentenceGate
from tests.conftest import make_settings


def test_gate_releases_whole_sentences_through_the_scrub() -> None:
    out: list[str] = []
    gate = SentenceGate(lambda t: guardrails.postfilter(t)[0], out.append)
    gate.feed("Call me on 050 123")
    assert out == []  # no boundary yet, so nothing leaves the gate
    gate.feed(" 4567 today. The Velar")
    assert out == ["Call me on [contact via dubizzle] today. "]
    gate.close()
    assert out[-1] == "The Velar" and gate.emitted.endswith("The Velar")


def feed_in_pieces(extractor: ReplyFieldExtractor, text: str, size: int) -> str:
    return "".join(extractor.feed(text[i : i + size]) for i in range(0, len(text), size))


def test_extractor_finds_the_reply_field_across_any_chunking() -> None:
    want = 'Say "hi"\nAED 1,048 \u00e9'
    doc = json.dumps({"cited_listing_ids": ["R-078"], "reply_markdown": want, "x": 1})
    for size in (1, 3, 7, 50):
        assert feed_in_pieces(ReplyFieldExtractor(), doc, size) == want, size


def test_extractor_handles_escape_cut_at_chunk_boundary() -> None:
    ex = ReplyFieldExtractor()
    assert ex.feed('{"reply_markdown": "a\\') == "a"
    assert ex.feed("nb\\u00") == "\nb"
    assert ex.feed('e9c"}') == "\u00e9c"
    assert ex.feed(" trailing") == ""


class StreamingFake:
    """Wraps the offline model and replays its text in pieces, the way a real stream would."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.streamed_calls = 0

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kw: Any
    ) -> LLMResponse:
        return self.inner.complete(messages, tools, **kw)

    def complete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        on_token: Callable[[str], None],
        **kw: Any,
    ) -> LLMResponse:
        resp = self.inner.complete(messages, tools, **kw)
        self.streamed_calls += 1
        text = resp.text or ""
        for i in range(0, len(text), 9):
            on_token(text[i : i + 9])
        return resp

    def embed(self, text: str) -> list[float]:
        return self.inner.embed(text)


def test_stream_endpoint_emits_scrubbed_tokens_then_the_envelope(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        fake = StreamingFake(app.state.llm)
        app.state.llm = fake
        with c.stream(
            "POST", "/chat/stream", json={"message": "show me hondas", "name": "Sam"}
        ) as r:
            events: list[tuple[str, Any]] = []
            name = None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: ") and name:
                    events.append((name, json.loads(line[6:])))
    kinds = [e[0] for e in events]
    assert fake.streamed_calls == 1
    assert "token" in kinds and kinds[-1] == "envelope"
    assert kinds.index("token") < kinds.index("envelope")
    env = events[-1][1]
    draft = "".join(d["text"] for k, d in events if k == "token")
    assert draft.strip() == env["reply"].strip()
    assert env["streamed"] == {"chars": len(draft), "matches_reply": True}
    assert [c["id"] for c in env["cars"]] == ["R-078"]


def _streamed_reply(client, body):
    with client.stream("POST", "/chat/stream", json=body) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if isinstance(data, dict) and data.get("reply"):
                    return data["reply"]
    return ""


def test_the_stream_replies_in_the_language_it_was_given(client):
    """The route accepted locale and then dropped it, so the Arabic toggle did nothing here."""
    message = "how many planets are there"
    plain = client.post("/chat", json={"message": message, "locale": "ar"}).json()["reply"]
    streamed = _streamed_reply(client, {"message": message, "locale": "ar"})

    def arabic(text):
        return any("؀" <= ch <= "ۿ" for ch in text or "")

    assert arabic(plain), "the non-streaming route should already answer in Arabic"
    assert arabic(streamed), "locale=ar reached the stream route and came back English"
