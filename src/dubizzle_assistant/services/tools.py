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
    # The executed SQL and stage counts go to the trace, not to the model.
    payload["_trace"] = {
        "executed": payload.pop("executed"),
        "stage_counts": payload["stage_counts"],
        "relaxed": payload["relaxed_filters"],
    }
    return payload


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
            "transmission": row.get("transmission"),
            "seats": row.get("seats"),
            "warranty_text": row.get("warranty_text"),
            "price_vat_status": row.get("price_vat_status"),
            "down_payment_pct": row.get("down_payment_pct"),
            "language": row.get("language"),
            "description_quality": row.get("description_quality"),
            # With the sanitizer ablated the model sees the seller's raw text, phones and all. That is the demo.
            "listing_text": (
                inv.raw_text(ctx.conn, row["id"])
                if ctx.settings.ablate_sanitizer
                else (row.get("description_clean") or "")
            )[:1200],
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
    return out


def _compare(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    ids = [str(i).upper() for i in (args.get("listing_ids") or []) if i][:4]
    if len(ids) < 2:
        return {"error": "compare needs two to four listing ids"}
    out = inv.compare(ctx.conn, ids)
    missing = [i for i in ids if i not in out["ids"]]
    if missing:
        return {"error": f"unknown listing ids: {', '.join(missing)}"}
    for c in out["cards"]:
        if c["id"] not in {x["id"] for x in ctx.shown} | {x["id"] for x in ctx.new_cards}:
            ctx.new_cards.append(c)
    out["cards"] = [_compact(c) for c in out["cards"]]
    return out


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
