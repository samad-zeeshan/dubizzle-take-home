"""
Two stand-ins for the model: a scripted one for tests and a rule-based one for offline demos.

The heuristic client behaves like a cooperative tool-calling model. It reads
the user's message, picks the tool a real model would pick, and then writes a
grounded reply from the tool result. It exists so the whole app, including
Streamlit, runs with LLM_PROVIDER=mock and no key.
"""

from __future__ import annotations

import json
import re
from typing import Any

from dubizzle_assistant.normalize import parse_budget, resolve_make_model
from dubizzle_assistant.services.llm.base import LLMError, LLMResponse, ToolCall

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|hiya|salam|marhaba|مرحبا|السلام عليكم|good (morning|afternoon|evening)|how are you|how's it going)\b",
    re.I,
)
_BOOK_RE = re.compile(
    r"\b(book|booking|viewing|test ?drive|reserve|schedule|appointment|visit)\b|\bاحجز\b|\bحجز\b",
    re.I,
)
_CONFIRM_RE = re.compile(
    r"^\s*(yes|yep|yeah|sure|confirm|confirmed|go ahead|ok(ay)?|that works|works for me|please do|do it|book it|نعم|اكيد|تمام)\b",
    re.I,
)
_CANCEL_RE = re.compile(r"\bcancel\b", re.I)
_COMPARE_RE = re.compile(r"\bcompare|\bvs\.?\b|\bversus\b|\bdifference between\b", re.I)
_LIKE_RE = re.compile(
    r"\b(i like|i love|save|shortlist|favou?rite|remember that one|i'll take)\b", re.I
)
_REMEMBER_RE = re.compile(
    r"\b(remember|note that|keep in mind|my budget is|i only want|i prefer|i'm looking for a|i am looking for a)\b",
    re.I,
)
_DETAIL_RE = re.compile(
    r"\b(mileage|km|kilomet|warranty|price|how much|cost|colou?r|spec|gcc|year|engine|interior|seats|does it|is it|is there|tell me more|details|about it|about that|about the)\b",
    re.I,
)
_MORE_RE = re.compile(r"\b(show more|more results|more cars|next page|others)\b", re.I)
_WHATS_BOOKED_RE = re.compile(r"\b(what.*booked|my bookings?|my viewings?|upcoming)\b", re.I)
_RECALL_RE = re.compile(r"\b(what was i|last time|previously|earlier i|remind me)\b", re.I)
_SELL_RE = re.compile(r"\b(sell my|selling my|want to sell|trade in my)\b", re.I)

_COLORS = (
    "white",
    "black",
    "silver",
    "grey",
    "gray",
    "red",
    "blue",
    "beige",
    "brown",
    "green",
    "orange",
    "gold",
    "yellow",
)
_BODIES = {
    "suv": "suv",
    "suvs": "suv",
    "sedan": "sedan",
    "coupe": "coupe",
    "hatchback": "hatchback",
    "pickup": "pickup",
    "truck": "pickup",
    "van": "van",
    "convertible": "convertible",
    "4x4": "suv",
    "family car": "suv",
    "7 seater": "suv",
    "seven seater": "suv",
}
_FEATURES = (
    "panoramic",
    "sunroof",
    "leather",
    "carplay",
    "camera",
    "cruise",
    "4wd",
    "awd",
    "7 seats",
    "seven seats",
    "electric",
    "hybrid",
    "diesel",
    "full option",
    "body kit",
    "service history",
    "low mileage",
    "brabus",
    "amg",
)
_HOUR_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", re.I)
_DATE_WORD_RE = re.compile(
    r"\b(today|tomorrow|day after tomorrow|tonight|this (?:week|weekend)|next (?:week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\w*|\d{4}-\d{2}-\d{2})\b",
    re.I,
)
_ID_RE = re.compile(r"\b([CR]-\d{3})\b", re.I)


