"""Budget phrases written in words, and the order of soft passes under a monthly ceiling."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dubizzle_assistant.normalize import parse_budget


def test_budget_words_parse() -> None:
    assert parse_budget("under 150 thousand").amount_aed == 150_000  # type: ignore[union-attr]
    assert parse_budget("2 million").amount_aed == 2_000_000  # type: ignore[union-attr]
    assert parse_budget("150k").amount_aed == 150_000  # type: ignore[union-attr]
    assert parse_budget("about 1.2M").amount_aed == 1_200_000  # type: ignore[union-attr]


def test_monthly_budget_ranks_listed_instalments_first(client: TestClient) -> None:
    rows = client.get(
        "/inventory/search", params={"budget_text": "under 2000 a month", "limit": 12}
    ).json()["results"]
    known = [r["monthly_aed"] is not None for r in rows]
    # A car with no instalment listed is a soft pass and never outranks one that states a figure.
    assert known == sorted(known, reverse=True)
    assert all(r["monthly_aed"] <= 2000 for r in rows if r["monthly_aed"] is not None)
    assert known[0] is True


def test_cash_budget_ranks_listed_prices_first(client: TestClient) -> None:
    rows = client.get("/inventory/search", params={"price_max_aed": 100_000, "limit": 12}).json()[
        "results"
    ]
    known = [r["price_aed"] is not None for r in rows]
    assert known == sorted(known, reverse=True)
