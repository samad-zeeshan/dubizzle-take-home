"""
Viewing slots: Monday to Saturday, hourly starts 08:00 to 19:00, Asia/Dubai, validated in code.

Dealer opening hours inside listing text include Sundays and late nights, so
they never reach this module. Every rejection carries a reason and the next
three free slots, and confirming is a two-step state machine: the model
proposes, the server holds it, and only a later turn can confirm.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import dateparser

from dubizzle_assistant.config import DUBAI, Settings
from dubizzle_assistant.normalize import normalize_digits
from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services import memory
from dubizzle_assistant.services import tools as tool_registry
from dubizzle_assistant.services.context import TurnContext

OPEN_HOUR = 8
LAST_START_HOUR = 19  # the 19:00 slot ends at 20:00
HORIZON_DAYS = 30
MAX_OPEN_PER_USER = 3
PENDING_TTL_MINUTES = 10
_CSV_LOCK = threading.Lock()
CSV_COLUMNS = (
    "ref",
    "user_id",
    "listing_id",
    "slot_start",
    "slot_end",
    "status",
    "created_at",
    "cancelled_at",
)

_DATEPARSER_SETTINGS: dict[str, Any] = {
    "PREFER_DATES_FROM": "future",
    "TIMEZONE": "Asia/Dubai",
    "RETURN_AS_TIMEZONE_AWARE": True,
    "PREFER_DAY_OF_MONTH": "first",
}


_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
    "الاثنين": 0,
    "الإثنين": 0,
    "الثلاثاء": 1,
    "الأربعاء": 2,
    "الاربعاء": 2,
    "الخميس": 3,
    "الجمعة": 4,
    "الجمعه": 4,
    "السبت": 5,
    "الأحد": 6,
    "الاحد": 6,
}
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_TIME_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b|\b(\d{1,2}):(\d{2})\b|\bat\s+(\d{1,2})\b",
    re.I,
)


def parse_day_phrase(text: str, now: datetime) -> tuple[datetime | None, str | None]:
    """Deterministic reading of the common phrases. Returns (date at midnight, rule) or (None, None)."""
    low = normalize_digits(text.lower().strip())
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\b(today|tonight|this afternoon|this evening|now)\b|اليوم", low):
        return today, "today"
    if re.search(r"day after tomorrow|بعد غد", low):
        return today + timedelta(days=2), "day after tomorrow"
    if re.search(r"\btomorrow\b|\btmrw\b|غدا|غداً|بكرة|بكره", low):
        return today + timedelta(days=1), "tomorrow"
    m = re.search(r"\bin\s+(\d{1,2})\s+days?\b", low)
    if m:
        return today + timedelta(days=int(m.group(1))), f"in {m.group(1)} days"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if m:
        return today.replace(
            year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3))
        ), "iso date"
    m = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
        low,
    ) or re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})(?:st|nd|rd|th)?\b", low
    )
    if m:
        a, b = m.group(1), m.group(2)
        day, month = (int(a), _MONTHS[b]) if a.isdigit() else (int(b), _MONTHS[a])
        candidate = today.replace(month=month, day=day)
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)
        return candidate, "day and month"
    for word, wd in _WEEKDAYS.items():
        if re.search(rf"(?<![\w؀-ۿ]){re.escape(word)}(?![\w؀-ۿ])", low):
            ahead = (wd - today.weekday()) % 7
            if ahead == 0:
                ahead = 7 if re.search(r"\bnext\b|القادم|الجاي", low) else 0
            return today + timedelta(days=ahead), f"weekday {word}"
    if re.search(r"\bnext week\b|الأسبوع القادم", low):
        return today + timedelta(days=(7 - today.weekday()) % 7 or 7), "next week"
    return None, None


def hour_from_text(text: str) -> int | None:
    m = _TIME_RE.search(normalize_digits(text))
    if not m:
        return None
    if m.group(1):
        h = int(m.group(1)) % 12
        return h + 12 if m.group(3).lower().startswith("p") else h
    if m.group(4):
        return int(m.group(4))
    h = int(m.group(6))
    # "at 3" without am or pm on a car lot means the afternoon.
    return h + 12 if 1 <= h <= 7 else h


def slot_label(start: datetime) -> str:
    end = start + timedelta(hours=1)
    return f"{start.strftime('%A %d %b %Y')}, {start.strftime('%H:%M')} to {end.strftime('%H:%M')}"


def parse_slot(
    date_text: str | None, date_iso: str | None, hour: int | None, now: datetime
) -> tuple[datetime | None, list[str], str | None]:
    """Server-side date reading. Own rules first, dateparser second, the model's ISO guess last."""
    steps: list[str] = []
    day: datetime | None = None
    if date_text:
        day, rule = parse_day_phrase(date_text, now)
        if day is not None:
            steps.append(f"'{date_text}' -> {day.strftime('%A %Y-%m-%d')} ({rule})")
        else:
            settings = dict(_DATEPARSER_SETTINGS, RELATIVE_BASE=now.replace(tzinfo=None))
            try:
                parsed = dateparser.parse(date_text, settings=settings, languages=["en", "ar"])
            except Exception:  # noqa: BLE001
                parsed = None
            if parsed is not None:
                parsed = parsed.astimezone(DUBAI) if parsed.tzinfo else parsed.replace(tzinfo=DUBAI)
                day = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                steps.append(f"'{date_text}' -> {day.strftime('%A %Y-%m-%d')} (dateparser)")
                if hour is None and hour_from_text(date_text) is None and parsed.hour:
                    hour = parsed.hour
    model_day: datetime | None = None
    if date_iso:
        try:
            md = datetime.fromisoformat(date_iso)
            md = md.astimezone(DUBAI) if md.tzinfo else md.replace(tzinfo=DUBAI)
            model_day = md
        except ValueError:
            steps.append(f"model date_iso {date_iso!r} unreadable, ignored")
    if day is None and model_day is None:
        return (
            None,
            steps,
            "I could not work out which day you mean. Try 'Monday' or a date like 2026-09-07.",
        )
    if day is not None and model_day is not None and day.date() != model_day.date():
        steps.append(f"model said {model_day.date()}, text says {day.date()}, text wins")
    base = day if day is not None else model_day
    assert base is not None
    if hour is None:
        from_text = hour_from_text(date_text or "")
        if from_text is not None:
            hour = from_text
        elif model_day is not None and model_day.hour:
            hour = model_day.hour
        else:
            hour = 10
            steps.append("no time given, defaulted to 10:00")
    start = base.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    return start, steps, None


