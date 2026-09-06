"""
CLI: create a returning user with yesterday's history, so the recall screenshot is reproducible in one command.

    uv run python scripts/seed_demo_user.py            # seeds "Sara" against the configured database
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.config import get_settings  # noqa: E402
from dubizzle_assistant.db import connect, init_db  # noqa: E402
from dubizzle_assistant.services import booking, inventory, leads, memory  # noqa: E402


def main() -> int:
    s = get_settings()
    init_db(s.db_path)
    conn = connect(s.db_path)
    if conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0:
        inventory.load_inventory(conn, s.inventory_path)
    now = s.now()
    yesterday = now - timedelta(days=1)
    user = memory.identify_user(conn, yesterday, name="Sara")
    uid = user["user_id"]
    sid = memory.create_session(conn, uid, yesterday)
    memory.record_search(
        conn,
        uid,
        sid,
        "white SUV under AED 75k",
        {"body_type": "suv", "color": "white", "price_max_aed": 75000},
        11,
        yesterday,
    )
    memory.record_search(
        conn,
        uid,
        sid,
        "show me SUVs with warranty under AED 150k",
        {"body_type": "suv", "has_warranty": True, "price_max_aed": 150000},
        25,
        yesterday,
    )
    memory.remember(conn, uid, "budget_max_aed", "150000", "stated", sid, yesterday)
    memory.remember(conn, uid, "body_type", "suv", "stated", sid, yesterday)
    velar = inventory.get_cards(conn, ["C-003"])[0]
    memory.like(conn, uid, velar, sid, yesterday)
    leads.upsert(
        conn,
        s,
        uid,
        sid,
        {
            "budget_max_aed": 150000,
            "body_type": "suv",
            "timeline": "1m",
            "interested_listing_ids": ["C-003"],
        },
        yesterday,
    )
    # The coming Monday at 10:00, which is never a Sunday and always more than an hour away.
    monday = now + timedelta(days=(7 - now.weekday()) % 7 or 7)
    slot = monday.replace(hour=10, minute=0, second=0, microsecond=0)
    result = booking.create_booking(conn, s, uid, "C-003", slot, now)
    print(
        f"seeded user {uid} (Sara): 2 searches, 2 preferences, liked C-003, booking {result.get('ref') or result.get('reason')}"
    )
    print(
        "Open the client, type \"hi, it's Sara\" and the greeting should recall yesterday's search, the Velar, and the Monday viewing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
