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
common.direction()
h = common.health()
if h is None:
    st.error(common.t("err.backend", url=common.BACKEND))
    st.stop()

pages = {
    "home": st.Page(
        lambda: home.page(h), title=common.t("nav.home"), icon=":material/home:", default=True
    ),
    "chat": st.Page(
        lambda: chat.page(h), title=common.t("nav.chat"), icon=":material/chat:", url_path="chat"
    ),
    "inventory": st.Page(
        lambda: inventory.page(h),
        title=common.t("nav.inventory"),
        icon=":material/directions_car:",
        url_path="inventory",
    ),
}
# The admin page reads /admin/*, which the backend only mounts when DEBUG_ENDPOINTS is on.
if common.demo() and h.get("debug_endpoints"):
    pages["admin"] = st.Page(
        lambda: admin.page(h),
        title=common.t("nav.admin"),
        icon=":material/admin_panel_settings:",
        url_path="admin",
    )
st.session_state["pages"] = pages
nav = st.navigation(list(pages.values()), position="hidden")
common.sidebar(h)
nav.run()
