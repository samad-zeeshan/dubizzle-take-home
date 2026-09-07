"""
One chat turn end to end: pre-filter, resolver, prompt, tool loop, grounding, persistence.

Every step writes a stage into the turn trace as a by-product, which is what
the client, the debug endpoints, and the export show. The model only ever sees
inventory through tool results, so the loop is where control lives, not the
prompt.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from dubizzle_assistant.config import Settings
from dubizzle_assistant.normalize import resolve_make_model
from dubizzle_assistant.services import guardrails, inventory, memory, streaming, tools
from dubizzle_assistant.services import summary as summary_mod
from dubizzle_assistant.services.context import TurnContext
from dubizzle_assistant.services.llm.base import (
    LLMClient,
    LLMError,
    LLMResponse,
    RateLimitedError,
    assistant_message,
    estimate_tokens,
    tool_result_message,
)
from dubizzle_assistant.services.llm.mock_client import (
    _search_args as search_args_from_text,  # pyright: ignore[reportPrivateUsage]
)
from dubizzle_assistant.services.prompts import REPLY_SCHEMA, build_blocks, system_message
from dubizzle_assistant.services.trace import TurnTrace, redact

log = logging.getLogger("dubizzle.agent")

_ID_RE = re.compile(r"\b[CR]-\d{3}\b")
_PROVIDER_FIELDS = (
    "provider_specific_fields",
    "reasoning_content",
    "thinking_blocks",
    "annotations",
)

LOOP_CAP_REPLY = "I ran out of steps on that one. Could you narrow it to one car or one question and I will pick it up from there?"
# The cap normally lands after the answer is already in the tool results, because the model spent
# its last steps on bookkeeping calls. Taking the tools away lets it speak instead of apologising.
LOOP_CAP_NOTE = {
    "role": "user",
    "content": "Answer now from the tool results you already have.",
}
EMPTY_REPLY = "I did not manage to put an answer together for that. Could you say it another way, or name the car you mean?"
# The prefilter declines got an Arabic twin and these two did not, so the one moment the guard
# fires was the one moment an Arabic session switched to English, inside an RTL container.
EMPTY_REPLY_AR = (
    "لم أتمكن من تكوين إجابة لذلك. هل يمكنك صياغته بطريقة أخرى، أو ذكر السيارة التي تقصدها؟"
)


def _ids_in(obj: Any) -> list[str]:
    found: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("id"), str) and _ID_RE.fullmatch(o["id"]):
                found.append(o["id"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return list(dict.fromkeys(found))


def _strip_provider_fields(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Thought signatures belong to one model family; after a fallback they would be rejected.
    out: list[dict[str, Any]] = []
    for m in messages:
        out.append({k: v for k, v in m.items() if k not in _PROVIDER_FIELDS})
    return out


def _parse_structured(text: str | None) -> tuple[str, list[str], bool]:
    """Accept the JSON reply shape when the model used it, plain text otherwise."""
    if not text:
        return "", [], False
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    if s.startswith("{") and "reply_markdown" in s:
        try:
            data = json.loads(s)
            reply = str(data.get("reply_markdown") or "")
            cited = [str(i).upper() for i in data.get("cited_listing_ids") or [] if i]
            return reply, cited, True
        except json.JSONDecodeError:
            pass
    return text, [], False


def _intent_from(tool_names: list[str], prefilter_hit: dict[str, Any] | None) -> str:
    if prefilter_hit:
        return prefilter_hit["intent"]
    if any(
        n in ("propose_viewing", "confirm_viewing", "cancel_viewing", "get_availability")
        for n in tool_names
    ):
        return "booking"
    if "update_lead" in tool_names:
        return "lead"
    if "compare_listings" in tool_names:
        return "compare"
    if "similar_listings" in tool_names:
        return "similar"
    if "identify_user" in tool_names:
        return "memory_recall"
    if "search_inventory" in tool_names:
        return "inventory_search"
    if "get_listing" in tool_names:
        return "listing_question"
    if any(n in ("like_listing", "remember_preference") for n in tool_names):
        return "preference"
    return "chitchat"


def _template_reply(ctx: TurnContext) -> str:
    """Grounded fallback built from cards only, used when the model keeps inventing figures."""
    ar = ctx.locale == "ar"
    cards = ctx.new_cards or [c for c in ctx.shown if c["id"] == ctx.focus_id]
    if not cards:
        if ar:
            return "هذا ما أستطيع تأكيده من بيانات الإعلان. أي سيارة تريد تفاصيلها؟"
        return "Here is what I can confirm from the listing data. Which car would you like the details of?"
    lines = []
    for c in cards[:5]:
        # Make and model stay in Latin and the digits stay Western, the same two rules the Arabic
        # prompt block gives the model, so the grounding check reads the figures back either way.
        if c.get("price_aed"):
            price = f"{c['price_aed']:,} درهم" if ar else f"AED {c['price_aed']:,}"
        else:
            price = "السعر غير مذكور" if ar else "price not listed"
        if c.get("mileage_km") is not None:
            km = f"{c['mileage_km']:,} كم" if ar else f"{c['mileage_km']:,} km"
        else:
            km = "الممشى غير مذكور" if ar else "mileage not stated"
        lines.append(
            f"- {c['year']} {str(c['make']).title()} {str(c['model']).title()}، {price}، {km}"
            if ar
            else f"- {c['year']} {str(c['make']).title()} {str(c['model']).title()}, {price}, {km}"
        )
    head = "إليك ما تذكره بيانات الإعلان:" if ar else "Here is what the listing data shows:"
    return head + "\n" + "\n".join(lines)


class ChatUnavailableError(RuntimeError):
    def __init__(self, message: str, status: int = 503, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _record_call(
    conn: sqlite3.Connection, ctx: TurnContext, n: int, resp: LLMResponse, purpose: str
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO llm_calls (ts, session_id, turn, n, model, reasoning, prompt_tokens, completion_tokens, latency_ms, finish_reason, cassette_hit, purpose) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ctx.now.isoformat(timespec="seconds"),
                ctx.session_id,
                ctx.turn,
                n,
                resp.model,
                ctx.settings.llm_reasoning,
                resp.usage.get("prompt_tokens", 0),
                resp.usage.get("completion_tokens", 0),
                resp.latency_ms,
                resp.finish_reason,
                int(resp.cassette_hit),
                purpose,
            ),
        )


# "any convertibles?" late in a long session sometimes gets "none in stock" from memory instead
# of a search. When the question is plainly about stock and no tool ran, the model is sent back once.
_STOCK_VERB_RE = re.compile(
    r"\b(any|which|what|show|do you have|have you got|got any|are there|is there|list|find|looking for|cheapest|most expensive|options|available|in stock)\b",
    re.I,
)
_STOCK_NOUN_RE = re.compile(
    r"\b(cars?|vehicles?|models?|options?|anything|stock|inventory|suvs?|sedans?|convertibles?|coupes?|hatchbacks?|pickups?|vans?|wagons?|trucks?|electric|hybrid|diesel|petrol|seater|brand new|automatic|manual)\b",
    re.I,
)
SEARCH_NUDGE = {
    "role": "user",
    "content": "You have not searched the inventory this turn. Call search_inventory now and answer only from its results.",
}


# "عندك تويوتا؟" asks exactly what "do you have a toyota?" asks. Without these the nudge never
# fires in Arabic, and a search whose only hit is the focused car has its card suppressed.
_STOCK_VERB_AR_RE = re.compile(
    r"عندك|عندكم|عندنا|يوجد|أبغى|ابغى|أبي|ابي|أريد|اريد|ودي|وريني|ورني|اعرض|أعرض|ابحث|أبحث|ابي"
)
_STOCK_NOUN_AR_RE = re.compile(
    r"سيار|عربي|موديل|دفع رباعي|سيدان|كوبيه|مكشوف|بيك اب|بيك أب|كهربائ|هجين|ديزل|بنزين|مقاعد|جديد"
)


def _stock_question(text: str) -> bool:
    low = text.lower()
    if not (_STOCK_VERB_RE.search(low) or _STOCK_VERB_AR_RE.search(low)):
        return False
    if _STOCK_NOUN_RE.search(low) or _STOCK_NOUN_AR_RE.search(low):
        return True
    return resolve_make_model(low)[0] is not None


# "hi, it's Sara again" is identity, not chit-chat. Small models skip the tool, so code runs it
# when the whole message is an introduction.
_INTRO_RE = re.compile(
    r"^(?:(?:hi|hello|hey|hiya|salam|marhaba|good (?:morning|afternoon|evening))[,!. ]*)?\s*"
    r"(?:i'?m|i am|my name is|it'?s|this is|call me)\s+([a-z][a-z'-]{1,30})(?:\s+(?:again|here|back))?[.!]*$",
    re.I,
)
_NOT_NAMES = {
    "fine",
    "ok",
    "okay",
    "good",
    "great",
    "me",
    "back",
    "here",
    "done",
    "not",
    "too",
    "all",
    "cool",
    "urgent",
    "bad",
    "late",
    "early",
    "new",
    "old",
    "the",
    "a",
    "an",
    "it",
    "that",
    "this",
    "true",
    "false",
    "time",
    "over",
    "ready",
    "sorry",
    "interested",
    "looking",
}


def _intro_name(message: str) -> str | None:
    m = _INTRO_RE.match(message.strip())
    if not m or m.group(1).lower() in _NOT_NAMES:
        return None
    return m.group(1)


def _pin_offscreen(ctx: TurnContext, resolved: dict[str, Any] | None) -> dict[str, Any] | None:
    """A reference to a car that is not on screen, from a card link or a remembered id, gets the listing pulled in first.

    The model then answers from facts that are already grounding sources instead of guessing or
    having to call a tool, which small models skip.
    """
    rid = (resolved or {}).get("resolved")
    if not rid or any(c["id"] == rid for c in ctx.shown):
        return None
    cards = inventory.get_cards(ctx.conn, [rid])
    if not cards:
        return None
    ctx.new_cards.extend(cards)
    ctx.tool_results.append({"name": "pinned_listing", "result": cards[0]})
    ctx.trace.add("pinned_listing", listing_id=rid)
    return cards[0]


def _scrub_for(settings: Settings) -> Callable[[str], str]:
    if settings.ablate_postfilter:
        return lambda text: text
    return lambda text: guardrails.postfilter(text)[0]


def _call(
    ctx: TurnContext,
    llm: LLMClient,
    messages: list[dict[str, Any]],
    schemas: list[dict[str, Any]] | None,
    n: int,
    *,
    want_schema: bool,
    model: str | None,
    purpose: str = "chat",
) -> LLMResponse:
    settings = ctx.settings
    use_model = model or settings.llm_model
    with ctx.trace.stage("llm_call", n=n, purpose=purpose) as rec:
        try:
            call_kwargs: dict[str, Any] = {
                "reasoning": settings.llm_reasoning,
                "response_schema": REPLY_SCHEMA if want_schema else None,
                "temperature": settings.temperature_for(use_model),
                "model": model,
                "purpose": purpose,
            }
            streamer = getattr(llm, "complete_stream", None)
            if (
                ctx.on_token is not None
                and streamer is not None
                and n > 1
                and purpose == "chat"
                and model is None
            ):
                # Draft text reaches the client a sentence at a time, scrubbed. The final reply may still replace it.
                gate = streaming.SentenceGate(_scrub_for(settings), ctx.on_token)
                extractor = streaming.ReplyFieldExtractor() if want_schema else None

                def _on_delta(piece: str) -> None:
                    gate.feed(extractor.feed(piece) if extractor else piece)

                resp = streamer(messages, schemas, on_token=_on_delta, **call_kwargs)
                gate.close()
                ctx.streamed_text = gate.emitted
                rec["streamed_chars"] = len(gate.emitted)
            else:
                resp = llm.complete(messages, schemas, **call_kwargs)
        except RateLimitedError as e:
            rec["error"] = str(e)
            if e.daily:
                raise ChatUnavailableError(
                    "The model's daily quota is used up. Try again after the reset, or run with LLM_PROVIDER=mock.",
                    503,
                ) from e
            raise ChatUnavailableError(
                f"The model is rate limited right now. Try again in about {int(e.retry_after or 20)} seconds.",
                429,
                e.retry_after,
            ) from e
        except LLMError as e:
            rec["error"] = str(e)
            fallback = settings.usable_fallback_model
            if n == 1 and fallback and model is None and settings.llm_provider == "litellm":
                rec["fallback"] = fallback
                try:
                    resp = llm.complete(
                        _strip_provider_fields(messages),
                        schemas,
                        reasoning=settings.llm_reasoning,
                        response_schema=REPLY_SCHEMA if want_schema else None,
                        temperature=settings.temperature_for(fallback),
                        model=fallback,
                        purpose=purpose,
                    )
                except LLMError as e2:
                    raise ChatUnavailableError(f"The model could not be reached: {e2}", 503) from e2
            else:
                raise ChatUnavailableError(f"The model could not be reached: {e}", 503) from e
        rec.update(
            {
                "model": resp.model,
                "latency_ms": resp.latency_ms,
                "tokens": resp.usage,
                "finish_reason": resp.finish_reason,
                "emitted": "tool_calls" if resp.tool_calls else "text",
                "tool_names": [tc.name for tc in resp.tool_calls],
                "text_chars": len(resp.text or ""),
                "cassette_hit": resp.cassette_hit,
                "note": resp.note,
            }
        )
    _record_call(ctx.conn, ctx, n, resp, purpose)
    return resp


def _lead_block(ctx: TurnContext) -> str | None:
    try:
        from dubizzle_assistant.services import leads
    except ImportError:
        return None
    return leads.prompt_block(ctx.conn, ctx.user_id)


def _grounding_pass(
    ctx: TurnContext, reply: str, sources: dict[str, dict[str, Any]], stage: str
) -> dict[str, Any]:
    with ctx.trace.stage(stage) as rec:
        g = guardrails.grounding_spans(reply, sources)
        rec.update(
            {"checked": g["checked"], "grounded": g["grounded"], "ungrounded": g["ungrounded"]}
        )
    return g


def run_turn(
    *,
    settings: Settings,
    conn: sqlite3.Connection,
    llm: LLMClient,
    user_id: str,
    session_id: str,
    message: str,
    request_id: str,
    on_stage: Callable[[dict[str, Any]], None] | None = None,
    embedder: Callable[[str], list[float]] | None = None,
    on_token: Callable[[str], None] | None = None,
    locale: str = "en",
) -> dict[str, Any]:
    started = time.monotonic()
    now = settings.now()
    turn = memory.begin_turn(conn, session_id, now)
    trace = TurnTrace(session_id, turn, request_id, settings.ablations_active)
    if on_stage:
        trace.listeners.append(on_stage)
    saved = memory.get_context(conn, session_id)
    user = memory.get_user(conn, user_id)
    ctx = TurnContext(
        settings=settings,
        conn=conn,
        user_id=user_id,
        session_id=session_id,
        turn=turn,
        trace=trace,
        now=now,
        request_id=request_id,
        shown=saved["shown"],
        focus_id=saved["focus_id"],
        pending_booking=saved["pending_booking"],
        locale=locale,
        embedder=embedder,
        user_name=user["name"] if user else None,
        raw_message=message,
        on_token=on_token,
    )
    trace.add("received", chars=len(message), turn=turn)
    user_msg: dict[str, Any] = {"role": "user", "content": message}

    hit = None
    if settings.ablate_prefilter:
        trace.add("prefilter", result="skipped (ablated)")
    else:
        with trace.stage("prefilter") as rec:
            hit = guardrails.prefilter(message, locale)
            rec["result"] = "declined" if hit else "passed"
            if hit:
                rec["rule"], rec["match"] = hit["rule"], hit["match"]
    if hit:
        return _finish(
            ctx,
            user_msg,
            [],
            hit["reply"],
            intent=hit["intent"],
            resolved=None,
            recall=None,
            grounding=None,
            cited=[],
            structured=False,
            usage={},
            model=None,
            started=started,
            llm_used=False,
        )

    intro = _intro_name(message)
    if intro and memory.name_key(ctx.user_name or "") in ("", "guest"):
        with trace.stage("tool", name="identify_user", args={"name": intro}, by="rule") as rec:
            result = tools.run_tool(ctx, "identify_user", {"name": intro})
            rec["result_ids"] = []
        ctx.tool_results.append(
            {"name": "identify_user", "args": {"name": intro}, "result": result}
        )
        user_id = ctx.user_id

    resolved: dict[str, Any] | None = None
    if settings.ablate_resolver:
        trace.add("resolver", result="skipped (ablated)")
    else:
        with trace.stage("resolver") as rec:
            resolved = memory.resolve_reference(message, ctx.shown, ctx.focus_id)
            rec.update({k: resolved.get(k) for k in ("input", "resolved", "rule", "candidates")})
            if resolved.get("ambiguous"):
                rec["ambiguous"] = resolved["ambiguous"]
            if resolved.get("resolved"):
                ctx.focus_id = resolved["resolved"]

    with trace.stage("memory_read") as rec:
        prof = memory.profile(conn, user_id, now)
        recall = memory.recall_block(prof)
        lead_block = _lead_block(ctx)
        summary = saved.get("summary_text")
        rec.update(
            {
                "recall": recall,
                "lead_block": lead_block,
                "summary_present": bool(summary),
                "returning": bool(recall),
            }
        )

    with trace.stage("prompt") as rec:
        pinned = _pin_offscreen(ctx, resolved)
        blocks = build_blocks(
            ctx,
            recall=recall,
            resolved=resolved,
            lead_block=lead_block,
            summary=summary,
            pinned=pinned,
        )
        history = memory.load_history(
            conn,
            session_id,
            settings.history_turns,
            after_turn=saved.get("summary_through_turn", 0),
        )
        messages: list[dict[str, Any]] = [system_message(blocks), *history, user_msg]
        rec["blocks"] = blocks
        rec["history_messages"] = len(history)
        rec["history_tokens_estimate"] = sum(
            estimate_tokens(json.dumps(m, default=str)) for m in history
        )
        rec["total_tokens_estimate"] = (
            sum(b["tokens"] for b in blocks)
            + rec["history_tokens_estimate"]
            + estimate_tokens(message)
        )

    return _run_loop(
        ctx,
        llm,
        messages,
        user_msg,
        resolved=resolved,
        recall=recall,
        started=started,
        summary_prev=summary,
        summary_through=saved.get("summary_through_turn", 0),
    )


def _run_loop(
    ctx: TurnContext,
    llm: LLMClient,
    messages: list[dict[str, Any]],
    user_msg: dict[str, Any],
    *,
    resolved: dict[str, Any] | None,
    recall: str | None,
    started: float,
    summary_prev: str | None = None,
    summary_through: int = 0,
) -> dict[str, Any]:
    settings, trace = ctx.settings, ctx.trace
    schemas = tools.tool_schemas()
    turn_msgs: list[dict[str, Any]] = []
    tool_names: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    final: LLMResponse | None = None
    turn_model: str | None = None
    n = 0
    nudged = False
    ctx.stock_request = _stock_question(ctx.raw_message)
    while n < settings.max_tool_iterations:
        n += 1
        resp = _call(
            ctx,
            llm,
            messages,
            schemas,
            n,
            want_schema=settings.structured_reply_for(turn_model or settings.llm_model) and n > 1,
            model=turn_model,
        )
        if resp.model != settings.llm_model and settings.llm_provider == "litellm":
            turn_model = resp.model
        for k in usage:
            usage[k] += resp.usage.get(k, 0)
        if resp.empty:
            trace.add("empty_response", n=n, finish_reason=resp.finish_reason)
            resp = _call(
                ctx,
                llm,
                messages,
                schemas,
                n,
                want_schema=False,
                model=turn_model,
                purpose="retry_empty",
            )
            for k in usage:
                usage[k] += resp.usage.get(k, 0)
            if resp.empty:
                final = LLMResponse(
                    text=EMPTY_REPLY_AR if ctx.locale == "ar" else EMPTY_REPLY,
                    tool_calls=[],
                    finish_reason="empty",
                    usage={},
                    raw_message={},
                    model=resp.model,
                    latency_ms=0,
                )
                break
        if resp.tool_calls:
            am = assistant_message(resp)
            messages.append(am)
            turn_msgs.append(am)
            for tc in resp.tool_calls:
                tool_names.append(tc.name)
                with trace.stage("tool", name=tc.name, args=redact(tc.arguments)) as rec:
                    result = tools.run_tool(ctx, tc.name, tc.arguments)
                    extra = result.pop("_trace", None)
                    if extra:
                        rec.update(extra)
                    rec["result_ids"] = _ids_in(result)
                    if result.get("error"):
                        rec["error"] = result["error"]
                    if tc.name in ("search_inventory", "similar_listings"):
                        rec["total_matches"] = result.get("total_matches")
                        rec["normalization"] = result.get("normalization")
                ctx.tool_results.append({"name": tc.name, "args": tc.arguments, "result": result})
                tm = tool_result_message(tc.id, tc.name, result)
                messages.append(tm)
                turn_msgs.append(tm)
            continue
        if (
            n == 1
            and not ctx.tool_results
            and not ctx.pending_booking
            and not (resolved or {}).get("resolved")
            and ctx.stock_request
        ):
            trace.add("search_nudge", reason="stock question answered without a search")
            messages.append(SEARCH_NUDGE)
            nudged = True
            continue
        if nudged and n == 2 and not ctx.tool_results:
            # The note was ignored too. Code runs the search the user asked for and the model narrates it.
            args = search_args_from_text(ctx.raw_message) or {"keywords": ctx.raw_message}
            with trace.stage("tool", name="search_inventory", args=redact(args), by="rule") as rec:
                result = tools.run_tool(ctx, "search_inventory", args)
                extra = result.pop("_trace", None)
                if extra:
                    rec.update(extra)
                rec["result_ids"] = _ids_in(result)
                rec["total_matches"] = result.get("total_matches")
                rec["normalization"] = result.get("normalization")
            ctx.tool_results.append({"name": "search_inventory", "args": args, "result": result})
            tool_names.append("search_inventory")
            messages.append(
                {
                    "role": "user",
                    "content": "search_inventory was run for you with "
                    + json.dumps(args, ensure_ascii=False)
                    + ". Its result: "
                    + json.dumps(result, ensure_ascii=False, default=str)
                    + " Answer from these results only.",
                }
            )
            continue
        final = resp
        break
    if final is None:
        messages.append(LOOP_CAP_NOTE)
        n += 1
        try:
            capped = _call(
                ctx,
                llm,
                messages,
                None,
                n,
                want_schema=settings.structured_reply_for(turn_model or settings.llm_model),
                model=turn_model,
                purpose="loop_cap",
            )
        except ChatUnavailableError:
            capped = None
        if capped is not None and (capped.text or "").strip():
            final = capped
            for k in usage:
                usage[k] += capped.usage.get(k, 0)
        trace.add("loop_cap", iterations=n, recovered=final is not None)
    if final is None:
        final = LLMResponse(
            text=LOOP_CAP_REPLY,
            tool_calls=[],
            finish_reason="loop_cap",
            usage={},
            raw_message={},
            model=turn_model or settings.llm_model,
            latency_ms=0,
        )

    reply, cited, structured = _parse_structured(final.text)
    known = {c["id"] for c in ctx.shown} | {c["id"] for c in ctx.new_cards}
    dropped = [i for i in cited if i not in known]
    cited = [i for i in cited if i in known]
    trace.add("structured_reply", structured=structured, cited=cited, dropped_unknown=dropped)
    if not reply.strip():
        reply = EMPTY_REPLY_AR if ctx.locale == "ar" else EMPTY_REPLY

    if settings.ablate_postfilter:
        trace.add("postfilter", result="skipped (ablated)")
    else:
        reply, hits = guardrails.postfilter(reply)
        trace.add("postfilter", hits=hits)

    post_filter: dict[str, Any] = {"id_leak": False, "leaked_ids": []}
    if not settings.ablate_postfilter:
        leaked = guardrails.ids_in_prose(reply)
        if leaked:
            post_filter["leaked_ids"] = leaked
            reply = _rewrite_without_ids(ctx, llm, messages, reply, leaked, turn_model, usage)
            if guardrails.ids_in_prose(reply):
                # The model would not let go of them, so the text loses them on the way out.
                reply, post_filter["id_leak"] = guardrails.strip_ids(reply), True
        trace.add("id_check", leaked=leaked, id_leak=post_filter["id_leak"])

    sources = guardrails.collect_sources(ctx.tool_results, ctx.shown + ctx.new_cards)
    # The recall, summary, and lead blocks are written by the server from the database, so their figures are sourced too.
    # The customer's own message is a source for the same reason. Without it "do you have a 2023
    # X6" marked 2023 a hallucination, spent the retry and fell to the template, which in an
    # Arabic session meant the whole reply came back in English. It goes last so a figure that is
    # also a listing price keeps the listing's label.
    for label, block in (
        ("memory", recall),
        ("summary", summary_prev),
        ("lead", _lead_block(ctx)),
        ("user_message", ctx.raw_message),
    ):
        for key in guardrails.figures_in(block or ""):
            sources.setdefault(key, {"listing_id": None, "field": label})
    grounding: dict[str, Any] | None = None
    if settings.ablate_grounding_check:
        trace.add("grounding", result="skipped (ablated)")
    else:
        grounding = _grounding_pass(ctx, reply, sources, "grounding")
        if grounding["ungrounded"]:
            note = {
                "role": "user",
                "content": f"The figures {', '.join(grounding['ungrounded'])} do not appear in the tool results. Rewrite the reply using only figures from the tool results, or say the listing does not state it.",
            }
            retry_msgs = [*messages, {"role": "assistant", "content": reply}, note]
            reply2 = reply
            try:
                resp2 = _call(
                    ctx,
                    llm,
                    retry_msgs,
                    None,
                    n + 1,
                    want_schema=False,
                    model=turn_model,
                    purpose="regenerate",
                )
                for k in usage:
                    usage[k] += resp2.usage.get(k, 0)
                reply2, _, _ = _parse_structured(resp2.text)
                if not settings.ablate_postfilter:
                    reply2, _ = guardrails.postfilter(reply2)
                g2 = _grounding_pass(ctx, reply2, sources, "grounding_retry")
            except ChatUnavailableError:
                g2 = {"ungrounded": ["(retry unavailable)"]}
            if not g2["ungrounded"] and reply2.strip():
                reply, grounding = reply2, g2
            else:
                reply = _template_reply(ctx)
                grounding = _grounding_pass(ctx, reply, sources, "grounding_fallback")

    verification = None
    if settings.verify_mode == "llm":
        verification = _verify(ctx, llm, reply, messages, usage)
        if verification and not verification.get("all_supported"):
            claims = [
                str(v.get("claim"))
                for v in verification.get("verdicts", [])
                if not v.get("supported", True)
            ]
            note = {
                "role": "user",
                "content": f"A check found these claims unsupported by the tool results: {'; '.join(claims)}. Rewrite the reply using only what the tool results state.",
            }
            try:
                resp3 = _call(
                    ctx,
                    llm,
                    [*messages, {"role": "assistant", "content": reply}, note],
                    None,
                    n + 2,
                    want_schema=False,
                    model=turn_model,
                    purpose="regenerate_verify",
                )
                reply3, _, _ = _parse_structured(resp3.text)
                if reply3.strip():
                    reply = (
                        reply3 if settings.ablate_postfilter else guardrails.postfilter(reply3)[0]
                    )
                    if grounding is not None:
                        grounding = _grounding_pass(ctx, reply, sources, "grounding_after_verify")
                    verification["regenerated"] = True
            except ChatUnavailableError:
                verification["regenerated"] = False

    summary_mod.maybe_update(ctx, llm, summary_prev, summary_through)

    final_msg = assistant_message(final)
    final_msg["content"] = reply
    turn_msgs.append(final_msg)
    return _finish(
        ctx,
        user_msg,
        turn_msgs,
        reply,
        intent=_intent_from(tool_names, None),
        resolved=resolved,
        recall=recall,
        grounding=grounding,
        cited=cited,
        structured=structured,
        usage=usage,
        model=turn_model or final.model,
        started=started,
        llm_used=True,
        verification=verification,
        post_filter=post_filter,
    )


def _rewrite_without_ids(
    ctx: TurnContext,
    llm: LLMClient,
    messages: list[dict[str, Any]],
    reply: str,
    leaked: list[str],
    turn_model: str | None,
    usage: dict[str, int],
) -> str:
    """One corrected attempt at the same answer with the cars named instead of numbered."""
    note = {
        "role": "user",
        "content": (
            f"The reply contains listing ids ({', '.join(leaked)}). Rewrite it with the same facts, "
            "naming each car by year, make, and model, and with no listing id anywhere in the text."
        ),
    }
    try:
        resp = _call(
            ctx,
            llm,
            [*messages, {"role": "assistant", "content": reply}, note],
            None,
            0,
            want_schema=False,
            model=turn_model,
            purpose="regenerate_ids",
        )
    except ChatUnavailableError:
        return reply
    for k in usage:
        usage[k] += resp.usage.get(k, 0)
    rewritten, _, _ = _parse_structured(resp.text)
    if not rewritten.strip():
        return reply
    if not ctx.settings.ablate_postfilter:
        rewritten, _ = guardrails.postfilter(rewritten)
    return rewritten


def _verify(
    ctx: TurnContext,
    llm: LLMClient,
    reply: str,
    messages: list[dict[str, Any]],
    usage: dict[str, int],
) -> dict[str, Any] | None:
    try:
        from dubizzle_assistant.services import verify
    except ImportError:
        return None
    return verify.run(ctx, llm, reply, messages, usage)


def _finish(
    ctx: TurnContext,
    user_msg: dict[str, Any],
    turn_msgs: list[dict[str, Any]],
    reply: str,
    *,
    intent: str,
    resolved: dict[str, Any] | None,
    recall: str | None,
    grounding: dict[str, Any] | None,
    cited: list[str],
    structured: bool,
    usage: dict[str, int],
    model: str | None,
    started: float,
    llm_used: bool,
    verification: dict[str, Any] | None = None,
    post_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn, trace = ctx.conn, ctx.trace
    if not turn_msgs:
        turn_msgs = [{"role": "assistant", "content": reply}]
    with trace.stage("persist") as rec:
        memory.append_messages(conn, ctx.session_id, ctx.turn, [user_msg, *turn_msgs], ctx.now)
        shown = memory.push_shown(ctx.shown, ctx.new_cards, ctx.turn)
        memory.save_context(
            conn,
            ctx.session_id,
            shown=shown,
            focus_id=ctx.focus_id,
            pending_booking=ctx.pending_booking,
        )
        rec.update(
            {"messages": len(turn_msgs) + 1, "shown_total": len(shown), "focus_id": ctx.focus_id}
        )
        for w in ctx.memory_writes:
            trace.add("memory_write", **w)
    index = {c["id"]: c["display_index"] for c in shown}
    cars = [{**c, "display_index": index.get(c["id"])} for c in ctx.new_cards]
    trace.add("reply", chars=len(reply), intent=intent, cited=cited)

    last_search = next(
        (
            s
            for s in reversed(trace.stages)
            if s["stage"] == "tool" and s.get("name") in ("search_inventory", "similar_listings")
        ),
        None,
    )
    query_explain = None
    if last_search:
        query_explain = {
            "normalization": last_search.get("normalization"),
            "executed": last_search.get("executed"),
            "stage_counts": last_search.get("stage_counts"),
            "relaxed": last_search.get("relaxed"),
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    trace_dict = trace.to_dict()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO turn_traces (session_id, turn, request_id, trace_json, created_at) VALUES (?,?,?,?,?)",
            (
                ctx.session_id,
                ctx.turn,
                ctx.request_id,
                json.dumps(trace_dict, ensure_ascii=False, default=str),
                ctx.now.isoformat(timespec="seconds"),
            ),
        )
    identified = next((w for w in ctx.memory_writes if w.get("table") == "users"), None)
    actions = list(dict.fromkeys(ctx.suggested_actions))[:4]
    if ctx.pending_booking and "Confirm the viewing" not in actions:
        actions.insert(0, "Confirm the viewing")
    envelope = {
        "session_id": ctx.session_id,
        "user_id": ctx.user_id,
        "turn": ctx.turn,
        "request_id": ctx.request_id,
        "reply": reply,
        "streamed": None
        if ctx.streamed_text is None
        else {
            "chars": len(ctx.streamed_text),
            "matches_reply": ctx.streamed_text.strip() == reply.strip(),
        },
        "intent": intent,
        "cars": cars,
        "suggested_actions": actions,
        "resolver": {k: resolved.get(k) for k in ("input", "resolved", "rule")}
        if resolved
        else None,
        "query_explain": query_explain,
        "trace": trace_dict,
        "grounding": grounding,
        "post_filter": post_filter or {"id_leak": False, "leaked_ids": []},
        "memory": {"read": recall, "writes": ctx.memory_writes},
        "verification": verification,
        "structured_reply": structured,
        "cited_listing_ids": cited,
        "focus_id": ctx.focus_id,
        "pending_booking": ctx.pending_booking,
        "identified_user": {"user_id": identified["user_id"], "name": ctx.user_name}
        if identified
        else None,
        "llm_used": llm_used,
        "model": model,
        "usage": usage,
        "latency_ms": latency_ms,
    }
    log.info(
        "turn session=%s turn=%d intent=%s tools=%s cars=%d grounded=%s ms=%d",
        ctx.session_id,
        ctx.turn,
        intent,
        [s.get("name") for s in trace.stages if s["stage"] == "tool"],
        len(cars),
        f"{grounding['grounded']}/{grounding['checked']}" if grounding else "-",
        latency_ms,
    )
    return envelope
