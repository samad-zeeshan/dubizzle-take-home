"""Leads: the qualification rule, phone normalisation, the CSV, and capture through chat and the form."""

from __future__ import annotations

import csv
from datetime import datetime

import pytest

from dubizzle_assistant.config import DUBAI
from dubizzle_assistant.db import connect, init_db
from dubizzle_assistant.normalize import parse_budget
from dubizzle_assistant.services import leads, memory
from dubizzle_assistant.services.leads import normalize_phone, qualify
from dubizzle_assistant.services.llm.mock_client import _lead_budget_text

NOW = datetime(2026, 9, 5, 14, 30, tzinfo=DUBAI)


def test_phone_normalisation():
    assert normalize_phone("050 123 4567") == "+971501234567"
    assert normalize_phone("+971 55 123 4567") == "+971551234567"
    assert normalize_phone("00971589695000") == "+971589695000"
    assert normalize_phone("0555540224") == "+971555540224"
    assert normalize_phone("12345") is None
    assert normalize_phone("+44 20 7946 0958") is None


def test_qualification_matrix():
    assert qualify({})[0] == "new"
    assert qualify({"budget_max_aed": 80000})[0] == "partial"
    status, reason = qualify({"budget_max_aed": 80000, "body_type": "suv", "timeline": "1m"})
    assert status == "partial" and "phone or email" in reason
    status, reason = qualify(
        {"phone": "+971501234567", "budget_max_aed": 80000, "body_type": "suv", "timeline": "1m"}
    )
    assert status == "qualified" and "all present" in reason
    status, reason = qualify(
        {
            "phone": "+971501234567",
            "budget_max_aed": 80000,
            "body_type": "suv",
            "timeline": "browsing",
        }
    )
    assert status == "partial" and "timeline" in reason
    assert qualify({"booked_listing_ids": "C-003"}) == ("qualified", "confirmed viewing booked")


def test_upsert_merges_and_exports_csv(tmp_path, app_settings):
    db = tmp_path / "l.db"
    init_db(db)
    conn = connect(db)
    memory.identify_user(conn, NOW, user_id="u1", name="سارة")
    lead = leads.upsert(
        conn,
        app_settings,
        "u1",
        "s1",
        {"budget_max_aed": 150000, "preferred_makes": ["toyota"]},
        NOW,
    )
    assert lead["status"] == "partial" and lead["name"] == "سارة"
    lead = leads.upsert(
        conn,
        app_settings,
        "u1",
        "s1",
        {"preferred_makes": ["bmw", "toyota"], "body_type": "suv"},
        NOW,
    )
    assert lead["preferred_makes"] == "toyota|bmw"
    lead = leads.set_contact(
        conn, app_settings, "u1", NOW, name=None, phone="050 123 4567", email="bad"
    )
    assert lead["phone"] == "+971501234567" and lead["problems"] == ["email does not look valid"]
    lead = leads.upsert(conn, app_settings, "u1", "s1", {"timeline": "1m"}, NOW)
    assert lead["status"] == "qualified"
    path = app_settings.leads_csv
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "utf-8-sig so Excel renders Arabic"
    assert b"\r\r\n" not in raw
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    assert len(rows) == 1 and rows[0]["name"] == "سارة" and rows[0]["status"] == "qualified"
    assert rows[0]["qualification_reason"] == "contact, budget, need and timeline all present"
    assert not path.with_suffix(".tmp").exists()
    assert list(rows[0].keys()) == list(leads.CSV_COLUMNS)


def test_capture_through_chat_and_form(client):
    e = client.post("/chat", json={"message": "show me the velar", "name": "Lead User"}).json()
    uid, sid = e["user_id"], e["session_id"]
    e = client.post(
        "/chat",
        json={
            "message": "remember my budget is around 150k and I want an suv this month",
            "user_id": uid,
            "session_id": sid,
        },
    ).json()
    tools = [s.get("name") for s in e["trace"]["stages"] if s["stage"] == "tool"]
    assert "remember_preference" in tools or "update_lead" in tools
    r = client.post(
        "/leads/contact", json={"user_id": uid, "name": "Lead User", "phone": "055 987 6543"}
    ).json()
    assert r["phone"] == "+971559876543"
    all_leads = client.get("/leads").json()
    mine = next(x for x in all_leads if x["user_id"] == uid)
    assert mine["phone"] == "+971559876543"
    e = client.post(
        "/chat", json={"message": "what's the mileage on it?", "user_id": uid, "session_id": sid}
    ).json()
    block = next(s for s in e["trace"]["stages"] if s["stage"] == "memory_read")["lead_block"]
    assert block and "contact details on file" in block
    csv_resp = client.get("/leads.csv")
    assert csv_resp.status_code == 200 and "lead_id" in csv_resp.text.splitlines()[0]
    assert "+971559876543" not in e["reply"]


