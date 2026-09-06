"""
Admin page: leads, bookings, users, sessions, today's model calls, an availability grid, and transcript export.

Needs DEBUG_ENDPOINTS=true on the backend. Shows a notice otherwise.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="admin", layout="wide")
st.title("Admin")


def get(path: str, **params: Any) -> Any:
    r = httpx.get(f"{BACKEND}{path}", params=params, timeout=60)
    if r.status_code == 404 and path.startswith("/admin"):
        return None
    if r.status_code != 200:
        st.error(f"{path}: {r.status_code} {r.text[:200]}")
        return None
    return r.json()


health = get("/health")
if not health:
    st.stop()
if not health.get("debug_endpoints"):
    st.warning(
        "The backend is running with DEBUG_ENDPOINTS=false. Set it to true in .env and restart to see admin tables."
    )
    st.stop()

calls = get("/admin/llm_calls")
if calls:
    t = calls["totals"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("model calls today", f"{t['calls']} / {calls['budget']}")
    c2.metric("prompt tokens", f"{t['prompt_tokens']:,}")
    c3.metric("completion tokens", f"{t['completion_tokens']:,}")
    c4.metric("avg latency", f"{int(t['avg_latency_ms'])} ms")

tab_leads, tab_bookings, tab_users, tab_sessions, tab_slots, tab_calls = st.tabs(
    ["Leads", "Bookings", "Users", "Sessions", "Availability", "Model calls"]
)

with tab_leads:
    leads = get("/admin/leads") or []
    st.caption(
        f"{len(leads)} leads · status is a rule in code and the reason column says what is missing"
    )
    st.dataframe(leads, use_container_width=True, hide_index=True)
    st.link_button("Download leads.csv", f"{BACKEND}/leads.csv")

with tab_bookings:
    bookings = get("/admin/bookings") or []
    st.dataframe(bookings, use_container_width=True, hide_index=True)

with tab_users:
    users = get("/admin/users") or []
    st.dataframe(users, use_container_width=True, hide_index=True)
    uid = st.selectbox("Profile", [""] + [u["user_id"] for u in users])
    if uid:
        st.json(get(f"/users/{uid}/profile"))
        if st.button("Forget this user"):
            r = httpx.delete(f"{BACKEND}/users/{uid}", timeout=30)
            st.write(r.json())

with tab_sessions:
    sessions = get("/admin/sessions") or []
    st.dataframe(sessions, use_container_width=True, hide_index=True)
    sid = st.selectbox("Export session", [""] + [s["session_id"] for s in sessions])
    if sid:
        fmt = st.radio("Format", ["md", "json"], horizontal=True)
        r = httpx.get(f"{BACKEND}/sessions/{sid}/export", params={"format": fmt}, timeout=60)
        if fmt == "md":
            st.markdown(r.text)
        else:
            st.json(r.json())
        turns = get(f"/debug/turns/{sid}") or []
        st.caption("turns: " + ", ".join(f"{t['turn']} {t['intent']} {t['tools']}" for t in turns))

with tab_slots:
    lid = st.text_input("Listing id", value="C-003")
    week = st.text_input("Any date in the week (YYYY-MM-DD)", value="")
    grid = get(f"/inventory/{lid.upper()}/availability", week=week or None) if lid else None
    if grid:
        st.caption(grid["rule"] + f" · week of {grid['week_start']}")
        hours = [s["hour"] for s in grid["days"][0]["slots"]]
        st.table(
            [
                {
                    "day": f"{d['weekday'][:3]} {d['date'][5:]}",
                    **{
                        f"{h:02d}": next(s["state"] for s in d["slots"] if s["hour"] == h)
                        for h in hours
                    },
                }
                for d in grid["days"]
            ]
        )

with tab_calls:
    if calls:
        st.dataframe(calls["calls"], use_container_width=True, hide_index=True)
