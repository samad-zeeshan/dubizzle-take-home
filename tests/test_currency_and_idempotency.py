"""A budget this system cannot price, and a double click before anyone has an identity.

Report breaks 15 and 16: 25,000 euros became AED 25,000 in the SQL and in the lead CSV, and
the idempotency key did nothing for anonymous first contact, the one case it exists for.
"""

from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.normalize import parse_budget, unsupported_currency
from dubizzle_assistant.services.explain import filters_from_args
from dubizzle_assistant.services.llm.base import ToolCall
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

EUROS = "My budget is 25,000 euros for a family SUV. What can I get?"
KEY = "11111111-2222-3333-4444-555555555555"
TWICE = "show me toyota sedans under 60k"


def test_a_currency_we_cannot_convert_is_refused_not_rescaled():
    assert unsupported_currency("25,000 euros") == "euros"
    assert parse_budget("My budget is 25,000 euros") is None
    # The two that are pegged still convert, and a bare figure is still dirhams.
    assert parse_budget("$20k").amount_aed == 73450
    assert parse_budget("under 150 thousand").amount_aed == 150_000


def test_the_search_gets_no_ceiling_and_a_step_saying_why():
    f, steps = filters_from_args({"budget_text": "25,000 euros", "body_type": "suv"})
    assert f.price_max_aed is None and f.monthly_max_aed is None
    assert any("euros" in s and "ask for the figure in AED" in s for s in steps)


def test_the_lead_row_never_contradicts_itself(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = Scripted(
        [
            _resp(
                "",
                [
                    ToolCall(
                        id="1",
                        name="update_lead",
                        arguments={"budget_text": "25,000 euros", "body_type": "suv"},
                    )
                ],
            ),
            _resp("Prices here are in dirhams. What is your budget in AED?"),
        ]
    )
    app = create_app(settings)
    with TestClient(app) as c:
        app.state.llm = llm
        c.post("/chat", json={"message": EUROS, "name": "Euro"})

    result = next(m for m in llm.seen[1] if m.get("role") == "tool")["content"]
    assert "25000" not in result.replace(",", "")
    assert "cannot be converted" in result
    if settings.leads_file.exists():
        rows = list(csv.DictReader(settings.leads_file.open(encoding="utf-8")))
        for row in rows:
            assert row.get("budget_max_aed") != "25000"


def _plenty(text: str) -> Scripted:
    """A turn can cost more than one model call, the search nudge among them."""
    return Scripted([_resp(text) for _ in range(12)])


def _anonymous(c: TestClient) -> dict:
    return c.post("/chat", json={"message": TWICE}, headers={"Idempotency-Key": KEY}).json()


def test_a_double_click_before_anyone_is_identified_is_one_request(tmp_path: Path) -> None:
    llm = _plenty("Here are the Toyota sedans.")
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        first = _anonymous(c)
        calls_after_first = len(llm.seen)
        second = _anonymous(c)

    assert second.get("idempotent_replay") is True
    assert second["user_id"] == first["user_id"], "the retry minted a second user"
    assert second["session_id"] == first["session_id"]
    assert len(llm.seen) == calls_after_first, "the retry called the model again"


def test_a_known_user_still_replays_on_the_key(tmp_path: Path) -> None:
    llm = _plenty("Hello.")
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        opened = c.post("/chat", json={"message": "hi", "name": "Known"}).json()
        body = {"message": TWICE, "user_id": opened["user_id"]}
        a = c.post("/chat", json=body, headers={"Idempotency-Key": KEY}).json()
        b = c.post("/chat", json=body, headers={"Idempotency-Key": KEY}).json()
    assert b.get("idempotent_replay") is True and b["user_id"] == a["user_id"]


def test_a_different_key_is_a_different_request(tmp_path: Path) -> None:
    llm = _plenty("One.")
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        c.post("/chat", json={"message": TWICE}, headers={"Idempotency-Key": KEY})
        other = c.post(
            "/chat", json={"message": TWICE}, headers={"Idempotency-Key": KEY.replace("1", "9")}
        ).json()
    assert not other.get("idempotent_replay")
