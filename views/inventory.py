"""Inventory page. User mode browses cards; demo mode is the explorer with provenance and the retrieval modes side by side."""

from __future__ import annotations

from typing import Any

import streamlit as st

from views import common

BODIES = [
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
]
FIELDS = (
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


def filters() -> dict[str, Any]:
    with st.sidebar:
        st.divider()
        st.markdown("**Filters**")
        make = st.text_input("Make", placeholder="Merc, Range Rover, Honda")
        model = st.text_input("Model")
        body = st.selectbox("Body type", BODIES)
        budget = st.text_input("Budget", placeholder="$20k, under 2000 a month, 150k")
        keywords = st.text_input("Keywords", placeholder="panoramic roof 7 seats")
        color = st.text_input("Colour")
        c1, c2 = st.columns(2)
        warranty = c1.checkbox("Warranty")
        managed = c2.checkbox("Inspected")
        sort = st.selectbox(
            "Sort", ["", "price_asc", "price_desc", "year_desc", "year_asc", "mileage_asc"]
        )
        limit = st.slider("Rows", 6, 200, 30)
    return dict(
        make=make,
        model=model,
        body_type=body,
        color=color,
        budget_text=budget,
        keywords=keywords,
        has_warranty=warranty or None,
        is_dubizzle_managed=managed or None,
        sort=sort or None,
        limit=limit,
    )


def coverage(rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    st.markdown(f"**Field coverage over {total} listings**")
    for f in FIELDS:
        known = sum(1 for r in rows if r.get(f) not in (None, False, ""))
        st.progress(known / total if total else 0.0, text=f"{f}: {known} of {total}")


def provenance(picked: str) -> None:
    d = common.get_json(f"/inventory/{picked}")
    if not d:
        return
    st.markdown(
        f"**{d['year']} {d['make']} {d['model']} {d['trim'] or ''}** · {d['source_sheet']} sheet row {d['source_row']} · language {d['language']} · text quality {d['description_quality']}"
    )
    st.write(d["english_summary"])
    st.dataframe(
        [
            {
                "field": k,
                "value": v.get("value"),
                "source": v.get("source"),
                "confidence": v.get("confidence"),
                "evidence": (v.get("evidence") or "")[:120],
            }
            for k, v in d["fields"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Text the model sees"):
        st.write(d["description_clean"] or "(empty)")
    with st.expander("Seller's original wording, contacts removed"):
        st.write(d["description_original"] or "(empty)")
    st.caption(f"keywords: {d['keywords_en']}")


def page(h: dict[str, Any]) -> None:
    st.markdown("### Inventory")
    params = filters()
    if common.demo() and st.checkbox("Compare retrieval modes on this query"):
        cols = st.columns(4)
        for col, mode in zip(cols, ("structured", "fts", "hybrid", "embeddings"), strict=True):
            with col:
                st.markdown(f"**{mode}**")
                res = common.get_json("/inventory/search", mode=mode, **params)
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
                            for c in res["results"][:8]
                        ]
                    )
    res = common.get_json("/inventory/search", **params)
    if not res:
        return
    rows = res["results"]
    st.caption(
        f"{res['total_matches']} matches"
        + (f" · relaxed {res['relaxed_filters']}" if res.get("relaxed_filters") else "")
    )
    if not common.demo():
        common.render_cards(rows, per_row=3, show_index=False)
        return
    if res.get("normalization"):
        st.write("normalisation:", res["normalization"])
    with st.expander("Executed query"):
        st.code(res["executed"].get("sql", ""), language="sql")
        st.json({k: v for k, v in res["executed"].items() if k != "sql"})
        st.json(res["stage_counts"])
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
                "colour": c["exterior_color"],
                "body": c["body_type"],
                "spec": c["regional_spec"],
                "fuel": c["fuel_type"],
                "warranty": c["has_warranty"],
                "inspected": c["is_dubizzle_managed"],
                "new": c["is_brand_new"],
                "lang": c["language"],
                "quality": c["description_quality"],
                "why": c["explain"]["rank_reason"],
            }
            for c in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    coverage(rows)
    st.markdown("**Listing detail with provenance**")
    picked = st.selectbox("Listing", [c["id"] for c in rows])
    if picked:
        provenance(picked)