def _last_user(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _tool_results_this_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in reversed(messages):
        if m.get("role") == "user":
            break
        if m.get("role") == "tool":
            try:
                out.append({"name": m.get("name"), "data": json.loads(m.get("content") or "{}")})
            except json.JSONDecodeError:
                out.append({"name": m.get("name"), "data": {"text": m.get("content")}})
    out.reverse()
    return out


def _system_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")


def _resolved_from_prompt(system: str) -> str | None:
    m = re.search(r"Resolved reference: .*? refers to listing ([CR]-\d{3})", system)
    return m.group(1) if m else None


def _focus_from_prompt(system: str) -> str | None:
    m = re.search(r"Resolved reference: .*? refers to listing ([CR]-\d{3})", system) or re.search(
        r"Current focus: ([CR]-\d{3})", system
    )
    return m.group(1) if m else None


def _shown_from_prompt(system: str) -> list[str]:
    block = system.split("## Cars on screen", 1)
    if len(block) < 2:
        return []
    return re.findall(r"#\d+\s+([CR]-\d{3})", block[1].split("##", 1)[0])


def _pending_from_prompt(system: str) -> bool:
    return "## Pending booking" in system


def _search_args(text: str) -> dict[str, Any]:
    low = text.lower()
    args: dict[str, Any] = {}
    make, model, _ = resolve_make_model(low)
    if make:
        args["make"] = make
    if model:
        args["model"] = model
    for word, bt in _BODIES.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            args["body_type"] = bt
            break
    for c in _COLORS:
        if re.search(rf"\b{c}\b", low):
            args["color"] = c
            break
    if re.search(r"\d", low) and re.search(
        r"\$|aed|dhs|k\b|budget|under|below|less than|month|max", low
    ):
        m = re.search(
            r"(?:under|below|less than|max|up to|budget of|budget)?\s*\$?\s*\d[\d,\.]*\s*k?\s*(?:aed|dhs|usd|dollars|\$)?(?:\s*(?:a|per)\s*month|/mo(?:nth)?)?",
            low,
        )
        if m and parse_budget(m.group(0)):
            args["budget_text"] = m.group(0).strip()
    ym = re.search(r"\b(20[0-2]\d)\b\s*(?:or newer|and newer|\+|onwards)", low) or re.search(
        r"(?:from|after|newer than|since)\s+(20[0-2]\d)", low
    )
    if ym:
        args["year_min"] = int(ym.group(1))
    if "warranty" in low:
        args["has_warranty"] = True
    if re.search(r"\bbrand new\b|\bnew cars?\b|\b0 ?km\b", low):
        args["is_brand_new"] = True
    if re.search(r"\bgcc\b", low):
        args["regional_spec"] = "gcc"
    if re.search(r"\belectric\b|\bev\b", low):
        args["fuel_type"] = "electric"
    elif "diesel" in low:
        args["fuel_type"] = "diesel"
    if "inspected" in low or "managed" in low:
        args["is_dubizzle_managed"] = True
    if "cheapest" in low or "lowest price" in low:
        args["sort"] = "price_asc"
    elif "newest" in low or "latest" in low:
        args["sort"] = "year_desc"
    kws = [f for f in _FEATURES if f in low and f not in ("electric", "diesel", "hybrid")]
    if kws:
        args["keywords"] = " ".join(kws)
    return args


def _money(v: Any) -> str:
    return f"AED {int(v):,}" if v is not None else "price not listed"


def _card_line(c: dict[str, Any]) -> str:
    bits = [_money(c.get("price_aed"))]
    if c.get("monthly_aed"):
        bits.append(f"AED {int(c['monthly_aed']):,}/month")
    bits.append(
        f"{int(c['mileage_km']):,} km" if c.get("mileage_km") is not None else "mileage not stated"
    )
    if c.get("regional_spec"):
        bits.append(f"{str(c['regional_spec']).upper()} spec")
    if c.get("has_warranty"):
        bits.append("warranty mentioned")
    idx = c.get("display_index")
    return f"{'#' + str(idx) + ' ' if idx else ''}{c['id']}: {c['year']} {str(c['make']).title()} {str(c['model']).title()} ({', '.join(bits)})"


def _reply_for_results(results: list[dict[str, Any]], user: str) -> tuple[str, list[str]]:
    for r in results:
        name, data = r["name"], r["data"]
        if name == "search_inventory":
            cars = data.get("results", [])
            ids = [c["id"] for c in cars]
            if not cars:
                return (
                    "I could not find anything matching that in the current inventory. Want me to widen the search?",
                    [],
                )
            head = (
                f"I found {data.get('total_matches', len(cars))} matching cars"
                + (f", showing {len(cars)}" if data.get("total_matches", 0) > len(cars) else "")
                + "."
            )
            if data.get("relaxed_filters"):
                head = f"No exact match, so I relaxed {', '.join(data['relaxed_filters'])}. Closest cars:"
            b = data.get("price_buckets") or {}
            tail = ""
            if b.get("price_not_listed"):
                tail = f" {b['price_not_listed']} of these do not state a price in the listing."
            return (head + "\n" + "\n".join("- " + _card_line(c) for c in cars) + tail, ids)
        if name == "get_listing":
            c = data
            if "error" in c:
                return (c["error"], [])
            low = user.lower()
            name_str = (
                f"the {c['year']} {str(c['make']).title()} {str(c['model']).title()} ({c['id']})"
            )
            if re.search(r"mileage|km|kilomet", low):
                ans = (
                    f"{name_str} has {int(c['mileage_km']):,} km on the odometer."
                    if c.get("mileage_km") is not None
                    else f"The listing for {name_str} does not state the mileage."
                )
            elif "warrant" in low:
                ans = (
                    f"Yes, the listing for {name_str} mentions a warranty: {c.get('warranty_text') or 'details as listed'}."
                    if c.get("has_warranty")
                    else f"The listing for {name_str} does not mention a warranty."
                )
            elif re.search(r"price|how much|cost", low):
                ans = (
                    f"{name_str} is listed at {_money(c['price_aed'])}."
                    if c.get("price_aed")
                    else f"The listing for {name_str} does not state a total price"
                    + (
                        f", only an instalment of AED {int(c['monthly_aed']):,} per month."
                        if c.get("monthly_aed")
                        else "."
                    )
                )
            elif "colo" in low:
                ans = (
                    f"{name_str} is {c['exterior_color']}."
                    if c.get("exterior_color")
                    else f"The listing for {name_str} does not state the colour."
                )
            else:
                ans = f"{name_str}: {c.get('english_summary', '')}"
            return (ans, [c["id"]])
        if name == "compare_listings":
            cards = data.get("cards", [])
            return (
                "Side by side:\n" + "\n".join("- " + _card_line(c) for c in cards),
                [c["id"] for c in cards],
            )
        if name in (
            "propose_viewing",
            "confirm_viewing",
            "cancel_viewing",
            "get_availability",
            "update_lead",
            "remember_preference",
            "like_listing",
            "identify_user",
        ):
            text = (
                data.get("readback") or data.get("message") or json.dumps(data, ensure_ascii=False)
            )
            if data.get("alternatives"):
                text += (
                    " Free slots: "
                    + ", ".join(a.get("label", str(a)) for a in data["alternatives"][:3])
                    + "."
                )
            return (text, [data["listing_id"]] if data.get("listing_id") else [])
    return ("Done.", [])


class ScriptedLLM:
    """Returns canned responses in order. For tests that need exact control of the loop."""

    name = "scripted"
    model = "mock/scripted"

    def __init__(self, responses: list[LLMResponse | dict[str, Any]]) -> None:
        self._queue = [r if isinstance(r, LLMResponse) else self.make(**r) for r in responses]
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def make(
        text: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str = "stop",
    ) -> LLMResponse:
        calls = [
            ToolCall(
                id=tc.get("id", f"call_{i}"), name=tc["name"], arguments=tc.get("arguments", {})
            )
            for i, tc in enumerate(tool_calls or [], start=1)
        ]
        return LLMResponse(
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else finish_reason,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            raw_message={},
            model="mock/scripted",
            latency_ms=1,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, **kwargs})
        if not self._queue:
            raise LLMError("scripted model ran out of responses")
        return self._queue.pop(0)

    def embed(self, text: str) -> list[float]:
        raise LLMError("scripted model has no embeddings")