def test_offline_budget_reaches_the_lead_row(client):
    """A budget said to the stand-in has to land in the CSV, not just in the profile.

    The test above passes on remember_preference alone, which is how a lead row with an empty
    budget and a status of "missing: budget, make, body type" went unnoticed for so long.
    """
    e = client.post(
        "/chat", json={"message": "show me a toyota suv under 60000", "name": "Offline Lead"}
    ).json()
    tools = [s.get("name") for s in e["trace"]["stages"] if s["stage"] == "tool"]
    assert "update_lead" in tools
    # Recording the lead is bookkeeping behind the search; the buyer was searching.
    assert e["intent"] == "inventory_search"

    mine = next(x for x in client.get("/leads").json() if x["user_id"] == e["user_id"])
    assert mine["budget_max_aed"] == 60000
    assert "toyota" in mine["preferred_makes"] and mine["body_type"] == "suv"
    assert "60000" in client.get("/leads.csv").text


def test_a_browsing_search_raises_no_lead(client):
    """Naming a make is not a qualification signal, or every idle search invents an empty lead."""
    e = client.post("/chat", json={"message": "show me hondas", "name": "Browser Only"}).json()
    tools = [s.get("name") for s in e["trace"]["stages"] if s["stage"] == "tool"]
    assert tools == ["search_inventory"]
    assert not [x for x in client.get("/leads").json() if x["user_id"] == e["user_id"]]


# A budget filed against a buyer has to be surer than one used to widen a search. Each of these
# was a wrong row in data/leads.csv before the stand-in stopped reusing the search figure.
BUDGETS = [
    ("my budget is 25,000 euros for a family SUV", None, None),
    ("show me a bmw under 25000 euros", None, None),
    ("my budget is 25000 pounds", None, None),
    ("i can pay 2000 monthly", 2000, "monthly"),
    ("budget is 2500 dirhams a month", 2500, "monthly"),
    ("under 2000 a month", 2000, "monthly"),
    ("i have 3 kids so i need a 7 seater, max budget 90000", 90000, "cash"),
    ("i need a family car with max 7 seats", None, None),
    ("show me the 3 series under 90000", 90000, "cash"),
    ("2021 corolla under 60k", 60000, "cash"),
    ("show me cars under 60000 km", None, None),
    ("any of those under 50k km", None, None),
    ("anything below 40000 kms", None, None),
    ("my budget is 150000", 150000, "cash"),
    ("show me hondas", None, None),
]


@pytest.mark.parametrize(("message", "amount", "mode"), BUDGETS)
def test_offline_budget_phrase(message, amount, mode):
    phrase = _lead_budget_text(message)
    money = parse_budget(phrase) if phrase else None
    assert (int(money.amount_aed) if money else None) == amount
    assert (money.mode if money else None) == mode


def test_a_foreign_currency_budget_is_refused_not_repriced(client):
    """The phrase must reach update_lead with "euros" attached, or leads.py cannot refuse it.

    Truncating it to "25,000" walked straight past the unsupported_currency guard and filed an
    AED 25,000 buyer, which is the contradiction leads.py:334 says was already fixed once.
    """
    e = client.post(
        "/chat",
        json={"message": "my budget is 25,000 euros for a family suv", "name": "Euro Buyer"},
    ).json()
    rows = [x for x in client.get("/leads").json() if x["user_id"] == e["user_id"]]
    assert not rows or not rows[0].get("budget_max_aed")
    # And it has to say so. Recording nothing while replying "Noted" reads as accepted.
    assert "dirhams" in e["reply"] and "25,000" not in e["reply"] and "25000" not in e["reply"]


def test_a_mileage_filter_is_not_a_budget(client):
    """ "under 50000 km" filed a budget of AED 50,000,000 and overwrote a real one."""
    e = client.post(
        "/chat", json={"message": "my budget is 150000", "name": "Mileage Buyer"}
    ).json()
    uid, sid = e["user_id"], e["session_id"]
    client.post(
        "/chat", json={"message": "any of those under 50k km", "user_id": uid, "session_id": sid}
    )
    mine = next(x for x in client.get("/leads").json() if x["user_id"] == uid)
    assert mine["budget_max_aed"] == 150000
