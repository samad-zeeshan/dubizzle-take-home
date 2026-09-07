"""The enrichment pass has to finish whatever a model's output ceiling turns out to be.

It used to fail silently: a batch too big for the reply came back truncated, the error was
swallowed, and the regex values stood as though the model had agreed with them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dubizzle_assistant.ingest.enrich import make_enricher
from dubizzle_assistant.services.llm.base import LLMError, LLMResponse, RateLimitedError


def _record(n: int) -> dict[str, Any]:
    return {
        "id": f"X-{n:03d}",
        "title": f"Car {n}",
        "make": "toyota",
        "model": "corolla",
        "year": 2020,
        "description_clean": f"Listing {n} in good condition, GCC specs.",
        "english_summary": "",
        "keywords_en": "",
        "fields": {},
    }


class CeilingLLM:
    """Answers only when the batch is small enough to fit its reply, like a real ceiling."""

    name = "ceiling"
    model = "ceiling/test"

    def __init__(self, fits: int, fail_ids: set[str] | None = None) -> None:
        self.fits = fits
        self.fail_ids = fail_ids or set()
        self.batch_sizes: list[int] = []

    def complete(self, messages: list[dict[str, Any]], tools: Any = None, **kw: Any) -> LLMResponse:
        payload = json.loads(messages[-1]["content"])
        self.batch_sizes.append(len(payload))
        if len(payload) > self.fits or any(p["id"] in self.fail_ids for p in payload):
            return LLMResponse(None, [], "length", {}, {}, self.model, 1)
        listings = [{"id": p["id"], "price_aed": 50000 + int(p["id"][-3:])} for p in payload]
        return LLMResponse(json.dumps({"listings": listings}), [], "stop", {}, {}, self.model, 1)

    def embed(self, text: str) -> list[float]:
        raise LLMError("no embeddings here")


def _enrich(tmp_path, llm, records, batch_size=8):
    enricher = make_enricher(batch_size=batch_size, cache_path=tmp_path / "cache.json", client=llm)
    enricher(records)
    return json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))


def test_a_batch_too_big_for_the_reply_is_split_until_it_fits(tmp_path):
    llm = CeilingLLM(fits=2)
    records = [_record(i) for i in range(8)]
    cache = _enrich(tmp_path, llm, records)

    assert len(cache) == 8, "every listing should be answered once the batch is small enough"
    assert max(llm.batch_sizes) == 8, "it should try the whole batch first"
    assert min(llm.batch_sizes) <= 2, "and halve until the reply fits"


def test_one_listing_the_model_will_not_answer_does_not_lose_the_others(tmp_path):
    llm = CeilingLLM(fits=8, fail_ids={"X-003"})
    records = [_record(i) for i in range(8)]
    cache = _enrich(tmp_path, llm, records)

    answered = {item["id"] for item in cache.values()}
    assert answered == {f"X-{i:03d}" for i in range(8)} - {"X-003"}


def test_a_listing_with_no_text_is_never_sent(tmp_path):
    llm = CeilingLLM(fits=8)
    records = [_record(0), _record(1)]
    records[1]["description_clean"] = "   "
    cache = _enrich(tmp_path, llm, records)

    assert [item["id"] for item in cache.values()] == ["X-000"]
    assert llm.batch_sizes == [1], "the empty listing never reaches the model"


def test_the_daily_quota_stops_the_pass_with_its_progress_kept(tmp_path):
    class QuotaLLM(CeilingLLM):
        def complete(self, messages, tools=None, **kw):
            payload = json.loads(messages[-1]["content"])
            if any(p["id"] == "X-002" for p in payload):
                raise RateLimitedError("free tier daily cap", daily=True)
            return super().complete(messages, tools, **kw)

    llm = QuotaLLM(fits=1)
    records = [_record(i) for i in range(4)]
    with pytest.raises(RateLimitedError):
        _enrich(tmp_path, llm, records, batch_size=1)

    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert {item["id"] for item in cache.values()} == {"X-000", "X-001"}