def validate_slot(
    conn: sqlite3.Connection, listing_id: str, start: datetime, now: datetime
) -> str | None:
    row = conn.execute(
        "SELECT id, is_export_only FROM listings WHERE id = ?", (listing_id,)
    ).fetchone()
    if row is None:
        return f"there is no listing {listing_id} in the inventory"
    if row["is_export_only"]:
        return "this vehicle is listed for export only and cannot be viewed or test driven here"
    if start.weekday() == 6:
        return "viewings are not available on Sundays; the schedule is Monday to Saturday"
    if start.minute != 0 or not OPEN_HOUR <= start.hour <= LAST_START_HOUR:
        return "viewings start on the hour between 08:00 and 19:00 Dubai time, the last one ending at 20:00"
    if start < now + timedelta(hours=1):
        return "that slot is in the past or too soon; viewings need at least an hour's notice"
    if start > now + timedelta(days=HORIZON_DAYS):
        return f"viewings can be booked up to {HORIZON_DAYS} days ahead"
    taken = conn.execute(
        "SELECT 1 FROM bookings WHERE listing_id = ? AND slot_start = ? AND status = 'confirmed'",
        (listing_id, start.isoformat(timespec="minutes")),
    ).fetchone()
    if taken:
        return "that slot is already taken for this car"
    return None


