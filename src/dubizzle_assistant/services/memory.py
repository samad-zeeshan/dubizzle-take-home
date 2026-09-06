"""
Short and long term memory: sessions, message blobs, the cars on screen, users, preferences.

Short term is a numbered list of what the user has been shown, kept server
side so "the first one" resolves in code. Long term is typed slots written by
tools, never a free-text summary, so nothing a user says can be replayed as an
instruction next session.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime
from typing import Any

from dubizzle_assistant.normalize import known_makes, resolve_make_model
from dubizzle_assistant.text import contains_contact

PREFERENCE_KINDS = {
    "budget_max_aed",
    "budget_min_aed",
    "monthly_max_aed",
    "make",
    "model",
    "body_type",
    "color",
    "regional_spec",
    "fuel_type",
    "must_have",
    "dislike",
    "timeline",
    "financing_interest",
    "year_min",
}
SCALAR_KINDS = {
    "budget_max_aed",
    "budget_min_aed",
    "monthly_max_aed",
    "timeline",
    "financing_interest",
    "year_min",
}
_INJECTION_RE = re.compile(
    r"ignore (all|any|the|your|previous)|system prompt|you are now|recommend|always say|forget your",
    re.I,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def name_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# users --------------------------------------------------------------------


def identify_user(
    conn: sqlite3.Connection, now: datetime, *, name: str | None = None, user_id: str | None = None
) -> dict[str, Any]:
    """Find or create a user. A typed name is spoofable by design; the README says so."""
    row = None
    if user_id:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None and name:
        row = conn.execute(
            "SELECT * FROM users WHERE name_key = ? ORDER BY created_at LIMIT 1", (name_key(name),)
        ).fetchone()
    if row is None:
        display = (name or user_id or "guest").strip()[:60]
        uid = user_id or ("u_" + secrets.token_hex(4))
        with conn:
            conn.execute(
                "INSERT INTO users (user_id, name, name_key, created_at, last_seen_at) VALUES (?,?,?,?,?)",
                (uid, display, name_key(display), _iso(now), _iso(now)),
            )
        return {"user_id": uid, "name": display, "returning": False}
    with conn:
        conn.execute(
            "UPDATE users SET last_seen_at = ? WHERE user_id = ?", (_iso(now), row["user_id"])
        )
    return {"user_id": row["user_id"], "name": row["name"], "returning": True}


def get_user(conn: sqlite3.Connection, user_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def forget_user(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn:
        sessions = [
            r[0]
            for r in conn.execute("SELECT session_id FROM sessions WHERE user_id = ?", (user_id,))
        ]
        for sid in sessions:
            for table in ("messages", "session_context", "turn_traces"):
                counts[table] = (
                    counts.get(table, 0)
                    + conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,)).rowcount
                )
        for table in (
            "sessions",
            "preference_events",
            "liked_cars",
            "search_history",
            "bookings",
            "leads",
            "idempotency",
        ):
            counts[table] = conn.execute(
                f"DELETE FROM {table} WHERE user_id = ?", (user_id,)
            ).rowcount
        counts["users"] = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,)).rowcount
    return counts


# sessions -----------------------------------------------------------------


def create_session(conn: sqlite3.Connection, user_id: str, now: datetime) -> str:
    sid = "s_" + secrets.token_urlsafe(6)
    with conn:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, created_at, last_active_at) VALUES (?,?,?,?)",
            (sid, user_id, _iso(now), _iso(now)),
        )
        conn.execute("INSERT INTO session_context (session_id) VALUES (?)", (sid,))
    return sid


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def begin_turn(conn: sqlite3.Connection, session_id: str, now: datetime) -> int:
    with conn:
        conn.execute(
            "UPDATE sessions SET turn_counter = turn_counter + 1, last_active_at = ? WHERE session_id = ?",
            (_iso(now), session_id),
        )
        return int(
            conn.execute(
                "SELECT turn_counter FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        )


def is_idle(session: dict[str, Any], now: datetime, idle_minutes: int) -> bool:
    last = datetime.fromisoformat(session["last_active_at"])
    return (now - last).total_seconds() > idle_minutes * 60


def append_messages(
    conn: sqlite3.Connection, session_id: str, turn: int, blobs: list[dict[str, Any]], now: datetime
) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO messages (session_id, turn, role, blob_json, created_at) VALUES (?,?,?,?,?)",
            [
                (
                    session_id,
                    turn,
                    b.get("role", "assistant"),
                    json.dumps(b, ensure_ascii=False, default=str),
                    _iso(now),
                )
                for b in blobs
            ],
        )


def load_history(
    conn: sqlite3.Connection, session_id: str, turns: int, after_turn: int = 0
) -> list[dict[str, Any]]:
    """Whole turns only, so an assistant tool call is never sent without its tool result."""
    rows = conn.execute(
        "SELECT turn, blob_json FROM messages WHERE session_id = ? AND turn > "
        "(SELECT COALESCE(MAX(turn), 0) - ? FROM messages WHERE session_id = ?) AND turn > ? ORDER BY id",
        (session_id, turns, session_id, after_turn),
    ).fetchall()
    return [json.loads(r["blob_json"]) for r in rows]


def all_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT turn, role, blob_json, created_at FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {
            "turn": r["turn"],
            "role": r["role"],
            "created_at": r["created_at"],
            **json.loads(r["blob_json"]),
        }
        for r in rows
    ]


# session context: cars on screen, focus, pending booking, summary ------------


def get_context(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM session_context WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO session_context (session_id) VALUES (?)", (session_id,)
            )
        return {
            "shown": [],
            "focus_id": None,
            "pending_booking": None,
            "summary_text": None,
            "summary_through_turn": 0,
        }
    return {
        "shown": json.loads(row["shown_json"] or "[]"),
        "focus_id": row["focus_id"],
        "pending_booking": json.loads(row["pending_booking_json"])
        if row["pending_booking_json"]
        else None,
        "summary_text": row["summary_text"],
        "summary_through_turn": row["summary_through_turn"],
    }


def save_context(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    shown: list[dict[str, Any]],
    focus_id: str | None,
    pending_booking: dict[str, Any] | None,
    summary_text: str | None = None,
    summary_through_turn: int | None = None,
) -> None:
    with conn:
        conn.execute(
            "UPDATE session_context SET shown_json = ?, focus_id = ?, pending_booking_json = ?, "
            "summary_text = COALESCE(?, summary_text), summary_through_turn = COALESCE(?, summary_through_turn) WHERE session_id = ?",
            (
                json.dumps(shown, ensure_ascii=False),
                focus_id,
                json.dumps(pending_booking, ensure_ascii=False) if pending_booking else None,
                summary_text,
                summary_through_turn,
                session_id,
            ),
        )


def push_shown(
    shown: list[dict[str, Any]], cards: list[dict[str, Any]], turn: int
) -> list[dict[str, Any]]:
    """Append a result set with display numbers that continue across the session."""
    start = (shown[-1]["display_index"] if shown else 0) + 1
    seen = {c["id"] for c in shown}
    out = list(shown)
    for c in cards:
        if c["id"] in seen:
            continue
        out.append(
            {
                "display_index": start + len(out) - len(shown),
                "id": c["id"],
                "year": c["year"],
                "make": c["make"],
                "model": c["model"],
                "trim": c.get("trim"),
                "price_aed": c.get("price_aed"),
                "monthly_aed": c.get("monthly_aed"),
                "mileage_km": c.get("mileage_km"),
                "turn": turn,
            }
        )
        seen.add(c["id"])
    return out[-30:]


_ORDINALS = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "الأول": 1,
    "الاول": 1,
    "الثاني": 2,
    "الثالث": 3,
    "الرابع": 4,
    "الخامس": 5,
}
_PRONOUN_RE = re.compile(
    r"\b(it|that one|this one|that car|this car|the car|that|this|it's|its|does it|is it|on it|about it|for it|هذه|هذا|السيارة)\b",
    re.I,
)
_ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|last)\b(?:\s+(one|car|\w+))?|#\s?(\d{1,2})\b|\bnumber\s+(\d{1,2})\b|\boption\s+(\d{1,2})\b",
    re.I,
)
_SEARCH_VERB_RE = re.compile(
    r"\b(show|find|search|list|any|looking for|do you have|give me|what do you have|got any|i want|i need|are there)\b",
    re.I,
)
_COMPARATIVE_RE = re.compile(
    r"\b(cheaper|cheapest|less expensive|pricier|more expensive|newer|newest|older|oldest|lower mileage|fewer km|higher mileage)\b",
    re.I,
)


def resolve_reference(
    text: str, shown: list[dict[str, Any]], focus_id: str | None
) -> dict[str, Any]:
    """Map 'the first one', 'the velar', 'the cheaper one', 'it' to a listing id, in code."""
    out: dict[str, Any] = {
        "input": text,
        "resolved": None,
        "rule": "none",
        "candidates": len(shown),
    }
    if not shown:
        return out
    low = text.lower()
    explicit = re.search(r"\b([cr]-\d{3})\b", low)
    if explicit:
        out.update(resolved=explicit.group(1).upper(), rule="explicit_id")
        return out

    m = _ORDINAL_RE.search(low)
    if m:
        word = (m.group(1) or "").lower()
        num = m.group(3) or m.group(4) or m.group(5)
        # "the first Honda" narrows to that make before counting.
        pool = shown
        qualifier = (m.group(2) or "").lower()
        if qualifier and qualifier not in ("one", "car"):
            narrowed = [
                c
                for c in shown
                if qualifier in (c["make"], c["model"])
                or qualifier in c["model"]
                or qualifier in c["make"]
            ]
            if narrowed:
                pool = narrowed
            else:
                q_make = resolve_make_model(qualifier)[0]
                if q_make or qualifier.rstrip("s") in known_makes():
                    # "that first Honda" when no Honda is on screen: say so rather than hand back the first car.
                    out.update(rule=f"not_on_screen:{qualifier}")
                    return out
        if word == "last":
            out.update(resolved=pool[-1]["id"], rule="ordinal")
            return out
        idx = int(num) if num else _ORDINALS.get(word)
        if idx:
            if num:
                hit = next((c for c in shown if c["display_index"] == idx), None)
                if hit:
                    out.update(resolved=hit["id"], rule="display_number")
                    return out
            if idx <= len(pool):
                out.update(
                    resolved=pool[idx - 1]["id"],
                    rule="ordinal" + (":" + qualifier if pool is not shown else ""),
                )
                return out

    searching = bool(_SEARCH_VERB_RE.search(low))
    if not searching:
        # "the velar", "that range rover", "the honda": the alias table maps the phrase to make and model.
        rm, rmo, _ = resolve_make_model(low)
        if rm:
            same = [
                c
                for c in shown
                if c["make"] == rm and (not rmo or c["model"] == rmo or c["model"].startswith(rmo))
            ]
            if len(same) == 1:
                out.update(resolved=same[0]["id"], rule="make_or_model")
                return out
            if len(same) > 1:
                if focus_id and any(c["id"] == focus_id for c in same):
                    out.update(resolved=focus_id, rule="make_or_model:focus")
                    return out
                out.update(rule="ambiguous:" + (rmo or rm), ambiguous=[c["id"] for c in same])
                return out

    cm = _COMPARATIVE_RE.search(low)
    if cm and len(shown) >= 2 and not searching:
        word = cm.group(1)
        recent = shown[-5:]
        if "cheap" in word or "less expensive" in word:
            priced = [c for c in recent if c.get("price_aed") is not None]
            if priced:
                out.update(
                    resolved=min(priced, key=lambda c: c["price_aed"])["id"],
                    rule="comparative:price",
                )
                return out
        if "pricier" in word or "more expensive" in word:
            priced = [c for c in recent if c.get("price_aed") is not None]
            if priced:
                out.update(
                    resolved=max(priced, key=lambda c: c["price_aed"])["id"],
                    rule="comparative:price",
                )
                return out
        if "new" in word:
            out.update(
                resolved=max(recent, key=lambda c: c["year"] or 0)["id"], rule="comparative:year"
            )
            return out
        if "old" in word:
            out.update(
                resolved=min(recent, key=lambda c: c["year"] or 0)["id"], rule="comparative:year"
            )
            return out
        if "mileage" in word or "km" in word:
            known = [c for c in recent if c.get("mileage_km") is not None]
            if known:
                pick = (
                    min(known, key=lambda c: c["mileage_km"])
                    if "lower" in word or "fewer" in word
                    else max(known, key=lambda c: c["mileage_km"])
                )
                out.update(resolved=pick["id"], rule="comparative:mileage")
                return out

    if _PRONOUN_RE.search(low) and not searching:
        if focus_id:
            out.update(resolved=focus_id, rule="pronoun:focus")
        elif len(shown) == 1 or len({c["turn"] for c in shown}) == 1 and len(shown) == 1:
            out.update(resolved=shown[-1]["id"], rule="pronoun:only_shown")
        else:
            out.update(rule="pronoun:ambiguous")
    return out


# long term: preferences, likes, searches, recall ------------------------------


def check_value(value: str) -> str | None:
    """Reject anything that looks like an instruction or a contact detail before it is stored."""
    if len(value) > 120:
        return "too long"
    if _INJECTION_RE.search(value):
        return "looks like an instruction"
    if contains_contact(value):
        return "contact details are not stored as preferences"
    return None


def remember(
    conn: sqlite3.Connection,
    user_id: str,
    kind: str,
    value: str,
    source: str,
    session_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    if kind not in PREFERENCE_KINDS:
        return {"ok": False, "error": f"unknown preference kind {kind}"}
    value = str(value).strip().lower()
    problem = check_value(value)
    if problem:
        return {"ok": False, "error": problem}
    with conn:
        conn.execute(
            "INSERT INTO preference_events (user_id, kind, value, source, session_id, ts) VALUES (?,?,?,?,?,?)",
            (user_id, kind, value, source, session_id, _iso(now)),
        )
    return {"ok": True, "kind": kind, "value": value}


def like(
    conn: sqlite3.Connection,
    user_id: str,
    card: dict[str, Any],
    session_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    snapshot = {
        k: card.get(k) for k in ("id", "year", "make", "model", "trim", "price_aed", "mileage_km")
    }
    with conn:
        conn.execute(
            "INSERT INTO liked_cars (user_id, listing_id, snapshot_json, session_id, ts) VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id, listing_id) DO UPDATE SET ts = excluded.ts, session_id = excluded.session_id",
            (user_id, card["id"], json.dumps(snapshot, ensure_ascii=False), session_id, _iso(now)),
        )
    return {"ok": True, "listing_id": card["id"]}


def record_search(
    conn: sqlite3.Connection,
    user_id: str,
    session_id: str,
    raw_query: str,
    filters: dict[str, Any],
    count: int,
    now: datetime,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO search_history (user_id, session_id, raw_query, parsed_filters_json, result_count, ts) VALUES (?,?,?,?,?,?)",
            (
                user_id,
                session_id,
                raw_query[:300],
                json.dumps(filters, ensure_ascii=False),
                count,
                _iso(now),
            ),
        )


def relative_time(then: str, now: datetime) -> str:
    t = datetime.fromisoformat(then)
    days = (now.date() - t.date()).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7} week{'s' if days >= 14 else ''} ago"
    return f"on {t.strftime('%d %b %Y')}"


def profile(conn: sqlite3.Connection, user_id: str, now: datetime) -> dict[str, Any]:
    """Materialise the typed slots: newest wins per scalar kind, sets union for the rest."""
    user = get_user(conn, user_id)
    if user is None:
        return {"user_id": user_id, "known": False}
    prefs: dict[str, Any] = {}
    for r in conn.execute(
        "SELECT kind, value, ts FROM preference_events WHERE user_id = ? ORDER BY id", (user_id,)
    ):
        if r["kind"] in SCALAR_KINDS:
            prefs[r["kind"]] = r["value"]
        else:
            prefs.setdefault(r["kind"], [])
            if r["value"] not in prefs[r["kind"]]:
                prefs[r["kind"]].append(r["value"])
    likes = [
        {**json.loads(r["snapshot_json"]), "when": relative_time(r["ts"], now), "ts": r["ts"]}
        for r in conn.execute(
            "SELECT snapshot_json, ts FROM liked_cars WHERE user_id = ? ORDER BY ts DESC LIMIT 5",
            (user_id,),
        )
    ]
    searches = [
        {
            "query": r["raw_query"],
            "filters": json.loads(r["parsed_filters_json"]),
            "results": r["result_count"],
            "when": relative_time(r["ts"], now),
            "ts": r["ts"],
        }
        for r in conn.execute(
            "SELECT raw_query, parsed_filters_json, result_count, ts FROM search_history WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,),
        )
    ]
    bookings = [
        dict(r)
        for r in conn.execute(
            "SELECT ref, listing_id, slot_start, status FROM bookings WHERE user_id = ? AND status = 'confirmed' AND slot_start >= ? ORDER BY slot_start LIMIT 5",
            (user_id, _iso(now)),
        )
    ]
    lead = conn.execute(
        "SELECT status, qualification_reason FROM leads WHERE user_id = ?", (user_id,)
    ).fetchone()
    sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    return {
        "user_id": user_id,
        "known": True,
        "name": user["name"],
        "created_at": user["created_at"],
        "last_seen_at": user["last_seen_at"],
        "sessions": sessions,
        "preferences": prefs,
        "liked_cars": likes,
        "recent_searches": searches,
        "upcoming_bookings": bookings,
        "lead": dict(lead) if lead else None,
    }


def recall_block(p: dict[str, Any]) -> str | None:
    """Under 300 tokens of what we know, built from rows, never from a transcript."""
    if not p.get("known") or (
        not p["preferences"]
        and not p["liked_cars"]
        and not p["recent_searches"]
        and not p["upcoming_bookings"]
    ):
        return None
    lines = [f"Name: {p['name']}. Sessions so far: {p['sessions']}."]
    prefs = p["preferences"]
    if prefs:
        parts = []
        for k, v in prefs.items():
            parts.append(f"{k.replace('_', ' ')}: {', '.join(v) if isinstance(v, list) else v}")
        lines.append("Stated preferences: " + "; ".join(parts) + ".")
    for s in p["recent_searches"][:3]:
        lines.append(f'Searched {s["when"]}: "{s["query"]}" ({s["results"]} results).')
    for c in p["liked_cars"][:3]:
        lines.append(f"Liked {c['when']}: {c['year']} {c['make']} {c['model']} ({c['id']}).")
    for b in p["upcoming_bookings"][:2]:
        lines.append(
            f"Upcoming viewing: {b['listing_id']} at {b['slot_start'][:16].replace('T', ' ')} ({b['ref']})."
        )
    if p.get("lead"):
        lines.append(f"Lead status: {p['lead']['status']} ({p['lead']['qualification_reason']}).")
    lines.append("Use this only when relevant. Never apply stored preferences as silent filters.")
    return "\n".join(lines)
