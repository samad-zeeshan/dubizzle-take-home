"""A constraint the customer stated is honoured, and a superlative says what it covers.

Report breaks 18 and 10: "absolutely nothing brand new" produced no WHERE clause at all, and
"the cheapest Rolls-Royce" named a car out of eleven where ten state no price.
"""

from __future__ import annotations

from dubizzle_assistant.services import inventory
from dubizzle_assistant.services.inventory import SearchFilters

USED_ONLY = "I only want used cars, absolutely nothing brand new. Show me the newest ones you have."


def _search(conn, limit=10, **kw):
    return inventory.search(conn, SearchFilters(**kw), mode="structured", limit=limit)


def test_nothing_brand_new_reaches_the_sql(inventory_conn):
    out = _search(inventory_conn, is_brand_new=False, sort="year_desc", limit=5)
    assert "is_brand_new = 0" in out.executed["sql"]
    assert out.applied_filters.get("is_brand_new") is False or "is_brand_new" in str(
        out.executed["sql"]
    )
    rows = inventory_conn.execute(
        "SELECT id FROM listings WHERE is_brand_new = 1 LIMIT 1"
    ).fetchall()
    assert rows, "the dataset has no brand new cars, so this test proves nothing"
    brand_new = {
        r["id"] for r in inventory_conn.execute("SELECT id FROM listings WHERE is_brand_new = 1")
    }
    assert not [c for c in out.results if c["id"] in brand_new], "a brand new car came back"


def test_the_positive_form_still_works(inventory_conn):
    out = _search(inventory_conn, is_brand_new=True, limit=5)
    assert "is_brand_new = 1" in out.executed["sql"]
    assert out.results and all(c["is_brand_new"] for c in out.results)


def test_no_warranty_is_a_filter_not_a_shrug(inventory_conn):
    out = _search(inventory_conn, has_warranty=False, limit=5)
    assert "has_warranty = 0" in out.executed["sql"]
    assert out.results and not any(c["has_warranty"] for c in out.results)


def test_a_cheapest_sort_says_how_many_state_no_price(inventory_conn):
    out = _search(inventory_conn, make="rolls-royce", sort="price_asc", limit=5)
    assert out.price_buckets["price_not_listed"] > 0
    assert out.sort_caveat is not None
    assert str(out.price_buckets["price_not_listed"]) in out.sort_caveat
    assert "listed prices only" in out.sort_caveat


def test_no_caveat_when_every_match_states_a_price(inventory_conn):
    out = _search(inventory_conn, make="rolls-royce", sort="year_desc", limit=5)
    assert out.sort_caveat is None, "the caveat belongs to a price sort only"
