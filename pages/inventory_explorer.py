"""
Inventory explorer: every listing, every extracted field with its source and evidence, and the retrieval modes side by side.

Backed only by the inventory endpoints. Nothing here touches the database.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="inventory explorer", layout="wide")
st.title("Inventory explorer")


def get(path: str, **params: Any) -> Any:
    r = httpx.get(
        f"{BACKEND}{path}",
        params={k: v for k, v in params.items() if v not in (None, "", False)},
        timeout=60,
    )
    if r.status_code != 200:
        st.error(f"{path}: {r.status_code} {r.text[:200]}")
        return None
    return r.json()


def coverage(rows: list[dict[str, Any]]) -> None:
    fields = (
        "price_aed",
        "monthly_aed",
        "mileage_km",
        "exterior_color",
        "body_type",
        "regional_spec",
        "fuel_type",
        "has_warranty",
        "is_dubizzle_managed",
        "is_brand_new",
    )
    total = len(rows)
    st.subheader(f"Field coverage over {total} listings")
    for f in fields:
        known = sum(1 for r in rows if r.get(f) not in (None, False, ""))
        st.progress(known / total if total else 0.0, text=f"{f}: {known} of {total}")


with st.sidebar:
    st.header("Filters")
    make = st.text_input("Make (aliases ok: Merc, Range Rover)")
    model = st.text_input("Model")
    body = st.selectbox(
        "Body type",
        [
            "",
            "suv",
            "sedan",
            "coupe",
            "hatchback",
            "pickup",
            "van",
            "convertible",
            "wagon",
            "truck_chassis",
        ],
    )
    color = st.text_input("Colour")
    spec = st.selectbox("Spec", ["", "gcc", "us", "japan", "euro", "korean", "canadian"])
    fuel = st.selectbox("Fuel", ["", "petrol", "diesel", "electric", "hybrid"])
    budget = st.text_input("Budget phrase", placeholder="$20k, under 2000 a month, 150k")
    keywords = st.text_input("Keywords", placeholder="panoramic roof 7 seats")
    warranty = st.checkbox("Warranty mentioned")
    new = st.checkbox("Brand new")
    managed = st.checkbox("dubizzle inspected")
    sort = st.selectbox(
        "Sort", ["", "price_asc", "price_desc", "year_desc", "year_asc", "mileage_asc"]
    )
    compare_modes = st.checkbox("Compare retrieval modes on this query")
    limit = st.slider("Rows", 5, 200, 50)

params = dict(
    make=make,
    model=model,
    body_type=body,
    color=color,
    regional_spec=spec,
    fuel_type=fuel,
    budget_text=budget,
    keywords=keywords,
    has_warranty=warranty or None,
    is_brand_new=new or None,
    is_dubizzle_managed=managed or None,
    sort=sort or None,
    limit=limit,
)

if compare_modes:
    st.subheader("Same query, four ways")
    cols = st.columns(4)
    for col, mode in zip(cols, ("structured", "fts", "hybrid", "embeddings"), strict=True):
        with col:
            st.markdown(f"**{mode}**")
            res = get("/inventory/search", mode=mode, **params)
            if res:
                st.caption(
                    f"{res['total_matches']} matches, relaxed {res['relaxed_filters'] or 'none'}"
                )
                st.table(
                    [
                        {
                            "id": c["id"],
                            "car": f"{c['year']} {c['make']} {c['model']}",
                            "why": c["explain"]["rank_reason"],
                        }
                        for c in res["results"][:10]
                    ]
                )

res = get("/inventory/search", **params)
if res:
    st.caption(
        f"{res['total_matches']} matches · mode {res['mode']} · relaxed {res['relaxed_filters'] or 'none'} · buckets {res['price_buckets']}"
    )
    if res["normalization"]:
        st.write("normalization:", res["normalization"])
    with st.expander("Executed query"):
        st.code(res["executed"].get("sql", ""), language="sql")
        st.json({k: v for k, v in res["executed"].items() if k != "sql"})
        st.json(res["stage_counts"])
    rows = res["results"]
    st.dataframe(
        [
            {
                "id": c["id"],
                "year": c["year"],
                "make": c["make"],
                "model": c["model"],
                "trim": c["trim"],
                "price_aed": c["price_aed"],
                "monthly_aed": c["monthly_aed"],
                "mileage_km": c["mileage_km"],
                "exterior_color": c["exterior_color"],
                "body_type": c["body_type"],
                "regional_spec": c["regional_spec"],
                "fuel_type": c["fuel_type"],
                "has_warranty": c["has_warranty"],
                "is_dubizzle_managed": c["is_dubizzle_managed"],
                "is_brand_new": c["is_brand_new"],
                "language": c["language"],
                "quality": c["description_quality"],
                "rank_reason": c["explain"]["rank_reason"],
            }
            for c in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    coverage(rows)
    st.subheader("Listing detail with provenance")
    picked = st.selectbox("Listing", [c["id"] for c in rows])
    if picked:
        d = get(f"/inventory/{picked}")
        if d:
            st.markdown(
                f"**{d['year']} {d['make']} {d['model']} {d['trim'] or ''}** · {d['source_sheet']} sheet row {d['source_row']} · language {d['language']}"
            )
            st.write(d["english_summary"])
            st.table(
                [
                    {
                        "field": k,
                        "value": v.get("value"),
                        "source": v.get("source"),
                        "confidence": v.get("confidence"),
                        "evidence": (v.get("evidence") or "")[:120],
                    }
                    for k, v in d["fields"].items()
                ]
            )
            with st.expander("Text the model sees (description_clean)"):
                st.write(d["description_clean"] or "(empty)")
            with st.expander("Seller's original wording, contacts removed"):
                st.write(d["description_original"] or "(empty)")
            st.caption(f"keywords: {d['keywords_en']}")
