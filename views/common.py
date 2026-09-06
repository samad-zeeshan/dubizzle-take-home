"""
Shared client pieces: brand tokens and CSS, backend calls, session state, the user or demo mode switch, and car cards.

Only user_id, session_id, the mode, and the stored envelopes live in session
state. History replays from envelopes and never re-calls the backend.
"""

from __future__ import annotations

import html
import os
from typing import Any

import httpx
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120

# dubizzle's red as the single accent on a slate and off-white base, so the brand reads without shouting.
BRAND = {
    "red": "#D8232A",
    "red_dark": "#B3161E",
    "red_soft": "#FDECEC",
    "ink": "#0F172A",
    "slate": "#334155",
    "muted": "#64748B",
    "line": "#E2E8F0",
    "bg": "#F8FAFC",
    "card": "#FFFFFF",
    "ok_bg": "#DCFCE7",
    "ok_fg": "#166534",
}

ICONS = {
    "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>',
    "memory": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg>',
    "car": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 11 6.5 6.5h11L19 11"/><rect x="3" y="11" width="18" height="7" rx="2"/><circle cx="7.5" cy="18" r="1.5"/><circle cx="16.5" cy="18" r="1.5"/></svg>',
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{--brand:#D8232A;--brand-dark:#B3161E;--brand-soft:#FDECEC;--ink:#0F172A;--slate:#334155;--muted:#64748B;--line:#E2E8F0;--bg:#F8FAFC;--card:#FFFFFF;--ok-bg:#DCFCE7;--ok-fg:#166534;--radius:14px;--shadow:0 1px 2px rgba(15,23,42,.06),0 8px 24px -16px rgba(15,23,42,.25)}
html,body,[data-testid="stAppViewContainer"]{font-family:'DM Sans',system-ui,-apple-system,'Segoe UI',sans-serif;color:var(--ink)}
h1,h2,h3,.hero h1,.tile h3{font-family:'Space Grotesk','DM Sans',system-ui,sans-serif;letter-spacing:-.01em}
[data-testid="stAppDeployButton"],#MainMenu{display:none}
.block-container{padding-top:1.6rem;max-width:1180px}
[data-testid="stSidebar"]{background:var(--bg);border-right:1px solid var(--line)}
.brandmark{display:flex;align-items:center;gap:.6rem;margin:.2rem 0 .8rem}
.brandmark .dot{width:14px;height:14px;border-radius:4px;background:var(--brand);flex:none}
.brandmark b{font-family:'Space Grotesk',sans-serif;font-size:1.05rem}
.brandmark span{color:var(--muted);font-size:.8rem}
.hero{background:linear-gradient(135deg,var(--brand-dark) 0%,var(--brand) 55%,#F04B44 100%);color:#fff;border-radius:22px;padding:2.6rem 2.4rem 2.2rem;box-shadow:var(--shadow)}
.hero .eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:.72rem;opacity:.85;font-weight:600}
.hero h1{font-size:2.6rem;line-height:1.1;margin:.5rem 0 .7rem;color:#fff}
.hero p{font-size:1.1rem;max-width:58ch;opacity:.94;line-height:1.55;margin:0}
.stats{display:flex;gap:1rem;flex-wrap:wrap;margin:1.2rem 0 .4rem}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:.9rem 1.2rem;min-width:150px;flex:1}
.stat b{display:block;font-size:1.5rem;font-variant-numeric:tabular-nums;font-family:'Space Grotesk',sans-serif}
.stat span{color:var(--muted);font-size:.85rem}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:1.2rem 1.2rem 1.1rem;height:100%;box-shadow:var(--shadow);transition:transform .2s ease,box-shadow .2s ease}
.tile:hover{transform:translateY(-2px)}
.tile .ic{width:38px;height:38px;border-radius:10px;background:var(--brand-soft);color:var(--brand);display:grid;place-items:center;margin-bottom:.7rem}
.tile .ic svg{width:20px;height:20px}
.tile h3{font-size:1.02rem;margin:0 0 .3rem}
.tile p{color:var(--slate);font-size:.93rem;line-height:1.5;margin:0}
.car{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);height:100%}
.car .img{aspect-ratio:16/10;background:#EEF2F6 center/cover no-repeat;display:block}
.car .body{padding:.8rem .95rem .9rem}
.car .t{font-weight:600;font-size:.98rem;line-height:1.3}
.car .price{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1.15rem;margin:.25rem 0 .1rem;font-variant-numeric:tabular-nums}
.car .price small{font-family:'DM Sans',sans-serif;font-weight:500;color:var(--muted);font-size:.8rem;margin-left:.3rem}
.car .meta{color:var(--muted);font-size:.84rem}
.car .idx{position:relative;display:inline-block;background:var(--ink);color:#fff;border-radius:999px;padding:.05rem .55rem;font-size:.72rem;margin-bottom:.4rem}
.badges{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.5rem}
.badge{font-size:.72rem;font-weight:600;padding:.15rem .55rem;border-radius:999px;background:var(--brand-soft);color:var(--brand-dark)}
.badge.ok{background:var(--ok-bg);color:var(--ok-fg)}
.badge.id{background:#EEF2F6;color:var(--slate);font-weight:500}
.reviewer{background:var(--ink);color:#fff;border-radius:var(--radius);padding:1.3rem 1.4rem}
.reviewer h3{color:#fff;margin:0 0 .3rem}
.reviewer p{color:#CBD5E1;margin:0;line-height:1.5}
.foot{color:var(--muted);font-size:.8rem;margin-top:2rem;border-top:1px solid var(--line);padding-top:.8rem}
div[data-testid="stButton"]>button,div[data-testid="stFormSubmitButton"]>button{border-radius:999px;border:1px solid var(--line);padding:.35rem .95rem;font-weight:500;transition:background .15s ease,border-color .15s ease}
div[data-testid="stButton"]>button[kind="primary"]{background:var(--brand);border-color:var(--brand);color:#fff}
div[data-testid="stButton"]>button[kind="primary"]:hover{background:var(--brand-dark);border-color:var(--brand-dark)}
div[data-testid="stButton"]>button:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
[data-testid="stChatMessage"]{border-radius:var(--radius);padding:.9rem 1rem;border:1px solid var(--line);background:var(--card);margin-bottom:.5rem}
[data-testid="stChatInput"]{border-radius:var(--radius)}
.meta-line{color:var(--muted);font-size:.8rem;margin-top:.3rem}
@media (prefers-reduced-motion:reduce){.tile,.tile:hover,div[data-testid="stButton"]>button{transition:none;transform:none}}
@media (max-width:768px){.hero{padding:1.8rem 1.3rem}.hero h1{font-size:2rem}}
</style>
"""

STARTERS = [
    "Show me SUVs with warranty under AED 150k",
    "Any Hondas?",
    "Compare the two cheapest Range Rovers",
    "Book the Velar for Monday at 10am",
]
# Filled by app.py once the navigation exists, so pages can switch to each other.
PAGES: dict[str, Any] = {}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def api(method: str, path: str, **kwargs: Any) -> httpx.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    return httpx.request(method, f"{BACKEND}{path}", **kwargs)


def get_json(path: str, **params: Any) -> Any:
    try:
        r = api(
            "GET",
            path,
            params={k: v for k, v in params.items() if v not in (None, "", False)},
            timeout=60,
        )
    except httpx.HTTPError as e:
        st.error(f"Backend not reachable: {e}")
        return None
    if r.status_code == 404 and path.startswith("/admin"):
        return None
    if r.status_code != 200:
        st.error(f"{path}: {r.status_code} {r.text[:200]}")
        return None
    return r.json()


def health() -> dict[str, Any] | None:
    try:
        r = api("GET", "/health", timeout=5)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def init_state() -> None:
    st.session_state.setdefault("user_id", None)
    st.session_state.setdefault("user_name", None)
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending_prompt", None)
    st.session_state.setdefault("mode", st.query_params.get("mode", "user"))
    if not st.session_state.session_id and "session" in st.query_params:
        st.session_state.session_id = st.query_params["session"]
    if not st.session_state.user_id and "user" in st.query_params:
        st.session_state.user_id = st.query_params["user"]
    if st.session_state.user_id and not st.session_state.user_name:
        prof = get_json(f"/users/{st.session_state.user_id}/profile")
        st.session_state.user_name = (prof or {}).get("name")
    if st.session_state.session_id and not st.session_state.messages:
        restore_history(st.session_state.session_id)


def restore_history(session_id: str) -> None:
    """After a refresh the backend still has the transcript; the panels only exist for new turns."""
    try:
        r = api("GET", f"/sessions/{session_id}", timeout=10)
    except httpx.HTTPError:
        return
    if r.status_code != 200:
        return
    for m in r.json().get("messages") or []:
        text = m.get("content")
        if (
            m.get("role") in ("user", "assistant")
            and isinstance(text, str)
            and text.strip()
            and not text.startswith("{")
        ):
            st.session_state.messages.append({"role": m["role"], "content": text, "envelope": None})


def demo() -> bool:
    return st.session_state.get("mode") == "demo"


def set_mode(mode: str) -> None:
    st.session_state.mode = mode
    if mode == "demo":
        st.query_params["mode"] = "demo"
    else:
        st.query_params.pop("mode", None)


def new_session() -> None:
    st.session_state.session_id = None
    st.session_state.messages = []
    st.query_params.pop("session", None)


def identify(name: str) -> None:
    r = api("POST", "/users/identify", json={"name": name})
    if r.status_code != 200:
        return
    d = r.json()
    st.session_state.user_id, st.session_state.user_name = d["user_id"], d["name"]
    st.query_params["user"] = d["user_id"]
    new_session()
    note = ("Welcome back, " if d["returning"] else "Nice to meet you, ") + d["name"] + "."
    summary = d.get("profile_summary") or ""
    if d["returning"] and "\n" in summary:
        note += " " + summary.split("\n")[1]
    st.session_state.identify_note = note


def money(n: Any) -> str:
    return f"AED {int(n):,}" if n else ""


def sidebar(h: dict[str, Any]) -> None:
    """The one sidebar for every page: brand, the mode switch, who you are, and in demo mode the backend."""
    with st.sidebar:
        st.markdown(
            '<div class="brandmark"><div class="dot"></div><div><b>Car Assistant</b><br><span>take-home build for dubizzle</span></div></div>',
            unsafe_allow_html=True,
        )
        for key, page in PAGES.items():
            st.page_link(page, label=key.title(), icon=page.icon or None, use_container_width=True)
        st.divider()
        on = st.toggle(
            "Demo mode",
            value=demo(),
            help="Shows the trace, prompt, retrieval, grounding, and memory under every reply, plus the admin page.",
        )
        if on != demo():
            set_mode("demo" if on else "user")
            st.rerun()
        st.divider()
        name = st.text_input(
            "Your name", value=st.session_state.user_name or "", placeholder="Sara"
        )
        c1, c2 = st.columns(2)
        if c1.button("Continue", use_container_width=True) and name.strip():
            identify(name.strip())
            st.rerun()
        c2.button("New chat", use_container_width=True, on_click=new_session)
        if st.session_state.get("identify_note"):
            st.caption(st.session_state.identify_note)
        if st.session_state.user_id:
            with st.expander("Your details and bookings"):
                st.caption("Contact details go straight to the backend, never through the model.")
                with st.form("contact"):
                    phone = st.text_input("Phone (UAE mobile)")
                    email = st.text_input("Email")
                    if st.form_submit_button("Save") and (phone or email):
                        r = api(
                            "POST",
                            "/leads/contact",
                            json={
                                "user_id": st.session_state.user_id,
                                "phone": phone or None,
                                "email": email or None,
                            },
                        )
                        st.write(
                            r.json().get("problems")
                            or f"Saved. Lead status: {r.json().get('status')}"
                        )
                r = api("GET", "/bookings", params={"user_id": st.session_state.user_id})
                if r.status_code == 200 and r.json():
                    st.table(
                        [
                            {
                                "ref": b["ref"],
                                "car": b["listing_id"],
                                "slot": b["slot_start"][:16],
                                "status": b["status"],
                            }
                            for b in r.json()
                        ]
                    )
        if demo():
            st.divider()
            llm = h["llm"]
            st.markdown("**Backend**")
            st.caption(f"model `{llm['model']}` via {llm['provider']}")
            st.caption(
                f"retrieval `{h['retrieval_mode']}` · cassette `{llm['cassette_mode']}` · verify `{llm['verify_mode']}`"
            )
            st.caption(f"model calls today {llm['requests_today']} / {llm['budget']}")
            if h["ablations_active"]:
                st.warning("ablations active: " + ", ".join(h["ablations_active"]))
            if llm.get("last_error"):
                st.error(llm["last_error"])
            if h.get("demo_clock"):
                st.caption(f"clock frozen at {h['demo_clock']}")
            st.caption(
                f"user `{st.session_state.user_id or '-'}` · session `{st.session_state.session_id or '-'}`"
            )


def car_card(c: dict[str, Any], show_index: bool = True) -> str:
    title = html.escape(
        f"{c.get('year') or ''} {str(c.get('make') or '').title()} {str(c.get('model') or '').title()}".strip()
    )
    trim = c.get("trim")
    if trim and trim != "other":
        title += " " + html.escape(str(trim).title())
    photo = c.get("thumb") or c.get("photo_url") or ""
    img = (
        f'<div class="img" role="img" aria-label="{title}" style="background-image:url({html.escape(photo)})"></div>'
        if photo
        else '<div class="img"></div>'
    )
    price = money(c.get("price_aed")) or "Price not listed"
    monthly = f"<small>or {money(c.get('monthly_aed'))}/mo</small>" if c.get("monthly_aed") else ""
    body = str(c.get("body_type") or "")
    meta = " · ".join(
        p
        for p in (
            f"{int(c['mileage_km']):,} km" if c.get("mileage_km") is not None else "",
            body.upper() if body == "suv" else body.title(),
            str(c.get("regional_spec") or "").upper(),
            str(c.get("exterior_color") or "").title(),
        )
        if p
    )
    badges = []
    if c.get("has_warranty"):
        badges.append('<span class="badge">Warranty</span>')
    if c.get("is_dubizzle_managed"):
        badges.append('<span class="badge ok">dubizzle inspected</span>')
    if c.get("is_brand_new"):
        badges.append('<span class="badge ok">Brand new</span>')
    badges.append(f'<span class="badge id">{html.escape(str(c.get("id")))}</span>')
    idx = (
        f'<span class="idx">#{c["display_index"]}</span>'
        if show_index and c.get("display_index")
        else ""
    )
    return (
        f'<div class="car">{img}<div class="body">{idx}<div class="t">{title}</div>'
        f'<div class="price">{price}{monthly}</div><div class="meta">{html.escape(meta)}</div>'
        f'<div class="badges">{"".join(badges)}</div></div></div>'
    )


def render_cards(cars: list[dict[str, Any]], per_row: int = 3, show_index: bool = True) -> None:
    for i in range(0, len(cars), per_row):
        cols = st.columns(per_row)
        for col, c in zip(cols, cars[i : i + per_row], strict=False):
            col.markdown(car_card(c, show_index), unsafe_allow_html=True)
