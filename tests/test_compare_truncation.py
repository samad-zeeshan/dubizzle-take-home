"""More ids than compare takes are named, not dropped in silence.

Report break 7: asked for six, the tool returned four and the model told the customer the
other two were not in the inventory. Both were sitting in the dataset.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.llm.base import ToolCall
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

SIX = ["C-003", "C-006", "R-016", "R-052", "R-057", "R-037"]
ASK = (
    "Compare these six for me side by side: C-003, C-006, R-016, R-052, R-057 and R-037. "
    "I want price, year and mileage for all six in one table."
)


def test_six_real_ids_are_reported_not_swallowed(tmp_path: Path) -> None:
    llm = Scripted(
        [
            _resp(
                "",
                [ToolCall(id="1", name="compare_listings", arguments={"listing_ids": SIX})],
            ),
            _resp("Here are the four I can compare at once."),
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        e = c.post("/chat", json={"message": ASK, "name": "Six"}).json()

    # What the model was handed on the second call is the thing that matters.
    result = next(m for m in llm.seen[1] if m.get("role") == "tool")["content"]
    assert "R-057" in result and "R-037" in result
    assert "not_compared" in result
    assert "are in the inventory but were not included" in result
    # And the four that were compared still came back whole.
    stage = next(
        s for s in e["trace"]["stages"] if s["stage"] == "tool" and s["name"] == "compare_listings"
    )
    assert stage["result_ids"] == SIX[:4]


def test_four_or_fewer_carries_no_note(tmp_path: Path) -> None:
    llm = Scripted(
        [
            _resp(
                "",
                [ToolCall(id="1", name="compare_listings", arguments={"listing_ids": SIX[:3]})],
            ),
            _resp("Three compared."),
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        c.post("/chat", json={"message": "compare three", "name": "Three"})
    result = next(m for m in llm.seen[1] if m.get("role") == "tool")["content"]
    assert "not_compared" not in result
