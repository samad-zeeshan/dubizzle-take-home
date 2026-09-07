"""The HTTP surface a reviewer will drive from /docs: health, search, detail, compare."""

from __future__ import annotations

import json

from dubizzle_assistant.text import PHONE_RE


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["inventory_count"] == 189
    assert body["db_ok"] is True
    assert body["llm"]["configured"] is True
    assert body["retrieval_mode"] == "hybrid"
    assert body["ablations_active"] == []
    assert body["inventory"]["source_file"] == "cars.xlsx"
    assert body["inventory"]["listings"] == 189
    assert body["inventory"]["llm_model"]


def test_every_router_is_mounted(client):
    # These four used to be imported in a try/except that swallowed any ImportError,
    # so a typo inside one of them removed its routes without a word.
    paths = client.get("/openapi.json").json()["paths"]
    for p in (
        "/bookings",
        "/leads/contact",
        "/chat/stream",
        "/inventory/{listing_id}/availability",
    ):
        assert p in paths, p


def test_reading_the_lead_table_needs_the_debug_flag(tmp_path):
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path, debug_endpoints=False))) as c:
        paths = c.get("/openapi.json").json()["paths"]
    # The account form posts contacts on any deployment; only the admin page reads them back.
    assert "/leads/contact" in paths
    assert "/leads" not in paths and "/leads.csv" not in paths


def test_search_honda(client):
    r = client.get("/inventory/search", params={"make": "honda"}).json()
    assert r["total_matches"] == 1
    car = r["results"][0]
    assert car["make"] == "honda" and car["mileage_km"] == 79000 and car["price_aed"] is None
    assert car["explain"]["matched_filters"] == ["make"]
    assert r["executed"]["sql"].startswith("SELECT")
    assert "make = :make" in r["executed"]["sql"]


def test_search_alias_and_conversion(client):
    r = client.get("/inventory/search", params={"make": "Merc"}).json()
    assert any("mercedes-benz (alias)" in s for s in r["normalization"])
    assert r["total_matches"] >= 20
    r = client.get(
        "/inventory/search", params={"body_type": "suv", "color": "white", "budget_text": "$20k"}
    ).json()
    assert any("73,450 AED" in s for s in r["normalization"])
    # One white SUV states a price under AED 73k (the Bestune T99). The rest pass softly with no
    # listed price, the buckets say so, and the priced one is ranked first.
    b = r["price_buckets"]
    assert r["total_matches"] > 0
    assert b["listed_within_budget"] == 1
    assert b["listed_within_budget"] + b["price_not_listed"] == r["total_matches"]
    assert b["excluded_over_budget"] >= 1
    assert all(c["body_type"] == "suv" for c in r["results"])
    assert r["results"][0]["price_aed"] is not None
    assert all("soft pass" in " ".join(c["explain"]["matched_filters"]) for c in r["results"][1:])


def test_search_range_rover_family(client):
    r = client.get("/inventory/search", params={"model": "range rover", "limit": 20}).json()
    models = {c["model"] for c in r["results"]}
    assert "range rover velar" in models and "range rover sport" in models


def test_search_keywords_use_fts(client):
    r = client.get("/inventory/search", params={"keywords": "panoramic roof"}).json()
    assert r["executed"]["fts"]
    assert r["total_matches"] > 0
    assert r["results"][0]["explain"]["bm25"] is not None
    r2 = client.get(
        "/inventory/search", params={"keywords": "panoramic roof", "mode": "structured"}
    ).json()
    assert "keywords ignored in structured mode" in r2["normalization"]


def test_embeddings_mode_unavailable_is_a_clean_503(client):
    r = client.get("/inventory/search", params={"make": "bmw", "mode": "embeddings"})
    assert r.status_code == 503
    assert "embeddings" in r.json()["detail"]


def test_listing_detail_has_provenance_and_no_contacts(client):
    r = client.get("/inventory/C-003")
    assert r.status_code == 200
    d = r.json()
    assert d["fields"]["price_aed"]["value"] == 119750
    assert "119,750" in d["fields"]["price_aed"]["evidence"]
    assert d["fields"]["body_type"]["source"] == "inferred"
    assert not PHONE_RE.search(d["description_original"])
    assert "dealer_contact" not in d
    assert d["thumb_url"].endswith("?imwidth=400")


def test_unknown_listing_404(client):
    assert client.get("/inventory/Z-999").status_code == 404


def test_compare(client):
    r = client.get("/inventory/compare", params={"ids": "C-003,C-044"}).json()
    assert r["ids"] == ["C-003", "C-044"]
    assert len(r["table"]["year"]) == 2
    assert client.get("/inventory/compare", params={"ids": "C-003"}).status_code == 422
    assert client.get("/inventory/compare", params={"ids": "C-003,Z-1"}).status_code == 404


def test_no_phone_numbers_in_any_search_payload(client):
    r = client.get("/inventory/search", params={"limit": 50, "offset": 0})
    text = json.dumps(r.json(), ensure_ascii=False)
    assert not PHONE_RE.search(text)
    r = client.get("/inventory/search", params={"limit": 50, "offset": 150})
    assert not PHONE_RE.search(json.dumps(r.json(), ensure_ascii=False))


def test_makes(client):
    makes = client.get("/inventory/makes").json()
    assert "mercedes-benz" in makes and "tova" in makes and len(makes) >= 40
