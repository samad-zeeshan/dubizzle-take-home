"""Chat page. User mode is the product; demo mode adds the work behind every reply."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import streamlit as st

from views import common

HIDDEN_KEYS = ("stage", "at_ms", "ms", "blocks")


def send(text: str) -> None:
    body: dict[str, Any] = {"message": text}
    if st.session_state.user_id:
        body["user_id"] = st.session_state.user_id
    if st.session_state.session_id:
        body["session_id"] = st.session_state.session_id
    elif st.session_state.user_name:
        body["name"] = st.session_state.user_name
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user"):
        st.markdown(text)
    envelope: dict[str, Any] | None = None
    error: str | None = None
    with st.chat_message("assistant"):
        status = st.status("Thinking", expanded=common.demo())
        draft = st.empty()
        draft_text = ""
        try:
            with httpx.stream(
                "POST",
                f"{common.BACKEND}/chat/stream",
                json=body,
                headers={"Idempotency-Key": str(uuid.uuid4())},
                timeout=common.TIMEOUT,
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
                                status.update(label=data["label"].capitalize())
                                if common.demo():
                                    status.write(f"{data['label']} · {data.get('at_ms')} ms")
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
            label="Done" if envelope else "Failed",
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


def mark_grounding(reply: str, grounding: dict[str, Any] | None) -> str:
    """Unsourced figures get a visible marker so a reviewer can see the check, not just trust it."""
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


def stage_rows(env: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for s in env["trace"]["stages"]:
        extra = {k: v for k, v in s.items() if k not in HIDDEN_KEYS}
        rows.append(
            {
                "stage": s["stage"],
                "ms": s.get("ms", ""),
                "at": s.get("at_ms", ""),
                "detail": json.dumps(extra, ensure_ascii=False, default=str)[:160],
            }
        )
    return rows


def under_the_hood(env: dict[str, Any]) -> None:
    g = env.get("grounding") or {}
    meta = f"intent {env['intent']}"
    if g:
        meta += f" · grounded {g.get('grounded')}/{g.get('checked')}"
    if env.get("model"):
        meta += f" · {env['model'].split('/')[-1]} · {env.get('latency_ms')} ms"
    if env.get("streamed"):
        meta += " · streamed" + (
            "" if env["streamed"].get("matches_reply") else ", then replaced after checks"
        )
    if env.get("degraded"):
        meta += " · degraded: offline stand-in"
    st.markdown(f'<div class="meta-line">{meta}</div>', unsafe_allow_html=True)
    with st.expander("Under the hood"):
        tabs = st.tabs(["Trace", "Retrieval", "Prompt", "Grounding", "Memory", "Model"])
        with tabs[0]:
            st.dataframe(stage_rows(env), use_container_width=True, hide_index=True)
        with tabs[1]:
            tools = [s for s in env["trace"]["stages"] if s["stage"] == "tool"]
            if tools:
                st.markdown("**Tool calls**")
                st.json(
                    [
                        {k: v for k, v in s.items() if k not in ("stage", "at_ms", "ms")}
                        for s in tools
                    ]
                )
            if env.get("query_explain"):
                q = env["query_explain"]
                if q.get("normalization"):
                    st.markdown("**Normalisation**")
                    st.write(q["normalization"])
                st.markdown("**Executed query**")
                st.code((q.get("executed") or {}).get("sql", ""), language="sql")
                st.json({k: v for k, v in q.items() if k not in ("normalization",)})
                for c in env.get("cars") or []:
                    ex = c.get("explain") or {}
                    if ex:
                        st.caption(
                            f"{c['id']}: {ex.get('rank_reason')}; filters {ex.get('matched_filters')}; stage {ex.get('admitted_at') or ex.get('stage', '')}"
                        )
            if env.get("resolver"):
                st.markdown("**Reference resolver**")
                st.json(env["resolver"])
            if not tools and not env.get("query_explain"):
                st.write("No tool call this turn.")
        with tabs[2]:
            blocks = next(
                (s.get("blocks") for s in env["trace"]["stages"] if s["stage"] == "prompt"), None
            )
            if blocks:
                st.caption(" · ".join(f"{b['name']} ~{b['tokens']}" for b in blocks) + " tokens")
                for b in blocks:
                    with st.expander(
                        f"{b['name']} (~{b['tokens']} tokens)",
                        expanded=b["name"] not in ("static",),
                    ):
                        st.text(b["text"])
            else:
                st.write("No model call this turn.")
        with tabs[3]:
            if g.get("spans"):
                st.markdown(mark_grounding(env["reply"], g))
                st.dataframe(
                    [
                        {
                            "figure": s["text"],
                            "grounded": s["grounded"],
                            "source": json.dumps(s.get("source"), default=str),
                        }
                        for s in g["spans"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No figures to check in this reply.")
        with tabs[4]:
            st.markdown("**Read**")
            st.write(env["memory"]["read"] or "nothing on file")
            st.markdown("**Written**")
            st.write(env["memory"]["writes"] or "none")
        with tabs[5]:
            st.json(
                {
                    k: env.get(k)
                    for k in (
                        "model",
                        "usage",
                        "latency_ms",
                        "streamed",
                        "verification",
                        "structured_reply",
                        "cited_listing_ids",
                        "request_id",
                    )
                }
            )


def render_envelope(env: dict[str, Any]) -> None:
    st.markdown(env["reply"])
    common.render_cards(env.get("cars") or [], show_index=common.demo())
    if common.demo():
        under_the_hood(env)


def page(h: dict[str, Any]) -> None:
    if not st.session_state.messages:
        st.markdown("### Ask about a car")
        st.caption("Search the inventory, compare listings, or book a viewing. Try one of these:")
        cols = st.columns(len(common.STARTERS))
        for col, s in zip(cols, common.STARTERS, strict=True):
            if col.button(s, key=f"chat_starter_{s}", use_container_width=True):
                st.session_state.pending_prompt = s
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
            if col.button(
                action,
                key=f"chip_{len(st.session_state.messages)}_{action}",
                use_container_width=True,
            ):
                st.session_state.pending_prompt = action
    prompt = st.chat_input("Ask about a car, or say hi")
    text = prompt or st.session_state.pending_prompt
    if text:
        st.session_state.pending_prompt = None
        send(text)
        st.rerun()
