"""
Lead capture and qualification: one row per user, merged as facts arrive, judged in Python.

The model gathers budget and needs as they come up. Whether a lead is
qualified is a rule, never the model's opinion, and the reason is written
into the CSV so the file explains itself. Contact details arrive through the
form endpoint, not through chat, so they never enter a prompt.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime
from typing import Any

from dubizzle_assistant.config import Settings
from dubizzle_assistant.normalize import canonical_body_type, canonical_make, parse_budget
from dubizzle_assistant.services import tools as tool_registry
from dubizzle_assistant.services.context import TurnContext

CSV_COLUMNS = (
    "lead_id",
    "user_id",
    "name",
    "phone",
    "email",
    "budget_min_aed",
    "budget_max_aed",
    "budget_mode",
    "budget_original_text",
    "preferred_makes",
    "body_type",
    "min_year",
    "max_mileage_km",
    "spec",
    "timeline",
    "financing_interest",
    "trade_in",
    "trade_in_vehicle",
    "lead_type",
    "interested_listing_ids",
    "booked_listing_ids",
    "status",
    "qualification_reason",
    "session_id",
    "created_at",
    "updated_at",
)
LIST_FIELDS = ("preferred_makes", "interested_listing_ids", "booked_listing_ids")
TIMELINES = ("now", "1m", "3m", "browsing")
_CSV_LOCK = threading.Lock()
_PHONE_OK = re.compile(r"^\+9715\d{8}$")
_TIMELINE_WORDS = [
    (r"\b(today|asap|this week|right away|immediately|now)\b", "now"),
    (r"\b(this month|within a month|next month|few weeks|in a month|1 month|one month)\b", "1m"),
    (r"\b(2 months|3 months|three months|two months|this quarter|couple of months)\b", "3m"),
    (r"\b(just looking|browsing|no rush|someday|next year|not sure)\b", "browsing"),
]


def normalize_phone(text: str | None) -> str | None:
    """UAE mobiles in any of the dealers' own formats to +9715XXXXXXXX. Anything else is refused."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("971"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    candidate = "+971" + digits
    return candidate if _PHONE_OK.match(candidate) else None


def qualify(lead: dict[str, Any]) -> tuple[str, str]:
    if lead.get("booked_listing_ids"):
        return "qualified", "confirmed viewing booked"
    missing: list[str] = []
    if not (lead.get("phone") or lead.get("email")):
        missing.append("phone or email")
    if not (lead.get("budget_max_aed") or lead.get("budget_min_aed")):
        missing.append("budget")
    if not (
        lead.get("preferred_makes") or lead.get("body_type") or lead.get("interested_listing_ids")
    ):
        missing.append("make, body type or a car of interest")
    if lead.get("timeline") not in ("now", "1m", "3m"):
        missing.append("timeline within 3 months")
    if not missing:
        return "qualified", "contact, budget, need and timeline all present"
    filled = any(
        lead.get(k)
        for k in CSV_COLUMNS
        if k
        not in (
            "lead_id",
            "user_id",
            "name",
            "status",
            "qualification_reason",
            "session_id",
            "created_at",
            "updated_at",
        )
    )
    return ("partial" if filled else "new"), "missing: " + ", ".join(missing)


