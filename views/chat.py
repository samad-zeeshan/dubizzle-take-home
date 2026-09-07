"""Chat page. User mode is the product; demo mode adds the work behind every reply."""

from __future__ import annotations

import html
import json
import uuid
from typing import Any

import httpx
import streamlit as st

from views import common

HIDDEN_KEYS = ("stage", "at_ms", "ms", "blocks")
_MAX_ERROR = 160


def one_line(text: object) -> str:
    """A failure reaches the customer as one sentence. A pasted JSON body helps nobody read it."""
    s = str(text or "").strip()
    if s.startswith(("{", "[")):
        try:
            payload = json.loads(s)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, list) and detail:  # a 422 arrives as a list of field errors
                first = detail[0]
                detail = first.get("msg") if isinstance(first, dict) else first
            if isinstance(detail, str | int | float):
                s = str(detail)
            elif isinstance(payload.get("message"), str):
                s = payload["message"]
    s = " ".join(s.split())
    if not s or s.startswith(("{", "[")):
        return common.t("err.no_detail")
    return s[: _MAX_ERROR - 1] + "…" if len(s) > _MAX_ERROR else s


# A chip carries bidi isolates so the Latin car name keeps its year at the front inside an
# Arabic sentence. They are invisible, but the backend should never see them.
_BIDI_MARKS = dict.fromkeys(map(ord, "⁦⁧⁨⁩‎‏"))


