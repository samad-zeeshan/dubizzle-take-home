"""Three ways the identity and model tables disagreed with the data behind them.

Report breaks 17, 11 and 12: a real model hidden by a static alias, the anonymous bucket
claimable as a name, and a long name that could never find its own row again.
"""

from __future__ import annotations

import re
from datetime import datetime

from dubizzle_assistant.config import DUBAI
from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.normalize import resolve_make_model
from dubizzle_assistant.services import memory

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=DUBAI)
LONG_NAME = "Anastasiya-Konstantinopolitanovska-Bartholomewsdottir-Alexandrovna"


def _users(tmp_path):
    db = tmp_path / "u.db"
    init_db(db)
    return connect(db)


def test_a_named_model_resolves_to_itself_not_to_an_alias(inventory_conn, inventory):
    """ "Do you have a Bentley Flying Spur?" answered with a 2006 Continental."""
    make, model, steps = resolve_make_model("Do you have a Bentley Flying Spur?")
    assert (make, model) == ("bentley", "flying spur"), steps


def test_every_model_name_in_the_inventory_resolves_to_itself(inventory_conn, inventory):
    """The registrar's own eligibility rule, so this asks only what the design promises."""
    wrong = []
    for row in inventory["listings"]:
        name = (row["model"] or "").strip().lower()
        # Short and numeric names stay out on purpose, "3" and "x5" would match everywhere.
        if len(name) < 4 or not re.search(r"[a-z]{3}", name):
            continue
        # "genesis" is both a make in this dataset and one car's model. Nothing can read that
        # phrase two ways at once, and the make is the safer half to keep.
        if name in {r["make"] for r in inventory["listings"]}:
            continue
        make, model, _ = resolve_make_model(name)
        if model != name:
            wrong.append((row["id"], name, model))
    assert not wrong, f"{len(wrong)} model names resolve to a different model: {wrong[:5]}"


def test_the_anonymous_bucket_is_not_a_claimable_name(tmp_path):
    conn = _users(tmp_path)
    first = memory.identify_user(conn, NOW)  # no name: the server calls them guest
    assert first["name"] == "guest"
    memory.remember(conn, first["user_id"], "body_type", "suv", "stated", None, NOW)

    claimer = memory.identify_user(conn, NOW, name="Guest")
    assert claimer["user_id"] != first["user_id"]
    assert claimer["returning"] is False
    assert memory.profile(conn, claimer["user_id"], NOW)["preferences"] == {}


def test_a_real_name_still_finds_its_profile(tmp_path):
    conn = _users(tmp_path)
    first = memory.identify_user(conn, NOW, name="Sara")
    again = memory.identify_user(conn, NOW, name="  sara ")
    assert again["user_id"] == first["user_id"] and again["returning"] is True


def test_a_name_longer_than_the_column_is_the_same_person_next_visit(tmp_path):
    conn = _users(tmp_path)
    assert len(LONG_NAME) > memory.NAME_LIMIT
    first = memory.identify_user(conn, NOW, name=LONG_NAME)
    assert first["returning"] is False

    second = memory.identify_user(conn, NOW, name=LONG_NAME)
    assert second["user_id"] == first["user_id"], "a second visit minted a new user"
    assert second["returning"] is True
    rows = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert rows == 1, "the users table grew a row per visit"
    # Whatever is stored is what the recall block will read back, so they have to agree.
    stored = memory.get_user(conn, first["user_id"])
    assert stored["name_key"] == memory.name_key(stored["name"])
