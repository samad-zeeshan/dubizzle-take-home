"""The offline stand-in must greet a returning customer from memory, not with a bare hello.

A reviewer without an API key runs the whole demo on this client, and the second scenario
the brief asks for is recall in a new session. A generic greeting there reads as if memory
were never wired up at all.
"""

from __future__ import annotations

from dubizzle_assistant.services.llm.mock_client import HeuristicLLM, _recall_from_prompt

RECALL_BLOCK = (
    "## Returning user\n"
    "Name, spell it exactly: Sara. Sessions so far: 4.\n"
    "Stated preferences: budget max aed: 150000; body type: suv.\n"
    'Searched yesterday: "show me SUVs with warranty under AED 150k" (25 results).\n'
    "Liked yesterday: 2018 land rover range rover velar (C-003).\n"
    "Upcoming viewing: C-003 at 2026-09-14 10:00 (BK-0001).\n"
    "Greet them by name once, mention what you remember briefly, then follow their lead.\n"
    "## Now\nCurrent time: Monday 2026-09-08 02:00 Asia/Dubai."
)


def _reply(system: str, message: str) -> str:
    out = HeuristicLLM().complete(
        [{"role": "system", "content": system}, {"role": "user", "content": message}]
    )
    return out.text or ""


def test_parses_the_block_the_router_writes() -> None:
    parsed = _recall_from_prompt(RECALL_BLOCK)
    assert parsed is not None
    name, sentences = parsed
    assert name == "Sara"
    joined = " ".join(sentences)
    assert "show me SUVs with warranty under AED 150k" in joined
    assert "2018 Land Rover Range Rover Velar" in joined
    assert "BK-0001" in joined
    # The post-filter scrubs listing ids, so quoting one would leave a hole in the sentence.
    assert "C-003" not in joined


def test_greeting_a_returning_customer_uses_memory() -> None:
    reply = _reply(RECALL_BLOCK, "hi, it's Sara")
    assert "Welcome back, Sara" in reply
    assert "2018 Land Rover Range Rover Velar" in reply
    assert "BK-0001" in reply


def test_greeting_without_memory_stays_generic() -> None:
    reply = _reply("## Now\nCurrent time: Monday 2026-09-08 02:00 Asia/Dubai.", "hi there")
    assert "Welcome back" not in reply
    assert "explore the cars" in reply


def test_no_second_greeting_in_the_same_session() -> None:
    already = RECALL_BLOCK.replace(
        "Greet them by name once, mention what you remember briefly, then follow their lead.",
        "You have already greeted them this session. Do not greet them again.",
    )
    assert "Welcome back" not in _reply(already, "hello again")


def test_asking_what_i_looked_at_answers_from_memory() -> None:
    reply = _reply(RECALL_BLOCK, "remind me what I was looking at")
    assert "2018 Land Rover Range Rover Velar" in reply
    assert "Here is what I have on file" not in reply