def send(text: str) -> None:
    text = text.translate(_BIDI_MARKS)
    body: dict[str, Any] = {"message": text, "locale": common.lang()}
    if st.session_state.user_id:
        body["user_id"] = st.session_state.user_id
    if st.session_state.session_id:
        body["session_id"] = st.session_state.session_id
    elif st.session_state.user_name:
        body["name"] = st.session_state.user_name
    # The backend still gets the id so the resolver can pin the car; the transcript never shows it.
    shown = common.for_display(text)
    st.session_state.messages.append({"role": "user", "content": shown})
    with st.chat_message("user"):
        st.markdown(shown)
    envelope: dict[str, Any] | None = None
    error: str | None = None
    with st.chat_message("assistant"):
        status = st.status(common.t("chat.thinking"), expanded=common.demo())
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
                    error = f"{r.status_code}: {one_line(r.read().decode('utf-8', 'replace'))}"
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
                                error = f"{data.get('status')}: {one_line(data.get('detail'))}"
        except httpx.HTTPError as e:
            error = one_line(common.t("err.unreachable", error=e))
        draft.empty()
        status.update(
            label=common.t("chat.done") if envelope else common.t("chat.failed"),
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
                "content": common.t("chat.error", error=error),
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
    st.markdown(f'<div class="meta-line">{html.escape(meta)}</div>', unsafe_allow_html=True)
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


# The backend writes these four in English with a listing id in them. A chip is also what gets
# sent when it is clicked, so it has to read as something the customer would have typed.
_CHIP_TEMPLATES = (
    ("Tell me more about ", "chip.more"),
    ("Book a viewing for ", "chip.book"),
    ("Similar cars to ", "chip.similar"),
)


def friendly(action: str, cars: list[dict[str, Any]]) -> str:
    """Suggested actions arrive with listing ids; people should see the car, not the id."""
    if action == "Show more":
        return common.t("chip.show_more")
    for c in cars:
        if not c.get("id") or c["id"] not in action:
            continue
        # Make and model stay Latin in either language, the way the ads print them.
        name = common.car_name(c)
        for prefix, key in _CHIP_TEMPLATES:
            if action.startswith(prefix):
                return common.t(key, car=name)
        return action.replace(c["id"], f"the {name}")
    return action


def render_envelope(env: dict[str, Any], latest: bool = False) -> None:
    st.markdown(env["reply"])
    common.render_cards(
        env.get("cars") or [],
        show_index=common.demo(),
        key_prefix=env.get("request_id") if latest else None,
    )
    if common.demo():
        under_the_hood(env)


def welcome() -> None:
    """The empty chat: one question in the middle of the page, and for a known user the threads they can pick back up."""
    uid = st.session_state.user_id
    name = st.session_state.user_name
    prof = common.profile(uid) if uid else None
    recall: list[tuple[str, str]] = []
    if prof:
        for s in prof.get("recent_searches") or []:
            if s["query"] not in [r[1] for r in recall]:
                recall.append((s["query"], s["query"]))
            if len(recall) == 2:
                break
        for c in (prof.get("liked_cars") or [])[:1]:
            car = common.car_name(c)
            recall.append(
                (
                    f"{common.t('chat.more_on')} {car}",
                    f"{common.t('chip.more', car=car)} ({c['id']})",
                )
            )
    if recall:
        title, sub = common.t("chat.welcome_back", name=name), common.t("chat.welcome_back_sub")
    elif name:
        title, sub = (
            common.t("chat.hi_name", name=name),
            common.t("chat.hi_sub"),
        )
    else:
        title, sub = (
            common.t("chat.hi"),
            common.t("chat.hi_sub_new"),
        )
    with st.container(key="welcome"):
        st.markdown(
            f'<div class="welcome"><h2>{html.escape(title)}</h2><p>{html.escape(sub)}</p></div>',
            unsafe_allow_html=True,
        )
        if recall:
            st.caption(common.t("chat.where_left"))
            for col, (label, text) in zip(st.columns(len(recall)), recall, strict=True):
                if col.button(label, key=f"recall_{text}", use_container_width=True):
                    st.session_state.pending_prompt = text
            st.caption(common.t("chat.or_try"))
        starters = [s for s in common.starters() if s not in {text for _, text in recall}]
        cols = st.columns(2)
        for i, s in enumerate(starters):
            if cols[i % 2].button(s, key=f"chat_starter_{s}", use_container_width=True):
                st.session_state.pending_prompt = s


def page(h: dict[str, Any]) -> None:
    ask = st.query_params.get("ask")
    if ask and st.session_state.get("last_ask") != ask:
        # A photo or title link from a card lands here with the listing id. Sent once per session.
        st.session_state.last_ask = ask
        st.query_params.pop("ask")
        d = common.get_json(f"/inventory/{ask}")
        if d:
            st.session_state.pending_prompt = (
                f"{common.t('chip.more', car=common.car_name(d))} ({d['id']})"
            )
    if not st.session_state.messages:
        welcome()
    msgs = st.session_state.messages
    # Buttons live on the last reply that showed cars, and chips name any car seen this session.
    with_cards = [i for i, m in enumerate(msgs) if (m.get("envelope") or {}).get("cars")]
    hot = with_cards[-1] if with_cards else -1
    seen_cars = [c for m in msgs for c in ((m.get("envelope") or {}).get("cars") or [])]
    for i, m in enumerate(msgs):
        with st.chat_message(m["role"]):
            if m["role"] == "assistant" and m.get("envelope"):
                render_envelope(m["envelope"], latest=(i == hot))
            else:
                st.markdown(m["content"])
    last = msgs[-1] if msgs else None
    if last and last.get("envelope") and last["envelope"].get("suggested_actions"):
        env = last["envelope"]
        labels = [friendly(a, seen_cars) for a in env["suggested_actions"]]
        cols = st.columns(len(labels))
        for col, label in zip(cols, labels, strict=True):
            if col.button(label, key=f"chip_{len(msgs)}_{label}", use_container_width=True):
                st.session_state.pending_prompt = label
    prompt = st.chat_input(
        common.t("chat.input_known") if st.session_state.user_id else common.t("chat.input_new")
    )
    text = prompt or st.session_state.pending_prompt
    if text:
        st.session_state.pending_prompt = None
        send(text)
        st.rerun()
