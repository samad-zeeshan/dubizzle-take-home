"""
Shared client pieces: brand tokens and CSS, backend calls, session state, the user or demo mode switch, and car cards.

Only user_id, session_id, the mode, and the stored envelopes live in session
state. History replays from envelopes and never re-calls the backend.
"""

from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import urlencode

import httpx
import streamlit as st
import streamlit.components.v1 as components

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120
# Sayara: Arabic for car. One place to rename the product.
APP_NAME = "Sayara"
APP_TAGLINE = "take-home build for dubizzle"

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
:root{--brand:#E3262E;--brand-dark:#B3161E;--brand-soft:rgba(227,38,46,.16);--ink:#F4F4F5;--slate:#C9C9CE;--muted:#9A9AA1;--line:#2A2A2E;--bg:#0F0F10;--card:#18181A;--card-2:#1E1E21;--ok-bg:rgba(34,197,94,.16);--ok-fg:#86EFAC;--radius:16px;--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 32px -18px rgba(0,0,0,.8);--ease:cubic-bezier(.2,.7,.2,1)}
html,body,[data-testid="stAppViewContainer"]{font-family:'DM Sans',system-ui,-apple-system,'Segoe UI',sans-serif;color:var(--ink);background:var(--bg)}
h1,h2,h3,.hero h1,.tile h3{font-family:'Space Grotesk','DM Sans',system-ui,sans-serif;letter-spacing:-.01em;color:var(--ink)}
[data-testid="stAppDeployButton"],#MainMenu,[data-testid="stMainMenu"]{display:none}
.block-container{padding-top:1.4rem;max-width:1180px}
[data-testid="stSidebar"]{background:#141416;border-right:1px solid var(--line)}
[data-testid="stSidebar"] hr{border-color:var(--line)}
.brandmark{display:flex;align-items:center;gap:.6rem;margin:.2rem 0 .8rem}
.brandmark .dot{width:14px;height:14px;border-radius:4px;background:var(--brand);flex:none;box-shadow:0 0 8px rgba(227,38,46,.35)}
.brandmark b{font-family:'Space Grotesk',sans-serif;font-size:1.05rem;color:var(--ink)}
.brandmark span{color:var(--muted);font-size:.8rem}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes sheen{0%{background-position:0% 50%}100%{background-position:100% 50%}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(134,239,172,.55)}70%{box-shadow:0 0 0 8px rgba(134,239,172,0)}}
.hero{position:relative;overflow:hidden;background:linear-gradient(120deg,#8F1017 0%,var(--brand-dark) 30%,var(--brand) 62%,#F0563F 100%);background-size:200% 200%;animation:rise .6s var(--ease) both,sheen 14s ease-in-out infinite alternate;color:#fff;border-radius:24px;padding:3rem 2.6rem 2.6rem;box-shadow:0 24px 50px -32px rgba(227,38,46,.3)}
.hero:after{content:"";position:absolute;inset:auto -20% -60% auto;width:60%;aspect-ratio:1;border-radius:50%;background:radial-gradient(closest-side,rgba(255,255,255,.18),transparent 70%);pointer-events:none}
.hero .eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;opacity:.85;font-weight:600}
.hero h1{font-size:3.2rem;line-height:1.05;margin:.5rem 0 .7rem;color:#fff}
.hero p{font-size:1.12rem;max-width:56ch;opacity:.94;line-height:1.55;margin:0}
.st-key-ask{margin:1.1rem 0 .6rem;animation:rise .6s .1s var(--ease) both}
.st-key-ask .react-aria-TextField,.st-key-ask [data-testid="stTextInputRootElement"]{height:64px}
.st-key-ask [data-testid="stTextInputRootElement"]{background:var(--card);border:1px solid var(--line);border-radius:18px;display:flex;align-items:center;transition:border-color .18s ease,box-shadow .18s ease}
.st-key-ask [data-testid="stTextInputRootElement"]:focus-within{border-color:var(--brand);box-shadow:0 0 0 4px var(--brand-soft)}
.st-key-ask [data-testid="stTextInputField"]{height:60px;font-size:1.08rem;padding-left:1.1rem;color:var(--ink);background:transparent}
.st-key-ask [data-testid="stTextInput"]{margin-bottom:0}
.st-key-ask div[data-testid="stFormSubmitButton"]>button{height:64px;width:100%;border-radius:18px;font-size:1.12rem;font-weight:700;background:var(--brand);border:1px solid var(--brand);color:#fff;box-shadow:0 10px 24px -16px rgba(227,38,46,.5);transition:transform .18s var(--ease),background .18s ease}
.st-key-ask div[data-testid="stFormSubmitButton"]>button:hover{background:#F03A41;transform:translateY(-1px)}
.st-key-chips{animation:rise .6s .18s var(--ease) both}
.st-key-chips div[data-testid="stButton"]>button{height:48px;width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--slate);font-weight:500;transition:border-color .18s ease,color .18s ease,transform .18s var(--ease)}
.st-key-chips div[data-testid="stButton"]>button:hover{border-color:var(--brand);color:var(--ink);transform:translateY(-1px)}
.section{font-family:'Space Grotesk',sans-serif;font-weight:600;font-size:1.35rem;margin:1.6rem 0 .8rem}
.bento{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;align-items:stretch}
.tile{background:linear-gradient(180deg,var(--card-2),var(--card));border:1px solid var(--line);border-radius:var(--radius);padding:1.3rem 1.2rem;min-height:230px;display:flex;flex-direction:column;box-shadow:var(--shadow);transition:transform .22s var(--ease),border-color .22s ease;animation:rise .6s var(--ease) both}
.bento .tile:nth-child(1){animation-delay:.2s}.bento .tile:nth-child(2){animation-delay:.28s}.bento .tile:nth-child(3){animation-delay:.36s}.bento .tile:nth-child(4){animation-delay:.44s}
.tile:hover{transform:translateY(-4px);border-color:rgba(227,38,46,.5)}
.tile .ic{width:40px;height:40px;border-radius:12px;background:var(--brand-soft);color:var(--brand);display:grid;place-items:center;margin-bottom:.9rem}
.tile .ic svg{width:20px;height:20px}
.tile h3{font-size:1.04rem;margin:0 0 .35rem}
.tile p{color:var(--slate);font-size:.93rem;line-height:1.55;margin:0}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;margin:1.4rem 0 .4rem}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:1rem 1.2rem;min-height:96px;display:flex;flex-direction:column;justify-content:center}
.stat b{display:block;font-size:1.55rem;font-variant-numeric:tabular-nums;font-family:'Space Grotesk',sans-serif;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat span{color:var(--muted);font-size:.84rem}
.stat .live{display:inline-block;width:9px;height:9px;border-radius:50%;background:#4ADE80;margin-right:.45rem;animation:pulse 2s ease-out infinite;vertical-align:middle}
.reviewer{background:linear-gradient(135deg,#1C1C1F,#141416);border:1px solid var(--line);border-radius:var(--radius);padding:1.4rem 1.5rem;height:100%}
.reviewer h3{color:var(--ink);margin:0 0 .4rem}
.reviewer p{color:var(--slate);margin:0;line-height:1.55}
.car{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);height:100%;margin-bottom:.75rem;transition:transform .22s var(--ease),border-color .22s ease}
.car:hover{transform:translateY(-3px);border-color:rgba(227,38,46,.5)}
.car .img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;background:#232326}
.car .imglink,.car .tlink{display:block;color:inherit;text-decoration:none}
.car .tlink:hover .t{color:var(--brand)}
.car .body{padding:.85rem 1rem .95rem}
.car .t{font-weight:600;font-size:.98rem;line-height:1.3;color:var(--ink)}
.car .price{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1.15rem;margin:.25rem 0 .1rem;font-variant-numeric:tabular-nums;color:var(--ink)}
.car .price small{font-family:'DM Sans',sans-serif;font-weight:500;color:var(--muted);font-size:.8rem;margin-left:.3rem}
.car .meta{color:var(--muted);font-size:.84rem}
.car .idx{display:inline-block;background:var(--brand);color:#fff;border-radius:999px;padding:.05rem .55rem;font-size:.72rem;margin-bottom:.4rem}
.badges{display:flex;gap:.35rem;flex-wrap:wrap;margin-top:.5rem}
.badge{font-size:.72rem;font-weight:600;padding:.15rem .55rem;border-radius:999px;background:var(--brand-soft);color:#FCA5A5}
.badge.ok{background:var(--ok-bg);color:var(--ok-fg)}
.badge.id{background:#26262A;color:var(--slate);font-weight:500}
.foot{color:var(--muted);font-size:.8rem;margin-top:1.6rem;border-top:1px solid var(--line);padding-top:.8rem}
div[data-testid="stButton"]>button,div[data-testid="stFormSubmitButton"]>button{border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:.35rem .95rem;font-weight:500;transition:background .15s ease,border-color .15s ease,transform .18s var(--ease)}
div[data-testid="stButton"]>button:hover{border-color:var(--brand);color:var(--ink)}
div[data-testid="stButton"]>button[kind="primary"]{background:var(--brand);border-color:var(--brand);color:#fff}
div[data-testid="stButton"]>button[kind="primary"]:hover{background:#F03A41;border-color:#F03A41}
div[data-testid="stButton"]>button:focus-visible,div[data-testid="stFormSubmitButton"]>button:focus-visible{outline:3px solid #fff;outline-offset:2px}
[data-testid="stChatMessage"]{border-radius:var(--radius);padding:.9rem 1rem;border:1px solid var(--line);background:var(--card);margin-bottom:.5rem;animation:rise .35s var(--ease) both}
[data-testid="stChatInput"]{border-radius:var(--radius)}
.meta-line{color:var(--muted);font-size:.8rem;margin-top:.3rem}
.card-actions div[data-testid="stButton"]>button{height:40px;font-size:.9rem}
[data-testid="stHorizontalBlock"]+[data-testid="stHorizontalBlock"]{margin-top:.25rem}
#cursor-glow{position:fixed;left:0;top:0;width:440px;height:440px;margin:-220px 0 0 -220px;border-radius:50%;pointer-events:none;z-index:0;background:radial-gradient(circle,rgba(227,38,46,.11) 0%,rgba(227,38,46,.04) 40%,transparent 70%);filter:blur(18px);opacity:0;transition:opacity .4s ease;will-change:transform}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}#cursor-glow{display:none}}
@media (max-width:1024px){.bento,.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.bento,.stats{grid-template-columns:1fr}.hero{padding:1.8rem 1.3rem}.hero h1{font-size:2.1rem}}
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


def bento(tiles: list[tuple[str, str, str]]) -> str:
    """Equal-height feature tiles as one CSS grid, so the boxes never drift with their text."""
    cards = "".join(
        f'<div class="tile"><div class="ic">{ICONS[icon]}</div><h3>{html.escape(title)}</h3><p>{html.escape(body)}</p></div>'
        for icon, title, body in tiles
    )
    return f'<div class="bento">{cards}</div>'


_GLOW_JS = """
<script>
(function () {
  var doc = window.parent && window.parent.document;
  if (!doc || doc.getElementById('cursor-glow')) return;
  var win = window.parent;
  if (win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (win.matchMedia && win.matchMedia('(pointer: coarse)').matches) return;
  var g = doc.createElement('div');
  g.id = 'cursor-glow';
  doc.body.appendChild(g);
  var x = 0, y = 0, tx = 0, ty = 0, raf = null;
  function tick() {
    x += (tx - x) * 0.16;
    y += (ty - y) * 0.16;
    g.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    raf = (Math.abs(tx - x) > 0.5 || Math.abs(ty - y) > 0.5) ? win.requestAnimationFrame(tick) : null;
  }
  doc.addEventListener('mousemove', function (e) {
    tx = e.clientX; ty = e.clientY;
    g.style.opacity = '1';
    if (!raf) raf = win.requestAnimationFrame(tick);
  }, { passive: true });
  doc.documentElement.addEventListener('mouseleave', function () { g.style.opacity = '0'; });
})();
</script>
"""


def cursor_glow() -> None:
    """A soft red glow that follows the pointer. Runs from a same-origin component frame because markdown strips scripts."""
    components.html(_GLOW_JS, height=0)


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


def ask_href(listing_id: str) -> str:
    """A link into the chat that asks about one car, keeping the user's session and mode in the URL."""
    params = {"ask": listing_id}
    if st.session_state.get("user_id"):
        params["user"] = st.session_state.user_id
    if st.session_state.get("session_id"):
        params["session"] = st.session_state.session_id
    if demo():
        params["mode"] = "demo"
    return "/chat?" + urlencode(params)


def money(n: Any) -> str:
    return f"AED {int(n):,}" if n else ""


def sidebar(h: dict[str, Any]) -> None:
    """The one sidebar for every page: brand, the mode switch, who you are, and in demo mode the backend."""
    with st.sidebar:
        st.markdown(
            f'<div class="brandmark"><div class="dot"></div><div><b>{html.escape(APP_NAME)}</b><br><span>{html.escape(APP_TAGLINE)}</span></div></div>',
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


def car_name(c: dict[str, Any]) -> str:
    return f"{c.get('year') or ''} {str(c.get('make') or '').title()} {str(c.get('model') or '').title()}".strip()


def car_card(c: dict[str, Any], show_index: bool = True, show_id: bool = True) -> str:
    title = html.escape(
        f"{c.get('year') or ''} {str(c.get('make') or '').title()} {str(c.get('model') or '').title()}".strip()
    )
    trim = c.get("trim")
    if trim and trim != "other":
        title += " " + html.escape(str(trim).title())
    photo = c.get("thumb_url") or c.get("photo_url") or ""
    href = ask_href(str(c.get("id")))
    # A real img tag: lazy, thumbnail sized, no referrer so the CDN treats it like any browser hit.
    img = (
        f'<a class="imglink" href="{href}" target="_self"><img class="img" src="{html.escape(photo)}" alt="{title}" loading="lazy" referrerpolicy="no-referrer"></a>'
        if photo
        else f'<a class="imglink" href="{href}" target="_self"><div class="img"></div></a>'
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
    if show_id:
        badges.append(f'<span class="badge id">{html.escape(str(c.get("id")))}</span>')
    idx = (
        f'<span class="idx">#{c["display_index"]}</span>'
        if show_index and c.get("display_index")
        else ""
    )
    return (
        f'<div class="car">{img}<div class="body">{idx}<a class="tlink" href="{href}" target="_self"><div class="t">{title}</div></a>'
        f'<div class="price">{price}{monthly}</div><div class="meta">{html.escape(meta)}</div>'
        f'<div class="badges">{"".join(badges)}</div></div></div>'
    )


def render_cards(
    cars: list[dict[str, Any]],
    per_row: int = 3,
    show_index: bool = True,
    key_prefix: str | None = None,
    switch_to_chat: bool = False,
) -> None:
    """Card grid. With a key_prefix each card gets ask and book buttons that feed the chat."""
    for i in range(0, len(cars), per_row):
        cols = st.columns(per_row)
        for col, c in zip(cols, cars[i : i + per_row], strict=False):
            col.markdown(car_card(c, show_index, show_id=demo()), unsafe_allow_html=True)
            if not key_prefix:
                continue
            b1, b2 = col.columns(2)
            picked = None
            if b1.button(
                "Ask about it", key=f"{key_prefix}_ask_{c['id']}", use_container_width=True
            ):
                # The id in brackets lets the resolver pin the car even when it is not on screen yet.
                picked = f"Tell me more about the {car_name(c)} ({c['id']})"
            if b2.button(
                "Book a viewing", key=f"{key_prefix}_book_{c['id']}", use_container_width=True
            ):
                picked = f"Book a viewing for the {car_name(c)} ({c['id']})"
            if picked:
                st.session_state.pending_prompt = picked
                if switch_to_chat:
                    st.switch_page(PAGES["chat"])
