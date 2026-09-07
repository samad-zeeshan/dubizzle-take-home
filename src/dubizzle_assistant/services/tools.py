"""
The tools the model can call: hand-written flat schemas and the handlers behind them.

Schemas use only type, properties, required, enum, and description. No nested
objects, no unions, nothing Pydantic would emit that Gemini rejects. Booking and
lead tools register themselves from their own modules.
"""

from __future__ import annotations

import contextlib
import importlib
from collections.abc import Callable
from typing import Any

from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services import memory
from dubizzle_assistant.services.context import TurnContext
from dubizzle_assistant.services.explain import filters_from_args

Handler = Callable[[TurnContext, dict[str, Any]], dict[str, Any]]

_SCHEMAS: dict[str, dict[str, Any]] = {}
_HANDLERS: dict[str, Handler] = {}


def register(schema: dict[str, Any], handler: Handler) -> None:
    name = schema["name"]
    _SCHEMAS[name] = {"type": "function", "function": schema}
    _HANDLERS[name] = handler


def tool_schemas() -> list[dict[str, Any]]:
    _ensure_loaded()
    return list(_SCHEMAS.values())


def run_tool(ctx: TurnContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    _ensure_loaded()
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        return handler(ctx, args or {})
    except Exception as e:  # noqa: BLE001
        # A tool bug must surface as a readable tool result, not a 500 mid-conversation.
        return {"error": f"{name} failed: {type(e).__name__}: {e}"}


def _ensure_loaded() -> None:
    if "propose_viewing" not in _HANDLERS:
        for name in ("booking", "leads"):
            with contextlib.suppress(ImportError):
                importlib.import_module(f"dubizzle_assistant.services.{name}")


_MAKES_HINT = (
    "Dataset makes are lowercase: mercedes-benz, bmw, toyota, nissan, land rover (holds every Range Rover), "
    "rolls-royce, bentley, audi, ford, chevrolet, dodge, ferrari, lamborghini, porsche, tesla, byd, xiaomi, "
    "haval, gwm, jac, kaiyi, bestune, chery, tova, and others. Aliases like Merc, Range Rover, Chevy are accepted."
)

SEARCH_SCHEMA = {
    "name": "search_inventory",
    "description": "Search the car inventory with structured filters and optional free text. Unknown prices pass softly and are labelled. Returns compact cards with ids; refer to cars only by these ids.",
    "parameters": {
        "type": "object",
        "properties": {
            "make": {"type": "string", "description": _MAKES_HINT},
            "model": {
                "type": "string",
                "description": "Model name as the user said it, e.g. 'range rover velar', 'c300', 'patrol'",
            },
            "year_min": {"type": "integer"},
            "year_max": {"type": "integer"},
            "price_max_aed": {"type": "integer", "description": "Cash budget ceiling in AED"},
            "price_min_aed": {"type": "integer"},
            "monthly_max_aed": {
                "type": "integer",
                "description": "Instalment ceiling in AED per month",
            },
            "budget_text": {
                "type": "string",
                "description": "The user's budget phrase verbatim, e.g. '$20k' or 'under 2000 a month'. The server converts and records the step.",
            },
            "body_type": {
                "type": "string",
                "enum": [
                    "suv",
                    "sedan",
                    "coupe",
                    "hatchback",
                    "pickup",
                    "van",
                    "convertible",
                    "wagon",
                    "truck_chassis",
                ],
            },
            "color": {"type": "string", "description": "Exterior colour word in English"},
            "regional_spec": {
                "type": "string",
                "enum": ["gcc", "us", "japan", "euro", "korean", "canadian"],
            },
            "fuel_type": {"type": "string", "enum": ["petrol", "diesel", "electric", "hybrid"]},
            "has_warranty": {"type": "boolean"},
            "mileage_max_km": {"type": "integer"},
            "is_brand_new": {"type": "boolean"},
            "is_dubizzle_managed": {
                "type": "boolean",
                "description": "Only dubizzle inspected listings",
            },
            "exclude_export_only": {"type": "boolean"},
            "keywords": {
                "type": "string",
                "description": "Features or free text, e.g. 'panoramic roof 7 seats'",
            },
            "sort": {
                "type": "string",
                "enum": ["price_asc", "price_desc", "year_desc", "year_asc", "mileage_asc"],
            },
            "limit": {"type": "integer", "description": "1 to 10, default 5"},
            "offset": {"type": "integer", "description": "For 'show more'"},
        },
    },
}


def _compact(card: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id",
        "year",
        "make",
        "model",
        "trim",
        "price_aed",
        "monthly_aed",
        "mileage_km",
        "exterior_color",
        "body_type",
        "regional_spec",
        "fuel_type",
        "has_warranty",
        "service_contract",
        "is_dubizzle_managed",
        "is_export_only",
        "is_brand_new",
        "english_summary",
    )
    return {k: card.get(k) for k in keep}


def _search(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    filters, steps = filters_from_args(args)
    limit = max(1, min(int(args.get("limit") or 5), 10))
    offset = max(0, int(args.get("offset") or 0))
    result = inv.search(
        ctx.conn,
        filters,
        mode=ctx.settings.retrieval_mode,
        limit=limit,
        offset=offset,
        relax=not ctx.settings.ablate_relaxation,
        embedder=ctx.embedder,
        normalization=steps,
    )
    ids = [c["id"] for c in result.results]
    on_screen = {c["id"] for c in ctx.shown} | {c["id"] for c in ctx.new_cards}
    # A search that finds only the car already under discussion is usually a hunt for alternatives
    # run on its own make and model. Showing the same card again would answer the wrong question,
    # but when the customer plainly asked to see stock an empty grid is the worse answer.
    only_focus = (
        offset == 0
        and ids == [ctx.focus_id]
        and ctx.focus_id in on_screen
        and not ctx.stock_request
    )
    if not only_focus:
        ctx.new_cards.extend(result.results)
    memory.record_search(
        ctx.conn,
        ctx.user_id,
        ctx.session_id,
        ctx.raw_message,
        result.applied_filters,
        result.total_matches,
        ctx.now,
    )
    ctx.note_write(
        "search_history",
        "search_inventory",
        query=ctx.raw_message[:80],
        results=result.total_matches,
    )
    if result.total_matches > result.shown + offset:
        ctx.suggested_actions.append("Show more")
    for c in result.results[:2]:
        ctx.suggested_actions.append(f"Tell me more about {c['id']}")
    payload = result.as_dict()
    payload["results"] = [_compact(c) for c in result.results]
    if only_focus:
        payload["note"] = (
            f"{ctx.focus_id} is the car already on screen and under discussion. If the user wants "
            "other cars like it, call similar_listings with its id."
        )
    # The executed SQL and stage counts go to the trace, not to the model.
    payload["_trace"] = {
        "executed": payload.pop("executed"),
        "stage_counts": payload["stage_counts"],
        "relaxed": payload["relaxed_filters"],
    }
    return payload


# Condition is what buyers actually ask about, and none of it is a search filter, so it
# rides on the detail call with the seller's own sentence attached as evidence.
_CONDITION_FIELDS = (
    "accident_free",
    "original_paint",
    "owners",
    "service_history",
    "new_tyres",
    "no_faults",
    "no_flood",
    "negotiable",
    "trade_in_accepted",
    "has_carplay",
    "has_leather",
    "driver_assist",
)
_INFERRED_SOURCES = ("llm", "inferred", "derived")
_INFERRED_NOTE = "from what this model is generally known for, the listing does not state it"


def _sourced(fields: dict[str, Any], name: str, value: Any) -> Any:
    """An inferred value travels with its source, so the reply can hedge instead of asserting."""
    if value is None:
        return None
    if (fields.get(name) or {}).get("source") not in _INFERRED_SOURCES:
        return value
    return {"value": value, "source": "inferred", "note": _INFERRED_NOTE}


def _conditions(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in _CONDITION_FIELDS:
        f = fields.get(name) or {}
        value = f.get("value")
        if value is None or value == [] or value == "":
            continue
        out[name] = {"value": value, "evidence": f.get("evidence")}
    return out


def _get(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    lid = str(args.get("listing_id") or "").upper()
    row = inv.get_listing(ctx.conn, lid)
    if row is None:
        return {"error": f"no listing {lid or '(missing id)'} in the inventory"}
    ctx.focus_id = row["id"]
    if row["id"] not in {c["id"] for c in ctx.shown} | {c["id"] for c in ctx.new_cards}:
        ctx.new_cards.append(inv.card(row))
    fields = row.get("fields", {})
    out = _compact(row)
    out.update(
        {
            "interior_color": row.get("interior_color"),
            "transmission": _sourced(fields, "transmission", row.get("transmission")),
            "fuel_type": _sourced(fields, "fuel_type", row.get("fuel_type")),
            "body_type": _sourced(fields, "body_type", row.get("body_type")),
            "seats": row.get("seats") if (row.get("seats") or 0) > 0 else None,
            "warranty_text": row.get("warranty_text"),
            "price_vat_status": row.get("price_vat_status"),
            "down_payment_pct": row.get("down_payment_pct"),
            "language": row.get("language"),
            "description_quality": row.get("description_quality"),
            # The seller's headline carries facts that appear nowhere else: the engine on one
            # listing, the spec on another, the instalment on a third.
            "title": row.get("title"),
            # The whole cleaned ad, because condition sits anywhere in it and a fixed cut lost
            # the tyres on one listing and CarPlay on another. The longest here is under 2000 chars.
            # With the sanitizer ablated the model sees the seller's raw text, phones and all. That is the demo.
            "listing_text": (
                inv.raw_text(ctx.conn, row["id"])
                if ctx.settings.ablate_sanitizer
                else (row.get("description_clean") or "")
            ),
            **_conditions(fields),
            "evidence": {
                k: fields[k].get("evidence")
                for k in (
                    "price_aed",
                    "monthly_aed",
                    "mileage_km",
                    "exterior_color",
                    "has_warranty",
                )
                if k in fields and fields[k].get("evidence")
            },
            "note": "null means the listing does not state it",
        }
    )
    ctx.suggested_actions.append(f"Book a viewing for {row['id']}")
    ctx.suggested_actions.append(f"Similar cars to {row['id']}")
    return out


MAX_COMPARE = 4


def _compare(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    asked = [str(i).upper() for i in (args.get("listing_ids") or []) if i]
    if len(asked) < 2:
        return {"error": "compare needs two to four listing ids"}
    ids = asked[:MAX_COMPARE]
    out = inv.compare(ctx.conn, ids)
    missing = [i for i in ids if i not in out["ids"]]
    if missing:
        return {"error": f"unknown listing ids: {', '.join(missing)}"}
    # The slice used to happen before missing was computed, so a dropped id could never appear
    # anywhere in the result. Asked for six, the model saw four and told the customer that the
    # other two were not in the inventory.
    dropped = asked[MAX_COMPARE:]
    if dropped:
        out["not_compared"] = dropped
        out["note"] = (
            f"Only the first {MAX_COMPARE} were compared. {', '.join(dropped)} are in the "
            "inventory but were not included. Call get_listing for each, or compare again."
        )
    for c in out["cards"]:
        if c["id"] not in {x["id"] for x in ctx.shown} | {x["id"] for x in ctx.new_cards}:
            ctx.new_cards.append(c)
    out["cards"] = [_compact(c) for c in out["cards"]]
    return out


def _similar(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    lid = str(args.get("listing_id") or ctx.focus_id or "").upper()
    limit = max(1, min(int(args.get("limit") or 5), 10))
    out = inv.similar(ctx.conn, lid, limit=limit)
    if out is None:
        return {"error": f"no listing {lid or '(missing id)'} in the inventory"}
    ctx.focus_id = lid
    ctx.new_cards.extend(out["results"])
    for c in out["results"][:2]:
        ctx.suggested_actions.append(f"Tell me more about {c['id']}")
    return {
        "anchor": _compact(out["anchor"]),
        "criteria": out["criteria"],
        "total_matches": out["total_matches"],
        "results": [
            {**_compact(c), "vs_anchor": c["explain"]["vs_anchor"]} for c in out["results"]
        ],
        "_trace": {
            "executed": out["executed"],
            "stage_counts": {"similar": out["total_matches"]},
            "relaxed": [],
        },
    }


def _like(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    lid = str(args.get("listing_id") or ctx.focus_id or "").upper()
    cards = inv.get_cards(ctx.conn, [lid]) if lid else []
    if not cards:
        return {"error": f"no listing {lid or '(missing id)'}"}
    res = memory.like(ctx.conn, ctx.user_id, cards[0], ctx.session_id, ctx.now)
    ctx.note_write("liked_cars", "like_listing", listing_id=lid)
    ctx.focus_id = lid
    return {
        **res,
        "message": f"Saved {cards[0]['year']} {cards[0]['make']} {cards[0]['model']} ({lid}) to your liked cars.",
    }


def _remember(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    res = memory.remember(
        ctx.conn,
        ctx.user_id,
        str(args.get("kind", "")),
        str(args.get("value", "")),
        "stated",
        ctx.session_id,
        ctx.now,
    )
    if res.get("ok"):
        ctx.note_write(
            "preference_events", "remember_preference", kind=res["kind"], value=res["value"]
        )
        res["message"] = f"Noted: {res['kind'].replace('_', ' ')} is {res['value']}."
    return res


def _identify(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"error": "a name is needed"}
    # A typed name is spoofable, so it may put a name to a guest session but must never move an
    # identified one onto someone else's account: that would hand this chat their preferences,
    # likes and bookings. Switching accounts goes through the account panel, which mints a fresh
    # session. Read the session's own row rather than trusting ctx, and never look the claimed
    # name up, so nothing about the other person can reach the reply.
    row = memory.get_session(ctx.conn, ctx.session_id)
    current = memory.get_user(ctx.conn, row["user_id"]) if row else None
    if current:
        held = current["name_key"] or memory.name_key(current["name"] or "")
        if held not in ("", "guest") and held != memory.name_key(name):
            return {
                "error": "this chat is already signed in",
                "signed_in_as": current["name"],
                "message": (
                    f"This chat is signed in as {current['name']}. Changing who is signed in "
                    "happens in the account panel, not in chat."
                ),
            }
    info = memory.identify_user(ctx.conn, ctx.now, name=name)
    with ctx.conn:
        ctx.conn.execute(
            "UPDATE sessions SET user_id = ? WHERE session_id = ?",
            (info["user_id"], ctx.session_id),
        )
    ctx.user_id, ctx.user_name = info["user_id"], info["name"]
    ctx.note_write("users", "identify_user", user_id=info["user_id"], returning=info["returning"])
    prof = memory.profile(ctx.conn, info["user_id"], ctx.now)
    return {
        **info,
        "message": f"Welcome back, {info['name']}."
        if info["returning"]
        else f"Nice to meet you, {info['name']}.",
        "recall": memory.recall_block(prof),
    }


register(SEARCH_SCHEMA, _search)
register(
    {
        "name": "get_listing",
        "description": "Full details for one listing by id, including the seller's cleaned text and which snippet each key figure came from. Use before answering any attribute question.",
        "parameters": {
            "type": "object",
            "properties": {"listing_id": {"type": "string", "description": "e.g. C-003 or R-078"}},
            "required": ["listing_id"],
        },
    },
    _get,
)
register(
    {
        "name": "compare_listings",
        "description": "Side by side comparison of two to four listings.",
        "parameters": {
            "type": "object",
            "properties": {"listing_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["listing_ids"],
        },
    },
    _compare,
)
register(
    {
        "name": "similar_listings",
        "description": "Alternatives to one listing: other cars with the same body type or a price within 30% of it, ranked by how close they sit on body type, price, year, and make. Never returns the listing itself. Use for 'similar cars', 'alternatives', 'anything else like it'.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "string",
                    "description": "The car to find alternatives to, e.g. R-085",
                },
                "limit": {"type": "integer", "description": "1 to 10, default 5"},
            },
            "required": ["listing_id"],
        },
    },
    _similar,
)
register(
    {
        "name": "like_listing",
        "description": "Save a car to the user's liked list so it can be recalled in future sessions.",
        "parameters": {
            "type": "object",
            "properties": {"listing_id": {"type": "string"}},
            "required": ["listing_id"],
        },
    },
    _like,
)
register(
    {
        "name": "remember_preference",
        "description": "Store one typed preference the user stated. Budgets in AED.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": sorted(memory.PREFERENCE_KINDS)},
                "value": {"type": "string"},
            },
            "required": ["kind", "value"],
        },
    },
    _remember,
)
register(
    {
        "name": "identify_user",
        "description": "Call when the user gives their name ('Hi, I'm Sara'). Finds or creates their profile and returns what is remembered.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    _identify,
)
