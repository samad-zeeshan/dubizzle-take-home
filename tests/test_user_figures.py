"""A figure the customer typed is a source, so echoing it back is not a hallucination."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from dubizzle_assistant.api.app import create_app
from dubizzle_assistant.services.guardrails import figures_in
from dubizzle_assistant.services.llm.base import ToolCall
from tests.conftest import make_settings
from tests.test_loop_cap import Scripted, _resp

ARABIC_ASK = "هل يوجد BMW X6 موديل ٢٠٢٣؟ وكم سعرها وممشاها؟"


def _turn(tmp_path: Path, message: str, *replies: str, locale: str = "en") -> dict[str, Any]:
    """One turn where the model searches, then answers. Extra replies feed the grounding retry."""
    llm = Scripted(
        [
            _resp("", [ToolCall(id="1", name="search_inventory", arguments={"make": "bmw"})]),
            *[_resp(r) for r in replies],
        ]
    )
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        app.state.llm = llm
        return c.post(
            "/chat", json={"message": message, "name": "Figures", "locale": locale}
        ).json()


def _grounding(envelope: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in envelope["trace"]["stages"] if s["stage"] == "grounding")


def _purposes(envelope: dict[str, Any]) -> list[str]:
    return [s.get("purpose") for s in envelope["trace"]["stages"] if s["stage"] == "llm_call"]


def test_arabic_indic_digits_are_read_as_the_same_figure():
    assert "2023" in figures_in(ARABIC_ASK)


def test_the_year_the_customer_asked_for_is_grounded(tmp_path: Path) -> None:
    e = _turn(tmp_path, "Do you have a 2023 BMW X6?", "We have no 2023 BMW X6 in stock right now.")
    assert _grounding(e)["ungrounded"] == []
    # The retry is what used to burn a call and then throw the answer away.
    assert "regenerate" not in _purposes(e)
    assert e["reply"].startswith("We have no 2023")


def test_an_arabic_session_keeps_its_language(tmp_path: Path) -> None:
    """Both digit systems, because the customer types Arabic-Indic and the model answers Western."""
    for reply in ("لا يوجد لدينا BMW X6 موديل 2023.", "لا يوجد لدينا BMW X6 موديل ٢٠٢٣."):
        e = _turn(tmp_path, ARABIC_ASK, reply, locale="ar")
        assert _grounding(e)["ungrounded"] == [], reply
        assert "regenerate" not in _purposes(e)
        assert e["reply"] == reply


def test_the_grounded_fallback_speaks_arabic(tmp_path: Path) -> None:
    """When the guard does fire, the reply must not switch language mid-session."""
    invented = "السعر هو 999999999 درهم."
    e = _turn(tmp_path, ARABIC_ASK, invented, invented, locale="ar")
    assert _grounding(e)["ungrounded"] == ["999999999"]
    assert "إليك ما تذكره" in e["reply"] or "هذا ما أستطيع تأكيده" in e["reply"]
    assert "Here is what" not in e["reply"]