def _hour_from(text: str) -> int | None:
    hm = _HOUR_RE.search(text)
    if not hm:
        return None
    if hm.group(1):
        h = int(hm.group(1)) % 12
        return h + 12 if hm.group(3).lower() == "pm" else h
    return int(hm.group(4))


class HeuristicLLM:
    """Rule-based stand-in: picks the tool a cooperative model would pick, then writes a grounded reply."""

    name = "mock"
    model = "mock/heuristic"

    def __init__(self) -> None:
        self._n = 0

    def _resp(self, text: str | None = None, calls: list[ToolCall] | None = None) -> LLMResponse:
        self._n += 1
        return LLMResponse(
            text=text,
            tool_calls=calls or [],
            finish_reason="tool_calls" if calls else "stop",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            raw_message={},
            model=self.model,
            latency_ms=2,
        )

    def _call(self, name: str, **args: Any) -> ToolCall:
        return ToolCall(id=f"call_{self._n + 1}_{name}", name=name, arguments=args)

    def embed(self, text: str) -> list[float]:
        raise LLMError("the mock model has no embeddings")

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        reasoning: str = "low",
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        model: str | None = None,
        purpose: str = "chat",
    ) -> LLMResponse:
        user = _last_user(messages)
        system = _system_text(messages)
        results = _tool_results_this_turn(messages)
        available = {t["function"]["name"] for t in tools or []}

        if purpose == "verify":
            return self._resp(json.dumps({"verdicts": [], "all_supported": True}))
        if purpose == "summary":
            turns = sum(1 for m in messages if m.get("role") == "user")
            return self._resp(
                f"Earlier in this session the user exchanged {turns} messages about cars in the inventory."
            )

        if results:
            text, cited = _reply_for_results(results, user)
            if response_schema:
                return self._resp(
                    json.dumps(
                        {"reply_markdown": text, "cited_listing_ids": cited, "fields_used": []}
                    )
                )
            return self._resp(text)

        low = user.lower()
        focus = _focus_from_prompt(system)
        resolved = _resolved_from_prompt(system)
        shown = _shown_from_prompt(system)
        explicit = [i.upper() for i in _ID_RE.findall(user)]

        if _GREETING_RE.search(low) and len(low) < 60:
            return self._resp(
                "Hello! I can help you explore the cars in our inventory, compare them, or book a viewing. What are you looking for?"
            )
        if _SELL_RE.search(low):
            return self._resp(
                "I can note that you are looking to sell. Listings are created on dubizzle itself, and I can record your details as a lead so the team can follow up. Meanwhile, is there anything in our inventory you would like to see?"
            )
        if _RECALL_RE.search(low):
            return self._resp(
                "Here is what I have on file for you from earlier sessions. Would you like to pick up where you left off?"
            )
        if _WHATS_BOOKED_RE.search(low):
            return self._resp(
                "Your confirmed viewings are listed in the sidebar under My bookings. Would you like to book another or cancel one?"
            )
        if (
            _CONFIRM_RE.search(low)
            and _pending_from_prompt(system)
            and "confirm_viewing" in available
        ):
            return self._resp(calls=[self._call("confirm_viewing")])
        if _CANCEL_RE.search(low) and "cancel_viewing" in available:
            ref = re.search(r"\bBK-\d{4}\b", user, re.I)
            return self._resp(
                calls=[
                    self._call("cancel_viewing", booking_ref=ref.group(0).upper() if ref else "")
                ]
            )
        if _BOOK_RE.search(low) and "propose_viewing" in available:
            target = explicit[0] if explicit else (focus or (shown[0] if shown else None))
            if not target:
                return self._resp(
                    "Which car would you like to view? Search first and I will book a slot for it."
                )
            dm = _DATE_WORD_RE.search(user)
            hour = _hour_from(user)
            return self._resp(
                calls=[
                    self._call(
                        "propose_viewing",
                        listing_id=target,
                        date_text=dm.group(0) if dm else "tomorrow",
                        hour=hour if hour is not None else 10,
                    )
                ]
            )
        if _COMPARE_RE.search(low) and "compare_listings" in available:
            ids = explicit or shown[:2]
            if focus and focus in shown and len(explicit) == 1:
                ids = [focus, explicit[0]]
            if len(ids) >= 2:
                return self._resp(calls=[self._call("compare_listings", listing_ids=ids[:4])])
        if _LIKE_RE.search(low) and "like_listing" in available and (explicit or focus):
            return self._resp(
                calls=[self._call("like_listing", listing_id=explicit[0] if explicit else focus)]
            )
        if _REMEMBER_RE.search(low) and "remember_preference" in available:
            args = _search_args(user)
            calls: list[ToolCall] = []
            if args.get("budget_text"):
                b = parse_budget(args["budget_text"])
                if b:
                    calls.append(
                        self._call(
                            "remember_preference",
                            kind="budget_max_aed" if b.mode == "cash" else "monthly_max_aed",
                            value=str(int(b.amount_aed)),
                        )
                    )
            for kind in ("make", "body_type", "color", "regional_spec"):
                if args.get(kind):
                    calls.append(self._call("remember_preference", kind=kind, value=args[kind]))
            if calls:
                return self._resp(calls=calls)
        if (
            resolved
            and _DETAIL_RE.search(low)
            and "get_listing" in available
            and not _BOOK_RE.search(low)
            and not _COMPARE_RE.search(low)
        ):
            return self._resp(calls=[self._call("get_listing", listing_id=resolved)])
        args = _search_args(user)
        searchy = any(
            k in args
            for k in (
                "make",
                "model",
                "body_type",
                "color",
                "budget_text",
                "year_min",
                "fuel_type",
                "is_brand_new",
                "regional_spec",
                "keywords",
                "sort",
                "is_dubizzle_managed",
            )
        )
        if (
            (explicit or focus)
            and _DETAIL_RE.search(low)
            and "get_listing" in available
            and not searchy
        ):
            return self._resp(
                calls=[self._call("get_listing", listing_id=explicit[0] if explicit else focus)]
            )
        if _MORE_RE.search(low) and "search_inventory" in available:
            return self._resp(calls=[self._call("search_inventory", offset=len(shown), limit=5)])
        if not args and focus and "get_listing" in available:
            return self._resp(calls=[self._call("get_listing", listing_id=focus)])
        if "search_inventory" not in available:
            return self._resp(
                "I can help with cars in our inventory, viewings, and your preferences. What would you like to know?"
            )
        args.setdefault("limit", 5)
        return self._resp(calls=[self._call("search_inventory", **args)])
