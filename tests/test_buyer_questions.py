"""The 28 questions a used-car buyer actually asks, graded against the offline model.

Expectations come from the listing's own data, never from a hand-written answer key, so a
regression in the ingest pipeline shows up here as a fact the assistant can no longer state
rather than as a politely worded "the listing does not say".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

NOTES = Path(__file__).resolve().parents[2] / "notes"
if NOTES.is_dir():
    sys.path.insert(0, str(NOTES))

pytest.importorskip(
    "buyer_questions_coverage", reason="the notes directory is not part of this checkout"
)

from buyer_questions_coverage import QUESTIONS  # noqa: E402
from buyer_questions_probe import QUESTION_TEXT, expected_for, grade  # noqa: E402

ANCHORS = ["C-003", "C-025", "C-041", "C-001", "C-039", "R-018", "R-041"]
ID_IN_PROSE = re.compile(r"#?\b[CR]-\d{3}\b", re.I)


def ask(client: Any, message: str, uid: str | None, sid: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message}
    if uid:
        body["user_id"] = uid
    else:
        body["name"] = "Buyer Questions"
    if sid:
        body["session_id"] = sid
    r = client.post("/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def answers(client, listings) -> dict[tuple[str, int], dict[str, Any]]:
    """One pass over every anchor and question, reused by the assertions below."""
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for anchor in ANCHORS:
        uid: str | None = None
        for start in range(0, len(QUESTIONS), 7):
            pin = ask(client, f"tell me more about {anchor}", uid, None)
            uid, sid = pin["user_id"], pin["session_id"]
            for q in QUESTIONS[start : start + 7]:
                out[(anchor, q.number)] = ask(client, QUESTION_TEXT[q.number], uid, sid)
    return out


@pytest.mark.parametrize("anchor", ANCHORS)
def test_every_buyer_question_is_answered_from_the_listing(anchor, answers, listings):
    listing = listings[anchor]
    failures = []
    for q in QUESTIONS:
        env = answers[(anchor, q.number)]
        kind, phrases = expected_for(listing, q.number)
        ok, why = grade(kind, phrases, env, q.number)
        if not ok:
            failures.append(f"Q{q.number:02d} {kind}: {why} :: {env['reply'][:160]}")
    assert not failures, f"{anchor}\n" + "\n".join(failures)


def test_no_listing_id_reaches_the_reply(answers):
    leaked = {
        f"{anchor} Q{number}": env["reply"]
        for (anchor, number), env in answers.items()
        if ID_IN_PROSE.search(env["reply"])
    }
    assert not leaked, leaked


def test_no_figure_in_any_reply_is_ungrounded(answers):
    ungrounded = {
        f"{anchor} Q{number}": env["grounding"]["ungrounded"]
        for (anchor, number), env in answers.items()
        if (env.get("grounding") or {}).get("ungrounded")
    }
    assert not ungrounded, ungrounded


def test_a_reply_that_names_ids_is_caught_and_stripped():
    from dubizzle_assistant.services import guardrails

    text = "Look at C-003, #R-041 and r-005 for that."
    assert guardrails.ids_in_prose(text) == ["C-003", "R-041", "R-005"]
    stripped = guardrails.strip_ids(text)
    assert not ID_IN_PROSE.search(stripped)
    assert "Look at" in stripped and "for that." in stripped


def test_the_inferred_transmission_is_hedged_not_asserted(answers, listings):
    """C-041 states no gearbox, so "automatic" may only appear with the model-knowledge caveat."""
    source = (listings["C-041"]["fields"].get("transmission") or {}).get("source")
    if source not in ("llm", "inferred", "derived"):
        pytest.skip("transmission for C-041 came from the ad on this build")
    reply = answers[("C-041", 24)]["reply"]
    assert re.search(r"normally|typically|usually|generally", reply, re.I)
    assert re.search(r"does not state|not stated", reply, re.I)


def test_the_timing_decoy_is_not_read_as_a_service_record(answers):
    """R-018's ad carries "Timing 09:00AM TO 9:00PM", which is a showroom timetable."""
    reply = answers[("R-018", 25)]["reply"]
    assert not re.search(r"09:00|9:00|showroom|opening hours", reply, re.I)
    assert re.search(r"does not|no mention|not stated", reply, re.I)
