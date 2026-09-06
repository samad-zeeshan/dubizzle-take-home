"""Make and model phrases the way a model sends them, not the way the schema wants them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dubizzle_assistant.services.memory import resolve_reference

SPORTS = {"C-044", "R-071", "R-013"}


def _ids(client: TestClient, **params: object) -> list[str]:
    body = client.get("/inventory/search", params={**params, "limit": 8}).json()
    return [r["id"] for r in body["results"]]


def test_model_name_sent_as_the_make(client: TestClient) -> None:
    assert set(_ids(client, make="range rover", model="sport")) == SPORTS
    assert set(_ids(client, make="range rover sport")) == SPORTS
    assert _ids(client, make="velar") == ["C-003"] or "C-003" in _ids(client, make="velar")


def test_model_phrase_matches_whole_words_anywhere(client: TestClient) -> None:
    assert set(_ids(client, make="land rover", model="sport")) == SPORTS
    assert _ids(client, model="velar") == ["C-003"]
    assert _ids(client, make="mazda", model="3") == ["C-012"]
    # A bare "3" must not pull in the 330i through a substring match.
    assert "R-037" not in _ids(client, make="mazda", model="3")


def test_named_make_not_on_screen_is_a_search() -> None:
    shown = [
        {"id": "C-061", "make": "toyota", "model": "camry", "price_aed": 36999, "year": 2018},
        {"id": "R-005", "make": "haval", "model": "h9", "price_aed": 115750, "year": 2026},
    ]
    assert resolve_reference("cheapest mercedes you have", shown, "R-005")["resolved"] is None
    assert resolve_reference("the cheaper one", shown, "R-005")["resolved"] == "C-061"
    assert resolve_reference("the haval, what mileage?", shown, None)["resolved"] == "R-005"
