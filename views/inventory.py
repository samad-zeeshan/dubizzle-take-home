"""Inventory page. User mode browses cards; demo mode is the explorer with provenance and the retrieval modes side by side."""

from __future__ import annotations

from typing import Any

import streamlit as st

from views import common
from views.i18n import stated

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


SORTS = {
    "": "Relevance",
    "price_asc": "Price, low to high",
    "price_desc": "Price, high to low",
    "year_desc": "Newest first",
    "year_asc": "Oldest first",
    "mileage_asc": "Lowest mileage",
}


def body_label(b: str) -> str:
    return "Any" if not b else "SUV" if b == "suv" else b.replace("_", " ").title()


def filters() -> dict[str, Any]:
    """A filter bar above the cards, with the rarer controls behind one popover, so the sidebar stays navigation."""
    with st.container(key="filterbar"):
        c1, c2, c3, c4, c5, c6 = st.columns(
            [1.7, 1.4, 1.3, 1.9, 1.5, 1.1], vertical_alignment="bottom"
        )
        make = c1.text_input("Make", placeholder="Merc, Honda")
        model = c2.text_input("Model", placeholder="Velar, 3-Series")
        body = c3.selectbox("Body type", BODIES, format_func=body_label)
        budget = c4.text_input("Budget", placeholder="$20k, under 2000 a month")
        sort = c5.selectbox("Sort", list(SORTS), format_func=lambda k: SORTS[k])
        with c6.popover("More", icon=":material/tune:", use_container_width=True):
            keywords = st.text_input("Keywords", placeholder="panoramic roof 7 seats")
            color = st.text_input("Colour")
            k1, k2 = st.columns(2)
            warranty = k1.checkbox("Warranty")
            managed = k2.checkbox("Inspected")
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
    st.markdown(f"### {common.t('inv.title')}")
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
    n = res["total_matches"]
    st.caption(
        f"{n} match{'' if n == 1 else 'es'}"
        + (f" · relaxed {res['relaxed_filters']}" if res.get("relaxed_filters") else "")
    )
    if not common.demo():
        common.render_cards(
            rows, per_row=3, show_index=False, key_prefix="inv", switch_to_chat=True
        )
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
                "colour": stated(c["exterior_color"]),
                "body": stated(c["body_type"]),
                "spec": stated(c["regional_spec"]),
                "fuel": stated(c["fuel_type"]),
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
