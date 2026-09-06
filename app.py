"""
Streamlit chat client. HTTP only, functional and unstyled: every panel exists to make the backend's work visible.

Only user_id, session_id, and the list of stored envelopes live in session
state. History replays from envelopes and never re-calls the backend.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120

st.set_page_config(page_title="dubizzle cars assistant", layout="wide")


def api(method: str, path: str, **kwargs: Any) -> httpx.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    return httpx.request(method, f"{BACKEND}{path}", **kwargs)


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
    st.session_state.setdefault("messages", [])  # list of {"role", "content", "envelope"?}
    st.session_state.setdefault("pending_prompt", None)
    if not st.session_state.session_id and "session" in st.query_params:
        st.session_state.session_id = st.query_params["session"]
    if not st.session_state.user_id and "user" in st.query_params:
        st.session_state.user_id = st.query_params["user"]


def new_session() -> None:
    st.session_state.session_id = None
    st.session_state.messages = []
    st.query_params.pop("session", None)


def identify(name: str) -> None:
    r = api("POST", "/users/identify", json={"name": name})
    if r.status_code == 200:
        d = r.json()
        st.session_state.user_id, st.session_state.user_name = d["user_id"], d["name"]
        st.query_params["user"] = d["user_id"]
        new_session()
        st.session_state.identify_note = (
            ("Welcome back, " if d["returning"] else "Nice to meet you, ")
            + d["name"]
            + (
                ". " + d["profile_summary"].split("\n")[1]
                if d["returning"] and d.get("profile_summary") and "\n" in d["profile_summary"]
                else ""
            )
        )


def send(text: str) -> None:
    body: dict[str, Any] = {"message": text}
    if st.session_state.user_id:
        body["user_id"] = st.session_state.user_id
    if st.session_state.session_id:
        body["session_id"] = st.session_state.session_id
    elif st.session_state.user_name:
        body["name"] = st.session_state.user_name
    st.session_state.messages.append({"role": "user", "content": text})
    status = st.status("working", expanded=True)
    draft = st.empty()  # streamed sentences show here until the final reply replaces them
    draft_text = ""
    envelope: dict[str, Any] | None = None
    error: str | None = None
    try:
        with httpx.stream(
            "POST",
            f"{BACKEND}/chat/stream",
            json=body,
            headers={"Idempotency-Key": str(uuid.uuid4())},
            timeout=TIMEOUT,
        ) as r:
            if r.status_code != 200:
                error = f"{r.status_code}: {r.read().decode('utf-8', 'replace')[:300]}"
            else:
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: ") and event:
                        data = json.loads(line[6:])
                        if event == "stage":
                            status.write(data["label"])
                        elif event == "token":
                            draft_text += data["text"]
                            draft.markdown(draft_text + " ▌")
                        elif event == "envelope":
                            envelope = data
                        elif event == "error":
                            error = f"{data.get('status')}: {data.get('detail')}"
    except httpx.HTTPError as e:
        error = f"backend not reachable: {e}"
    draft.empty()
    status.update(
        label="done" if envelope else "failed",
        state="complete" if envelope else "error",
        expanded=False,
    )
    if envelope:
        st.session_state.user_id = envelope["user_id"]
        st.session_state.session_id = envelope["session_id"]
        st.query_params["session"] = envelope["session_id"]
        st.query_params["user"] = envelope["user_id"]
        if envelope.get("identified_user"):
            st.session_state.user_id = envelope["identified_user"]["user_id"]
            st.session_state.user_name = envelope["identified_user"]["name"]
        st.session_state.messages.append(
            {"role": "assistant", "content": envelope["reply"], "envelope": envelope}
        )
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Sorry, that did not go through. {error}",
                "envelope": None,
            }
        )


def render_cars(cars: list[dict[str, Any]]) -> None:
    if not cars:
        return
    rows = [
        {
            "#": c.get("display_index"),
            "id": c["id"],
            "year": c["year"],
            "make": c["make"],
            "model": c["model"],
            "price": f"AED {c['price_aed']:,}" if c.get("price_aed") else "not listed",
            "monthly": f"AED {c['monthly_aed']:,}" if c.get("monthly_aed") else "",
            "km": f"{c['mileage_km']:,}" if c.get("mileage_km") is not None else "not stated",
            "colour": c.get("exterior_color") or "",
            "body": c.get("body_type") or "",
            "spec": c.get("regional_spec") or "",
            "warranty": "yes" if c.get("has_warranty") else "",
            "inspected": "yes" if c.get("is_dubizzle_managed") else "",
        }
        for c in cars
    ]
    st.table(rows)


def mark_grounding(reply: str, grounding: dict[str, Any] | None) -> str:
    """Ungrounded figures get a visible marker so a reviewer can see the check, not just trust it."""
    if not grounding or not grounding.get("spans"):
        return reply
    out, pos = [], 0
    for span in grounding["spans"]:
        out.append(reply[pos : span["start"]])
        text = reply[span["start"] : span["end"]]
        out.append(text if span["grounded"] else f"~~{text}~~ (unsourced)")
        pos = span["end"]
    out.append(reply[pos:])
    return "".join(out)


def render_envelope(env: dict[str, Any]) -> None:
    st.markdown(mark_grounding(env["reply"], env.get("grounding")))
    render_cars(env.get("cars") or [])
    meta = f"intent `{env['intent']}`"
    if env.get("grounding"):
        g = env["grounding"]
        meta += f" · grounded {g['grounded']}/{g['checked']}"
    if env.get("model"):
        meta += f" · {env['model']} · {env.get('latency_ms')} ms"
    if env.get("degraded"):
        meta += " · **degraded: offline stand-in, daily budget reached**"
    st.caption(meta)
    with st.expander("Trace"):
        for s in env["trace"]["stages"]:
            extra = {k: v for k, v in s.items() if k not in ("stage", "at_ms", "ms", "blocks")}
            st.write(f"**{s['stage']}** {s.get('ms', '')} ms", extra if extra else "")
    with st.expander("What the model saw"):
        blocks = next(
            (s.get("blocks") for s in env["trace"]["stages"] if s["stage"] == "prompt"), None
        )
        if blocks:
            for b in blocks:
                st.text(f"[{b['name']}] ~{b['tokens']} tokens\n{b['text']}")
        else:
            st.write("no model call this turn")
    if env.get("query_explain"):
        with st.expander("Query"):
            st.json(env["query_explain"])
            for c in env.get("cars") or []:
                if c.get("explain"):
                    st.write(
                        f"{c['id']}: {c['explain']['rank_reason']}; filters {c['explain']['matched_filters']}; stage {c['explain']['admitted_at_stage']}"
                    )
    with st.expander("Memory"):
        st.write("read:", env["memory"]["read"] or "nothing on file")
        st.write("writes:", env["memory"]["writes"] or "none")
    if env.get("resolver"):
        with st.expander("Resolver"):
            st.json(env["resolver"])
    if env.get("verification"):
        with st.expander("Verification"):
            st.json(env["verification"])


def sidebar(h: dict[str, Any]) -> None:
    with st.sidebar:
        st.header("You")
        name = st.text_input(
            "Your name", value=st.session_state.user_name or "", placeholder="Sara"
        )
        if st.button("Identify") and name.strip():
            identify(name.strip())
        if st.session_state.get("identify_note"):
            st.info(st.session_state.identify_note)
        st.write(f"user_id: `{st.session_state.user_id or '-'}`")
        st.write(f"session_id: `{st.session_state.session_id or '-'}`")
        st.button("New session", on_click=new_session)
        if st.session_state.user_id:
            with st.form("contact"):
                st.caption("Contact details go straight to the backend, never through the model.")
                phone = st.text_input("Phone (UAE mobile)")
                email = st.text_input("Email")
                if st.form_submit_button("Save contact") and (phone or email):
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
                        r.json().get("problems") or f"saved, lead status {r.json().get('status')}"
                    )
            r = api("GET", "/bookings", params={"user_id": st.session_state.user_id})
            if r.status_code == 200 and r.json():
                st.subheader("My bookings")
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
        st.header("Backend")
        llm = h["llm"]
        st.write(f"model: `{llm['model']}` ({llm['provider']})")
        st.write(f"calls today: {llm['requests_today']} / {llm['budget']}")
        st.write(
            f"retrieval: `{h['retrieval_mode']}` · cassette: `{llm['cassette_mode']}` · verify: `{llm['verify_mode']}`"
        )
        if h["ablations_active"]:
            st.warning("ablations active: " + ", ".join(h["ablations_active"]))
        if llm.get("last_error"):
            st.error(llm["last_error"])
        if h.get("demo_clock"):
            st.caption(f"clock frozen at {h['demo_clock']}")


def main() -> None:
    init_state()
    h = health()
    if h is None:
        st.error(
            f"Backend not reachable at {BACKEND}. Start it with:  uv run uvicorn main:app --reload"
        )
        st.stop()
    sidebar(h)
    st.title("dubizzle cars assistant")
    st.caption(
        "Ask about cars in the inventory, compare them, or book a viewing. Everything the assistant does is shown under each reply."
    )
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            if m["role"] == "assistant" and m.get("envelope"):
                render_envelope(m["envelope"])
            else:
                st.markdown(m["content"])
    last = st.session_state.messages[-1] if st.session_state.messages else None
    if last and last.get("envelope") and last["envelope"].get("suggested_actions"):
        cols = st.columns(len(last["envelope"]["suggested_actions"]))
        for col, action in zip(cols, last["envelope"]["suggested_actions"], strict=True):
            if col.button(action, key=f"chip_{len(st.session_state.messages)}_{action}"):
                st.session_state.pending_prompt = action
    prompt = st.chat_input("Ask about a car, or say hi")
    text = prompt or st.session_state.pending_prompt
    if text:
        st.session_state.pending_prompt = None
        send(text)
        st.rerun()


main()
