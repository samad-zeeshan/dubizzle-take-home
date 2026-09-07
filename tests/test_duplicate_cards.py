"""One car, one card, one display number, however many tools found it.

Report break 9: the chain prompt returned R-016 and R-057 twice each, both with the same
display number, which collides the per-card key the grid renders with.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.base import ToolCall
from dubizzle_assistant.services.memory import push_shown
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

CHAIN = (
    "Find your three cheapest SUVs, then compare all three side by side, then show me cars "
    "similar to whichever one has the lowest mileage, then check what viewing slots are free "
    "for that one on Saturday, and finally tell me which is the best value and remember that "
    "my budget is 90000 AED."
)


def test_push_shown_already_dedupes_within_one_turn():
    """The report blamed this too. It is correct, so this locks it rather than changing it."""
    card = {"id": "C-025", "year": 2018, "make": "bmw", "model": "x6"}
    out = push_shown([], [card, card], 1)
    assert [c["id"] for c in out] == ["C-025"]
    assert [c["display_index"] for c in out] == [1]


def test_the_chain_prompt_shows_each_car_once(tmp_path: Path) -> None:
    llm = Scripted(
        [
            _resp(
                "",
                [
                    ToolCall(
                        id="1",
                        name="search_inventory",
                        arguments={"body_type": "suv", "sort": "price_asc", "limit": 3},
                    )
                ],
            ),
            _resp(
                "",
                [
                    ToolCall(
                        id="2",
                        name="compare_listings",
                        arguments={"listing_ids": ["R-057", "R-052", "R-016"]},
                    )
                ],
            ),
            _resp(
                "",
                [ToolCall(id="3", name="similar_listings", arguments={"listing_id": "R-052"})],
            ),
            _resp("The three cheapest SUVs, with alternatives to the lowest mileage one."),
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": CHAIN, "name": "Chain"}).json()

    ids = [x["id"] for x in e["cars"]]
    assert len(ids) == len(set(ids)), f"a car appears twice: {ids}"
    indexes = [x["display_index"] for x in e["cars"]]
    assert len(indexes) == len(set(indexes)), f"two cards share a display number: {indexes}"
    # similar_listings still tells the model about the cars, it just does not draw them again.
    stage = next(
        s for s in e["trace"]["stages"] if s["stage"] == "tool" and s["name"] == "similar_listings"
    )
    assert stage["result_ids"], "the model was left with no alternatives at all"


def _two_identical_searches(*replies: str) -> Scripted:
    hit = {"make": "bmw", "model": "x6"}
    return Scripted(
        [
            _resp(
                "",
                [
                    ToolCall(id="1", name="search_inventory", arguments=hit),
                    ToolCall(id="2", name="search_inventory", arguments=hit),
                ],
            ),
            *[_resp(r) for r in replies],
        ]
    )


def test_two_searches_hitting_one_listing_draw_one_card(tmp_path: Path) -> None:
    """Report break 13: an Arabic session printed the single X6 twice under the same number."""
    llm = _two_identical_searches("One BMW X6 is listed.")
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": "do you have a bmw x6?", "name": "Twice"}).json()

    ids = [x["id"] for x in e["cars"]]
    assert len(ids) == len(set(ids)), f"the same listing was drawn twice: {ids}"


def test_the_grounded_template_lists_the_car_once(tmp_path: Path) -> None:
    """The template reads ctx.new_cards directly, so it is the surface that showed the repeat."""
    invented = "The price is 999999999 dirhams."
    llm = _two_identical_searches(invented, invented)
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": "do you have a bmw x6?", "name": "Tmpl"}).json()

    assert e["reply"].startswith("Here is what the listing data shows:")
    lines = [ln for ln in e["reply"].splitlines() if ln.startswith("- ")]
    assert len(lines) == len(set(lines)), f"the template repeated a car: {lines}"
