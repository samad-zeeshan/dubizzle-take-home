"""Landing page: the question box is the call to action, then what the assistant does, the reviewer's door, and the numbers."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from views import common

FEATURES = ("search", "calendar", "memory", "shield")


def page(h: dict[str, Any]) -> None:
    st.markdown(
        f'<div class="hero"><div class="eyebrow">{html.escape(common.APP_NAME)}</div>'
        f"<h1>{common.t('home.title')}</h1>"
        f"<p>{common.t('home.sub')}</p></div>",
        unsafe_allow_html=True,
    )
    ask = st.container(key="ask")
    with ask.form("hero_ask", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        text = c1.text_input(
            common.t("home.ask_label"),
            placeholder=common.t("home.ask_ph"),
            label_visibility="collapsed",
        )
        go = c2.form_submit_button(
            common.t("home.ask_btn"), use_container_width=True, type="primary"
        )
    if go and text.strip():
        st.session_state.pending_prompt = text.strip()
        st.switch_page(common.pages()["chat"])
    chips = st.container(key="chips")
    picks = common.starters()
    cols = chips.columns(len(picks))
    for col, s in zip(cols, picks, strict=True):
        if col.button(s, key=f"starter_{s}", use_container_width=True, help=s):
            st.session_state.pending_prompt = s
            st.switch_page(common.pages()["chat"])

    st.markdown(f'<div class="section">{common.t("home.what")}</div>', unsafe_allow_html=True)
    st.markdown(common.bento(FEATURES), unsafe_allow_html=True)

    st.write("")
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.markdown(
        f'<div class="reviewer"><h3>{common.t("home.review_t")}</h3>'
        "<p>Demo mode shows the work behind every reply: the trace with timings, the exact prompt, the SQL and relaxation ladder, "
        "the grounding check on each figure, and what memory was read and written. It also unlocks the inventory explorer's provenance view and the admin page.</p></div>",
        unsafe_allow_html=True,
    )
    with c2:
        if st.button(common.t("home.review_btn"), type="primary", use_container_width=True):
            common.set_mode("demo")
            st.switch_page(common.pages()["chat"])
        st.page_link(
            common.pages()["inventory"], label=common.t("home.browse"), use_container_width=True
        )

    llm = h["llm"]
    model = llm["model"].split("/")[-1]
    clock = '<span class="live"></span>live' if not h.get("demo_clock") else "frozen"
    st.markdown(
        '<div class="stats">'
        f'<div class="stat"><b>{h["inventory_count"]}</b><span>{common.t("stat.listings")}</span></div>'
        f'<div class="stat"><b>{html.escape(h["retrieval_mode"])}</b><span>{common.t("stat.retrieval")}</span></div>'
        f'<div class="stat"><b title="{html.escape(llm["model"])}">{html.escape(model)}</b><span>{common.t("stat.model")}</span></div>'
        f'<div class="stat"><b>{clock}</b><span>{common.t("stat.clock")}</span></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="foot">{html.escape(common.APP_NAME)} is a take-home assignment build for dubizzle, not an official dubizzle product. Listings are the assignment sample.</div>',
        unsafe_allow_html=True,
    )
