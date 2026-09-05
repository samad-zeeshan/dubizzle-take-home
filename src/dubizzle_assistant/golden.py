"""
Golden queries for retrieval evaluation, with expectations derived from the inventory.

Each case is a query as the search tool receives it, a predicate that says
which listings ought to match, and the bar the result must clear. Expected
sets are computed from inventory.json at run time, never typed by hand, so
they stay true when the extraction improves.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Rec = dict[str, Any]


def fv(rec: Rec, key: str) -> Any:
    return rec["fields"][key]["value"]


def _rr(rec: Rec) -> bool:
    return rec["make"] == "land rover" and rec["model"].startswith("range rover")


@dataclass
class Case:
    name: str
    args: dict[str, Any]
    expected: Callable[[Rec], bool]
    k: int = 5
    min_precision: float = 1.0
    min_recall: float | None = None
    expect_relaxed: bool = False
    check: Callable[[dict[str, Any], dict[str, Rec]], bool] | None = None
    note: str = ""


CASES: list[Case] = [
    Case("the only honda", {"make": "honda"}, lambda r: r["make"] == "honda", k=1, min_recall=1.0),
    Case(
        "toyota must not surface the honda",
        {"make": "toyota"},
        lambda r: r["make"] == "toyota",
        k=5,
        min_recall=1.0,
        note="the CR-V's title says 'Toyota Service History'",
    ),
    Case(
        "white suv under $20k (the PDF's example)",
        {"body_type": "suv", "color": "white", "budget_text": "$20k"},
        lambda r: fv(r, "body_type") == "suv" and fv(r, "exterior_color") == "white",
        k=5,
        check=lambda res, by: (
            res["price_buckets"]["listed_within_budget"] == 1
            and res["price_buckets"]["excluded_over_budget"] >= 1
            and res["results"][0]["price_aed"] is not None
        ),
        note="one white SUV (Bestune T99) is priced under AED 73k, two are over, the rest state no price",
    ),
    Case(
        "range rover under 150k",
        {"model": "range rover", "price_max_aed": 150000},
        lambda r: _rr(r) and (fv(r, "price_aed") is None or fv(r, "price_aed") <= 150000),
        k=5,
        min_recall=1.0,
        check=lambda res, by: (
            "C-003" in [c["id"] for c in res["results"]]
            and res["price_buckets"]["excluded_over_budget"] >= 1
        ),
    ),
    Case(
        "cheapest mercedes",
        {"make": "mercedes-benz", "sort": "price_asc"},
        lambda r: r["make"] == "mercedes-benz",
        k=5,
        check=lambda res, by: (
            res["results"][0]["price_aed"]
            == min(
                fv(x, "price_aed")
                for x in by.values()
                if x["make"] == "mercedes-benz" and fv(x, "price_aed")
            )
        ),
    ),
    Case(
        "electric cars",
        {"fuel_type": "electric"},
        lambda r: fv(r, "fuel_type") == "electric",
        k=5,
        min_recall=1.0,
    ),
    Case(
        "under 2000 a month",
        {"budget_text": "under 2000 a month"},
        lambda r: fv(r, "monthly_aed") is None or fv(r, "monthly_aed") <= 2000,
        k=5,
        check=lambda res, by: all(
            c["monthly_aed"] is None or c["monthly_aed"] <= 2000 for c in res["results"]
        ),
    ),
    Case(
        "seven seater",
        {"keywords": "7 seats"},
        lambda r: "7 seats" in r["keywords_en"],
        k=3,
        min_precision=0.66,
    ),
    Case(
        "brand new cars",
        {"is_brand_new": True},
        lambda r: bool(fv(r, "is_brand_new")),
        k=5,
        min_recall=1.0,
        note="brand new tyres are not a brand new car",
    ),
    Case(
        "gcc 2023 or newer with warranty",
        {"regional_spec": "gcc", "year_min": 2023, "has_warranty": True},
        lambda r: (
            fv(r, "regional_spec") == "gcc" and r["year"] >= 2023 and bool(fv(r, "has_warranty"))
        ),
        k=5,
        min_recall=1.0,
    ),
    Case(
        "corolla (arabic only listing)",
        {"model": "corolla"},
        lambda r: r["model"] == "corolla",
        k=1,
        min_recall=1.0,
    ),
    Case(
        "patrol incl. arabic only rows",
        {"model": "patrol"},
        lambda r: r["make"] == "nissan" and r["model"].startswith("patrol"),
        k=5,
        min_recall=1.0,
    ),
    Case(
        "mazda 3 (int-typed model cell)",
        {"make": "mazda", "model": "3"},
        lambda r: r["make"] == "mazda" and r["model"] == "3",
        k=1,
        min_recall=1.0,
    ),
    Case(
        "dbx 707 (int-typed trim cell)",
        {"model": "dbx"},
        lambda r: r["model"] == "dbx",
        k=1,
        min_recall=1.0,
    ),
    Case(
        "phantom (shared dealer paragraph)",
        {"model": "phantom"},
        lambda r: r["model"] == "phantom",
        k=2,
        min_recall=1.0,
    ),
    Case(
        "merc c300 via aliases",
        {"make": "merc", "model": "c300"},
        lambda r: r["make"] == "mercedes-benz" and r["model"] == "c-class",
        k=5,
        min_recall=1.0,
        check=lambda res, by: any("alias" in s for s in res["normalization"]),
    ),
    Case(
        "convertibles",
        {"body_type": "convertible"},
        lambda r: fv(r, "body_type") == "convertible",
        k=5,
        min_recall=1.0,
    ),
    Case(
        "export only excluded from bookable stock",
        {"make": "tova", "exclude_export_only": True},
        lambda r: False,
        k=5,
        check=lambda res, by: res["total_matches"] == 0,
    ),
    Case(
        "panoramic roof by keyword",
        {"keywords": "panoramic roof"},
        lambda r: "panoramic roof" in r["keywords_en"],
        k=5,
        min_precision=0.8,
    ),
    Case(
        "mileage under 50k",
        {"mileage_max_km": 50000},
        lambda r: fv(r, "mileage_km") is not None and fv(r, "mileage_km") <= 50000,
        k=5,
        check=lambda res, by: all(
            c["mileage_km"] is not None and c["mileage_km"] <= 50000 for c in res["results"]
        ),
    ),
    Case(
        "diesel",
        {"fuel_type": "diesel"},
        lambda r: fv(r, "fuel_type") == "diesel",
        k=5,
        min_recall=1.0,
    ),
    Case(
        "japanese spec",
        {"regional_spec": "japan"},
        lambda r: fv(r, "regional_spec") == "japan",
        k=5,
        min_recall=1.0,
    ),
    Case(
        "dubizzle inspected",
        {"is_dubizzle_managed": True},
        lambda r: bool(fv(r, "is_dubizzle_managed")),
        k=5,
        min_recall=1.0,
    ),
    Case(
        "2015 to 2017",
        {"year_min": 2015, "year_max": 2017},
        lambda r: 2015 <= r["year"] <= 2017,
        k=5,
        min_recall=1.0,
    ),
    Case(
        "listed between 50k and 100k",
        {"price_min_aed": 50000, "price_max_aed": 100000},
        lambda r: fv(r, "price_aed") is None or 50000 <= fv(r, "price_aed") <= 100000,
        k=5,
        check=lambda res, by: (
            all(c["price_aed"] is None or 50000 <= c["price_aed"] <= 100000 for c in res["results"])
            and res["results"][0]["price_aed"] is not None
        ),
    ),
    Case(
        "bentley continental incl. flying spur trim",
        {"make": "bentley", "model": "continental"},
        lambda r: r["make"] == "bentley" and r["model"] == "continental",
        k=5,
        min_recall=1.0,
    ),
    Case(
        "g wagon alias",
        {"model": "g wagon"},
        lambda r: r["make"] == "mercedes-benz" and r["model"].startswith("g-class"),
        k=5,
        min_recall=1.0,
    ),
    Case(
        "velar by model alias",
        {"model": "velar"},
        lambda r: r["model"] == "range rover velar",
        k=1,
        min_recall=1.0,
    ),
]


def score(case: Case, result: dict[str, Any], by_id: dict[str, Rec]) -> dict[str, Any]:
    """Precision at k over the shown page, recall over the full match list, rank of first hit."""
    expected = {i for i, r in by_id.items() if case.expected(r)}
    shown = [c["id"] for c in result["results"][: case.k]]
    hits = [i for i in shown if i in expected]
    precision = len(hits) / len(shown) if shown else (1.0 if not expected else 0.0)
    total = result["total_matches"]
    recall = None
    if expected:
        # The API pages, so recall is judged on whether the full match count covers the expected set.
        recall = min(1.0, total / len(expected)) if precision > 0 or total == 0 else 0.0
    first_hit = next((n for n, i in enumerate(shown, start=1) if i in expected), None)
    passed = precision >= case.min_precision
    if case.min_recall is not None and recall is not None:
        passed = passed and recall >= case.min_recall
    if case.expect_relaxed:
        passed = passed and bool(result["relaxed_filters"])
    if case.check is not None:
        passed = passed and bool(case.check(result, by_id))
    return {
        "name": case.name,
        "expected": len(expected),
        "total_matches": total,
        "shown": len(shown),
        "precision_at_k": round(precision, 2),
        "recall": None if recall is None else round(recall, 2),
        "first_hit_rank": first_hit,
        "relaxed": result["relaxed_filters"],
        "passed": passed,
        "note": case.note,
    }