def get_lead(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM leads WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    data = json.loads(row["data_json"])
    data.update(
        {
            "lead_id": row["lead_id"],
            "user_id": user_id,
            "status": row["status"],
            "qualification_reason": row["qualification_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )
    return data


def upsert(
    conn: sqlite3.Connection,
    settings: Settings,
    user_id: str,
    session_id: str | None,
    updates: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Merge new facts into the lead: lists union, scalars overwrite, then re-qualify and export."""
    existing = get_lead(conn, user_id) or {}
    data = {
        k: existing.get(k)
        for k in CSV_COLUMNS
        if k
        not in ("lead_id", "user_id", "status", "qualification_reason", "created_at", "updated_at")
    }
    for k, v in updates.items():
        if k not in data or v in (None, "", []):
            continue
        if k in LIST_FIELDS:
            current = [x for x in (data.get(k) or "").split("|") if x]
            for item in v if isinstance(v, list) else str(v).split(","):
                item = str(item).strip()
                if item and item not in current:
                    current.append(item)
            data[k] = "|".join(current)
        else:
            data[k] = v
    if session_id:
        data["session_id"] = session_id
    if not data.get("name"):
        row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
        data["name"] = row["name"] if row else None
    status, reason = qualify(data)
    lead_id = existing.get("lead_id") or ("L-" + secrets.token_hex(3).upper())
    created = existing.get("created_at") or now.isoformat(timespec="seconds")
    with conn:
        conn.execute(
            "INSERT INTO leads (lead_id, user_id, data_json, status, qualification_reason, created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET data_json = excluded.data_json, status = excluded.status, "
            "qualification_reason = excluded.qualification_reason, updated_at = excluded.updated_at",
            (
                lead_id,
                user_id,
                json.dumps(data, ensure_ascii=False),
                status,
                reason,
                created,
                now.isoformat(timespec="seconds"),
            ),
        )
    export_csv(conn, settings.leads_csv)
    return {
        **data,
        "lead_id": lead_id,
        "user_id": user_id,
        "status": status,
        "qualification_reason": reason,
        "created_at": created,
        "updated_at": now.isoformat(timespec="seconds"),
    }


def export_csv(conn: sqlite3.Connection, path: Any) -> None:
    """Rewrite the whole file atomically. utf-8-sig so Excel shows Arabic names, newline='' for Windows."""
    rows = []
    for r in conn.execute("SELECT * FROM leads ORDER BY created_at"):
        data = json.loads(r["data_json"])
        data.update(
            {
                "lead_id": r["lead_id"],
                "user_id": r["user_id"],
                "status": r["status"],
                "qualification_reason": r["qualification_reason"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
        rows.append(data)
    with _CSV_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(
                f, fieldnames=CSV_COLUMNS, extrasaction="ignore", quoting=csv.QUOTE_ALL
            )
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)


def all_leads(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        lead
        for r in conn.execute("SELECT user_id FROM leads ORDER BY created_at")
        if (lead := get_lead(conn, r["user_id"]))
    ]


def set_contact(
    conn: sqlite3.Connection,
    settings: Settings,
    user_id: str,
    now: datetime,
    *,
    name: str | None,
    phone: str | None,
    email: str | None,
) -> dict[str, Any]:
    """Contact details from the form. Phone is normalised or refused, never stored as typed."""
    updates: dict[str, Any] = {}
    problems: list[str] = []
    if name:
        updates["name"] = name.strip()[:80]
    if phone:
        norm = normalize_phone(phone)
        if norm:
            updates["phone"] = norm
        else:
            problems.append("phone must be a UAE mobile, for example 050 123 4567")
    if email:
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
            updates["email"] = email.strip().lower()
        else:
            problems.append("email does not look valid")
    lead = upsert(conn, settings, user_id, None, updates, now)
    return {**lead, "problems": problems}


def prompt_block(conn: sqlite3.Connection, user_id: str) -> str | None:
    lead = get_lead(conn, user_id)
    if not lead:
        return None
    parts: list[str] = []
    if lead.get("budget_max_aed"):
        parts.append(
            f"budget up to AED {int(lead['budget_max_aed']):,}"
            + (" per month" if lead.get("budget_mode") == "monthly" else "")
        )
    elif lead.get("budget_min_aed"):
        parts.append(f"budget from AED {int(lead['budget_min_aed']):,}")
    for k in ("preferred_makes", "body_type", "spec", "timeline", "lead_type"):
        if lead.get(k):
            parts.append(f"{k.replace('_', ' ')}: {lead[k]}")
    if lead.get("min_year"):
        parts.append(f"year from {lead['min_year']}")
    if lead.get("interested_listing_ids"):
        parts.append(f"interested in {lead['interested_listing_ids'].replace('|', ', ')}")
    known = "; ".join(parts) if parts else "nothing recorded yet"
    contact = (
        "contact details on file"
        if (lead.get("phone") or lead.get("email"))
        else "no contact details yet (collected via the form, not chat)"
    )
    return f"{known}. {contact}. Status: {lead['status']} ({lead['qualification_reason']}). Ask at most one qualifying question per turn."


def note_booking(ctx: TurnContext, listing_id: str) -> None:
    lead = upsert(
        ctx.conn,
        ctx.settings,
        ctx.user_id,
        ctx.session_id,
        {
            "booked_listing_ids": [listing_id],
            "interested_listing_ids": [listing_id],
            "timeline": "now",
        },
        ctx.now,
    )
    ctx.note_write("leads", "confirm_viewing", status=lead["status"])


def _timeline_from(text: str) -> str | None:
    low = text.lower()
    for rx, value in _TIMELINE_WORDS:
        if re.search(rx, low):
            return value
    return None


def _update_lead(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if args.get("budget_text"):
        money = parse_budget(str(args["budget_text"]))
        if money:
            updates["budget_original_text"] = str(args["budget_text"])[:60]
            updates["budget_mode"] = money.mode
            updates["budget_max_aed"] = int(money.amount_aed)
    for k in ("budget_min_aed", "budget_max_aed", "min_year", "max_mileage_km"):
        if args.get(k) not in (None, "", 0):
            with contextlib.suppress(TypeError, ValueError):
                updates[k] = int(float(args[k]))
    if args.get("budget_mode") in ("cash", "monthly"):
        updates["budget_mode"] = args["budget_mode"]
    if args.get("preferred_makes"):
        makes = [canonical_make(m)[0] for m in str(args["preferred_makes"]).split(",") if m.strip()]
        updates["preferred_makes"] = [m for m in makes if m]
    if args.get("body_type"):
        updates["body_type"] = (
            canonical_body_type(str(args["body_type"])) or str(args["body_type"]).lower()
        )
    for k in ("spec", "trade_in_vehicle"):
        if args.get(k):
            updates[k] = str(args[k]).strip().lower()[:60]
    tl = args.get("timeline")
    if tl:
        updates["timeline"] = tl if tl in TIMELINES else (_timeline_from(str(tl)) or "browsing")
    for k in ("financing_interest", "trade_in"):
        if args.get(k) is not None:
            updates[k] = "yes" if bool(args[k]) else "no"
    if args.get("lead_type") in ("buy", "sell"):
        updates["lead_type"] = args["lead_type"]
    if ctx.focus_id:
        updates["interested_listing_ids"] = [ctx.focus_id]
    if not updates:
        return {"ok": False, "reason": "nothing to record"}
    lead = upsert(ctx.conn, ctx.settings, ctx.user_id, ctx.session_id, updates, ctx.now)
    ctx.note_write("leads", "update_lead", fields=sorted(k for k in updates), status=lead["status"])
    return {
        "ok": True,
        "recorded": {
            k: (v if not isinstance(v, list) else ", ".join(v)) for k, v in updates.items()
        },
        "status": lead["status"],
        "qualification_reason": lead["qualification_reason"],
        "message": "Noted: "
        + "; ".join(
            f"{k.replace('_', ' ')} {v if not isinstance(v, list) else ', '.join(v)}"
            for k, v in updates.items()
        )
        + ".",
    }


tool_registry.register(
    {
        "name": "update_lead",
        "description": "Record what the user has said about budget and needs, as it comes up. Never ask for name or phone here; those go through the form.",
        "parameters": {
            "type": "object",
            "properties": {
                "budget_text": {
                    "type": "string",
                    "description": "Budget phrase verbatim, e.g. 'around 150k', '$20k', 'under 2000 a month'",
                },
                "budget_min_aed": {"type": "integer"},
                "budget_max_aed": {"type": "integer"},
                "budget_mode": {"type": "string", "enum": ["cash", "monthly"]},
                "preferred_makes": {"type": "string", "description": "Comma separated makes"},
                "body_type": {"type": "string"},
                "min_year": {"type": "integer"},
                "max_mileage_km": {"type": "integer"},
                "spec": {"type": "string", "description": "gcc, us, japan, euro, any"},
                "timeline": {
                    "type": "string",
                    "description": "now, 1m, 3m, browsing, or the user's words",
                },
                "financing_interest": {"type": "boolean"},
                "trade_in": {"type": "boolean"},
                "trade_in_vehicle": {"type": "string"},
                "lead_type": {"type": "string", "enum": ["buy", "sell"]},
            },
        },
    },
    _update_lead,
)
