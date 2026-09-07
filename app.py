"""
Streamlit client entry: page setup, brand CSS, and navigation. User mode is the product, demo mode shows the work.

Pages live in views/. Only app.py calls set_page_config, and it must be the first Streamlit call.
"""

from __future__ import annotations

import streamlit as st
from views import admin, chat, common, home, inventory

st.set_page_config(page_title=common.APP_NAME, page_icon=":material/directions_car:", layout="wide")
common.inject_css()
common.brand()
common.cursor_glow()
common.init_state()
h = common.health()
if h is None:
    st.error(
        f"Backend not reachable at {common.BACKEND}. Start it with:  uv run uvicorn main:app --reload"
    )
    st.stop()

pages = {
    "home": st.Page(lambda: home.page(h), title="Home", icon=":material/home:", default=True),
    "chat": st.Page(lambda: chat.page(h), title="Chat", icon=":material/chat:", url_path="chat"),
    "inventory": st.Page(
        lambda: inventory.page(h),
        title="Inventory",
        icon=":material/directions_car:",
        url_path="inventory",
    ),
}
if common.demo():
    pages["admin"] = st.Page(
        lambda: admin.page(h),
        title="Admin",
        icon=":material/admin_panel_settings:",
        url_path="admin",
    )
st.session_state["pages"] = pages
nav = st.navigation(list(pages.values()), position="hidden")
common.sidebar(h)
nav.run()