def next_free_slots(
    conn: sqlite3.Connection, listing_id: str, from_dt: datetime, now: datetime, n: int = 3
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    cursor = from_dt.replace(minute=0, second=0, microsecond=0)
    limit = now + timedelta(days=HORIZON_DAYS)
    while len(out) < n and cursor <= limit:
        cursor += timedelta(hours=1)
        if cursor.weekday() == 6 or not OPEN_HOUR <= cursor.hour <= LAST_START_HOUR:
            continue
        if validate_slot(conn, listing_id, cursor, now) is None:
            out.append({"start": cursor.isoformat(timespec="minutes"), "label": slot_label(cursor)})
    return out


def availability_grid(
    conn: sqlite3.Connection, listing_id: str, week_of: datetime, now: datetime
) -> dict[str, Any]:
    """Six days by twelve slots with a state each, so the rules are visible before anyone asks."""
    monday = (week_of - timedelta(days=week_of.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    taken = {
        r["slot_start"]
        for r in conn.execute(
            "SELECT slot_start FROM bookings WHERE listing_id = ? AND status = 'confirmed' AND slot_start BETWEEN ? AND ?",
            (
                listing_id,
                monday.isoformat(timespec="minutes"),
                (monday + timedelta(days=7)).isoformat(timespec="minutes"),
            ),
        )
    }
    days = []
    for d in range(7):
        day = monday + timedelta(days=d)
        slots = []
        for h in range(OPEN_HOUR, LAST_START_HOUR + 1):
            start = day.replace(hour=h)
            key = start.isoformat(timespec="minutes")
            if day.weekday() == 6:
                state = "closed"
            elif key in taken:
                state = "taken"
            elif start < now + timedelta(hours=1):
                state = "past"
            else:
                state = "free"
            slots.append({"start": key, "hour": h, "state": state})
        days.append({"date": day.date().isoformat(), "weekday": day.strftime("%A"), "slots": slots})
    return {
        "listing_id": listing_id,
        "week_start": monday.date().isoformat(),
        "days": days,
        "rule": "Monday to Saturday, 08:00 to 20:00 Asia/Dubai",
    }


def _next_ref(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM bookings WHERE ref = ?", (f"BK-{n:04d}",)).fetchone():
        n += 1
    return f"BK-{n:04d}"


def write_outbox(settings: Settings, ref: str, kind: str, body: str) -> str:
    # Stands in for the email or SMS a real system would send. Gitignored.
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    path = settings.outbox_dir / f"{ref}-{kind}.txt"
    path.write_text(body, encoding="utf-8", newline="\n")
    return str(path)


def export_csv(conn: sqlite3.Connection, path: Any) -> None:
    rows = [dict(r) for r in conn.execute("SELECT * FROM bookings ORDER BY id")]
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


def list_bookings(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM bookings WHERE user_id = ? ORDER BY slot_start", (user_id,)
        )
    ]


def open_booking_cap(conn: sqlite3.Connection, user_id: str, now: datetime) -> str | None:
    """The cap is checked when a slot is proposed as well, so the read-back never promises a fourth viewing."""
    open_count = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE user_id = ? AND status = 'confirmed' AND slot_start >= ?",
        (user_id, now.isoformat(timespec="minutes")),
    ).fetchone()[0]
    if open_count >= MAX_OPEN_PER_USER:
        return f"you already have {open_count} upcoming viewings; cancel one before booking another"
    return None


def create_booking(
    conn: sqlite3.Connection,
    settings: Settings,
    user_id: str,
    listing_id: str,
    start: datetime,
    now: datetime,
) -> dict[str, Any]:
    """Insert or explain why not. The partial unique indexes are the last line against double booking."""
    error = validate_slot(conn, listing_id, start, now)
    if error:
        return {
            "ok": False,
            "reason": error,
            "alternatives": next_free_slots(conn, listing_id, max(start, now), now),
        }
    cap = open_booking_cap(conn, user_id, now)
    if cap:
        return {"ok": False, "reason": cap, "alternatives": []}
    end = start + timedelta(hours=1)
    ref = _next_ref(conn)
    for attempt in range(2):
        try:
            with conn:
                conn.execute(
                    "INSERT INTO bookings (ref, user_id, listing_id, slot_start, slot_end, status, created_at) VALUES (?,?,?,?,?,'confirmed',?)",
                    (
                        ref,
                        user_id,
                        listing_id,
                        start.isoformat(timespec="minutes"),
                        end.isoformat(timespec="minutes"),
                        now.isoformat(timespec="seconds"),
                    ),
                )
            break
        except sqlite3.IntegrityError as e:
            # The ref is COUNT(*)+1 read outside this transaction, so two writers can pick the
            # same one. That is a clash in our own numbering, and telling the customer their
            # slot was taken when it was not sends them away from a free appointment.
            if attempt or "bookings.ref" not in str(e):
                return {
                    "ok": False,
                    "reason": "that slot was just taken, or you already hold a viewing at that hour",
                    "alternatives": next_free_slots(conn, listing_id, start, now),
                }
            n = int(ref.removeprefix("BK-")) + 1
            while conn.execute("SELECT 1 FROM bookings WHERE ref = ?", (f"BK-{n:04d}",)).fetchone():
                n += 1
            ref = f"BK-{n:04d}"
    cards = inv.get_cards(conn, [listing_id])
    car = cards[0] if cards else {"id": listing_id, "year": "", "make": "", "model": ""}
    label = slot_label(start)
    managed = bool(car.get("is_dubizzle_managed"))
    kind = (
        "viewing and test drive (dubizzle inspected, RTA transfer handled)"
        if managed
        else "viewing request"
    )
    body = (
        f"Booking {ref}\n{kind}\n{car['year']} {str(car['make']).title()} {str(car['model']).title()} ({listing_id})\n{label}\n"
        f"Arranged through dubizzle. Reply to this message to reschedule.\n"
    )
    outbox = write_outbox(settings, ref, "confirmation", body)
    export_csv(conn, settings.bookings_csv)
    return {
        "ok": True,
        "ref": ref,
        "listing_id": listing_id,
        "slot_start": start.isoformat(timespec="minutes"),
        "slot_label": label,
        "kind": kind,
        "message": f"Booked: {kind} for the {car['year']} {str(car['make']).title()} {str(car['model']).title()}, {label}. Reference {ref}.",
        # The file name only: an absolute path differs between machines and would break cassette replay.
        "outbox_file": Path(outbox).name,
    }


def cancel_booking(
    conn: sqlite3.Connection, settings: Settings, user_id: str, ref: str, now: datetime
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM bookings WHERE ref = ? AND user_id = ?", (ref.upper(), user_id)
    ).fetchone()
    if row is None:
        return {"ok": False, "reason": f"no booking {ref} on this account"}
    if row["status"] != "confirmed":
        return {"ok": False, "reason": f"booking {ref} is already {row['status']}"}
    with conn:
        conn.execute(
            "UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (now.isoformat(timespec="seconds"), row["id"]),
        )
    write_outbox(
        settings,
        row["ref"],
        "cancellation",
        f"Booking {row['ref']} cancelled.\n{row['listing_id']} at {row['slot_start']}\n",
    )
    export_csv(conn, settings.bookings_csv)
    return {
        "ok": True,
        "ref": row["ref"],
        "listing_id": row["listing_id"],
        "message": f"Cancelled booking {row['ref']} for {row['listing_id']}.",
    }


# tools -------------------------------------------------------------------------


def _availability(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    lid = str(args.get("listing_id") or ctx.focus_id or "").upper()
    if not lid:
        return {"error": "which car? give a listing id"}
    when = ctx.now
    if args.get("date_text"):
        parsed, _, _ = parse_slot(str(args["date_text"]), None, 10, ctx.now)
        if parsed is not None:
            when = parsed
    grid = availability_grid(ctx.conn, lid, when, ctx.now)
    free = [s for d in grid["days"] for s in d["slots"] if s["state"] == "free"]
    return {
        "listing_id": lid,
        "week_start": grid["week_start"],
        "rule": grid["rule"],
        "free_slots": len(free),
        "next_free": next_free_slots(ctx.conn, lid, when, ctx.now, n=5),
        "days": [
            {
                "date": d["date"],
                "weekday": d["weekday"],
                "free_hours": [s["hour"] for s in d["slots"] if s["state"] == "free"],
            }
            for d in grid["days"]
        ],
    }


def _propose(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    lid = str(args.get("listing_id") or ctx.focus_id or "").upper()
    if not lid:
        return {"ok": False, "reason": "which car would you like to view? Give the listing id."}
    hour = args.get("hour")
    try:
        hour = int(hour) if hour is not None else None
    except (TypeError, ValueError):
        hour = None
    start, steps, err = parse_slot(args.get("date_text"), args.get("date_iso"), hour, ctx.now)
    if err or start is None:
        return {"ok": False, "reason": err or "could not read the date", "date_steps": steps}
    error = validate_slot(ctx.conn, lid, start, ctx.now) or open_booking_cap(
        ctx.conn, ctx.user_id, ctx.now
    )
    if error:
        alts = next_free_slots(ctx.conn, lid, max(start, ctx.now), ctx.now)
        return {
            "ok": False,
            "listing_id": lid,
            "reason": error,
            "requested": slot_label(start),
            "date_steps": steps,
            "alternatives": alts,
            "message": f"I can't book {slot_label(start)}: {error}."
            + (f" The next free slots are {', '.join(a['label'] for a in alts)}." if alts else ""),
        }
    cards = inv.get_cards(ctx.conn, [lid])
    car = cards[0]
    label = slot_label(start)
    ctx.pending_booking = {
        "listing_id": lid,
        "slot_start": start.isoformat(timespec="minutes"),
        "slot_label": label,
        "turn": ctx.turn,
        "created_at": ctx.now.isoformat(timespec="seconds"),
    }
    ctx.focus_id = lid
    ctx.suggested_actions.insert(0, "Confirm the viewing")
    readback = (
        f"To confirm: a viewing of the {car['year']} {str(car['make']).title()} {str(car['model']).title()} on {label}"
        f"{' (dubizzle inspected, test drive included)' if car.get('is_dubizzle_managed') else ''}. Shall I book it?"
    )
    return {
        "ok": True,
        "pending": True,
        "listing_id": lid,
        "slot_start": ctx.pending_booking["slot_start"],
        "slot_label": label,
        "date_steps": steps,
        "readback": readback,
        "note": "Nothing is booked yet. Call confirm_viewing after the user agrees in their next message.",
    }


def _confirm(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    pb = ctx.pending_booking
    if not pb:
        return {"ok": False, "reason": "there is no proposed viewing to confirm; propose one first"}
    if pb.get("turn") == ctx.turn:
        return {
            "ok": False,
            "reason": "the proposal and the confirmation cannot happen in the same message; read the slot back and wait for the user",
        }
    created = datetime.fromisoformat(pb["created_at"])
    if ctx.now - created > timedelta(minutes=PENDING_TTL_MINUTES):
        ctx.pending_booking = None
        return {"ok": False, "reason": "that proposal expired; propose the slot again"}
    start = datetime.fromisoformat(pb["slot_start"])
    result = create_booking(ctx.conn, ctx.settings, ctx.user_id, pb["listing_id"], start, ctx.now)
    if result["ok"]:
        ctx.pending_booking = None
        cards = inv.get_cards(ctx.conn, [pb["listing_id"]])
        if cards:
            memory.like(ctx.conn, ctx.user_id, cards[0], ctx.session_id, ctx.now)
            ctx.note_write("liked_cars", "confirm_viewing", listing_id=pb["listing_id"])
        ctx.note_write(
            "bookings", "confirm_viewing", ref=result["ref"], listing_id=pb["listing_id"]
        )
        try:
            from dubizzle_assistant.services import leads

            leads.note_booking(ctx, pb["listing_id"])
        except ImportError:
            pass
    return result


def _cancel(ctx: TurnContext, args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("booking_ref") or "").strip()
    if not ref:
        mine = [b for b in list_bookings(ctx.conn, ctx.user_id) if b["status"] == "confirmed"]
        if len(mine) == 1:
            ref = mine[0]["ref"]
        else:
            return {
                "ok": False,
                "reason": "which booking? give the reference",
                "bookings": [
                    {"ref": b["ref"], "listing_id": b["listing_id"], "slot_start": b["slot_start"]}
                    for b in mine
                ],
            }
    result = cancel_booking(ctx.conn, ctx.settings, ctx.user_id, ref, ctx.now)
    if result["ok"]:
        ctx.note_write("bookings", "cancel_viewing", ref=result["ref"], status="cancelled")
    return result


tool_registry.register(
    {
        "name": "get_availability",
        "description": "Free viewing slots for a listing in a given week, for when the user asks what times are open. If they name a day and time, call propose_viewing instead. Viewings run Monday to Saturday, 08:00 to 20:00 Dubai time.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "string"},
                "date_text": {
                    "type": "string",
                    "description": "Any day in the week of interest, as the user said it",
                },
            },
            "required": ["listing_id"],
        },
    },
    _availability,
)
tool_registry.register(
    {
        "name": "propose_viewing",
        "description": "The tool for any request to book, schedule or view a car at a given day and time. Validates the slot and holds it as a proposal. Read the returned readback to the user and wait for their answer. Never confirms by itself.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {"type": "string"},
                "date_text": {
                    "type": "string",
                    "description": "The day as the user said it: 'tomorrow', 'next Friday', 'Monday', '2026-09-07'",
                },
                "date_iso": {
                    "type": "string",
                    "description": "Your own conversion to YYYY-MM-DD, optional",
                },
                "hour": {"type": "integer", "description": "Start hour 8 to 19 in 24h Dubai time"},
            },
            "required": ["listing_id", "date_text"],
        },
    },
    _propose,
)
tool_registry.register(
    {
        "name": "confirm_viewing",
        "description": "Book the currently proposed viewing. Only call after the user has agreed in a message that came after the proposal.",
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "optional"}},
        },
    },
    _confirm,
)
tool_registry.register(
    {
        "name": "cancel_viewing",
        "description": "Cancel one of the user's confirmed viewings by reference (BK-0001).",
        "parameters": {"type": "object", "properties": {"booking_ref": {"type": "string"}}},
    },
    _cancel,
)
