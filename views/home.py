"""Landing page: the question box is the call to action, then what the assistant does, the reviewer's door, and the numbers."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from views import common

FEATURES = [
    (
        "search",
        "Search that reads the ads",
        "Price, mileage, colour, spec, and warranty are pulled out of free text, so 'white SUV under $20k' works.",
    ),
    (
        "calendar",
        "Book a viewing in two steps",
        "Monday to Saturday, 8 to 8, Dubai time. It proposes a slot, you confirm, the booking is written down.",
    ),
    (
        "memory",
        "It remembers you",
        "Come back tomorrow and it recalls what you searched, what you liked, and what you booked.",
    ),
    (
        "shield",
        "Every number has a source",
        "Figures in a reply are checked against the listing they came from. Contact details never pass through the model.",
    ),
]


def page(h: dict[str, Any]) -> None:
    st.markdown(
        f'<div class="hero"><div class="eyebrow">{html.escape(common.APP_NAME)}</div>'
        "<h1>Find your next car.</h1>"
        "<p>Ask in plain English or Arabic, compare listings, and book a viewing.</p></div>",
        unsafe_allow_html=True,
    )
    ask = st.container(key="ask")
    with ask.form("hero_ask", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        text = c1.text_input(
            "Ask about a car",
            placeholder="Try: a white SUV under AED 100k with warranty",
            label_visibility="collapsed",
        )
        go = c2.form_submit_button("Ask", use_container_width=True, type="primary")
    if go and text.strip():
        st.session_state.pending_prompt = text.strip()
        st.switch_page(common.pages()["chat"])
    chips = st.container(key="chips")
    cols = chips.columns(len(common.STARTERS))
    for col, s in zip(cols, common.STARTERS, strict=True):
        if col.button(s, key=f"starter_{s}", use_container_width=True, help=s):
            st.session_state.pending_prompt = s
            st.switch_page(common.pages()["chat"])

    st.markdown('<div class="section">What it does</div>', unsafe_allow_html=True)
    st.markdown(common.bento(FEATURES), unsafe_allow_html=True)

    st.write("")
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.markdown(
        '<div class="reviewer"><h3>Reviewing this build?</h3>'
        "<p>Demo mode shows the work behind every reply: the trace with timings, the exact prompt, the SQL and relaxation ladder, "
        "the grounding check on each figure, and what memory was read and written. It also unlocks the inventory explorer's provenance view and the admin page.</p></div>",
        unsafe_allow_html=True,
    )
    with c2:
        if st.button("Open demo mode", type="primary", use_container_width=True):
            common.set_mode("demo")
            st.switch_page(common.pages()["chat"])
        st.page_link(
            common.pages()["inventory"], label="Browse the inventory", use_container_width=True
        )

    llm = h["llm"]
    model = llm["model"].split("/")[-1]
    clock = '<span class="live"></span>live' if not h.get("demo_clock") else "frozen"
    st.markdown(
        '<div class="stats">'
        f'<div class="stat"><b>{h["inventory_count"]}</b><span>listings, both sheets merged</span></div>'
        f'<div class="stat"><b>{html.escape(h["retrieval_mode"])}</b><span>retrieval mode</span></div>'
        f'<div class="stat"><b title="{html.escape(llm["model"])}">{html.escape(model)}</b><span>model behind the replies</span></div>'
        f'<div class="stat"><b>{clock}</b><span>booking clock</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="foot">{html.escape(common.APP_NAME)} is a take-home assignment build for dubizzle, not an official dubizzle product. Listings are the assignment sample.</div>',
        unsafe_allow_html=True,
    )
