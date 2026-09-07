"""A figure worked out from two listed figures is refused, but the refusal says so.

Report break 1: "how much more expensive is the Patrol than the Prado" is correct arithmetic
and the guard deleted it, leaving a reply that quoted two prices and answered nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.guardrails import derived_figures
from dubizzle_assistant.services.llm.base import ToolCall
from dubizzle_assistant.services.prompts import is_repair_note
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

ASK = "How much more expensive is the 2023 Nissan Patrol than the 2023 Toyota Prado? Just give me the difference in AED."


def test_a_difference_of_two_sourced_prices_is_recognised():
    sources = {"186999": {"field": "price_aed"}, "150000": {"field": "price_aed"}}
    assert derived_figures(["36,999"], sources) == ["36,999"]
    assert derived_figures(["36999"], sources) == ["36999"]
    assert derived_figures(["336999"], sources) == ["336999"]  # the sum, same class
    assert derived_figures(["777777"], sources) == []


def test_an_id_among_the_ungrounded_is_left_alone():
    assert derived_figures(["C-003"], {"119750": {"field": "price_aed"}}) == []


def _turn(tmp_path: Path, first_draft: str, second: str) -> dict[str, Any]:
    llm = Scripted(
        [
            _resp(
                "",
                [
                    ToolCall(
                        id="1",
                        name="compare_listings",
                        arguments={"listing_ids": ["R-041", "R-062"]},
                    )
                ],
            ),
            _resp(first_draft),
            _resp(second),
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": ASK, "name": "Sums"}).json()
    e["_seen"] = llm.seen
    return e


def test_the_rewrite_note_names_the_arithmetic(tmp_path: Path) -> None:
    honest = "I cannot work out the difference, but the listings state 186,999 and 150,000."
    e = _turn(tmp_path, "The difference is 36,999 AED.", honest)

    stage = next(s for s in e["trace"]["stages"] if s["stage"] == "grounding")
    assert "36,999" in stage["ungrounded"] or "36999" in stage["computed"]
    assert stage["computed"], "the difference was not recognised as arithmetic"

    note = e["_seen"][2][-1]["content"]
    assert is_repair_note(note)
    assert "arithmetic on other figures" in note
    assert "cannot give a worked out figure" in note
    # The old note told the model to say the listing does not state it, which was untrue.
    assert "say the listing does not state it" not in note
    assert e["reply"] == honest


def test_an_invented_figure_still_gets_the_old_note(tmp_path: Path) -> None:
    """Nothing about the anti-hallucination path changes for a figure that is simply made up."""
    e = _turn(tmp_path, "It has 987654 km on the clock.", "The listing does not state the mileage.")
    note = e["_seen"][2][-1]["content"]
    assert "do not appear in the tool results" in note
    assert "arithmetic on other figures" not in note
