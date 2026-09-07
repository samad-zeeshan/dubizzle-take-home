"""A failed turn shows the customer a sentence, not the response body."""

from __future__ import annotations

from views.chat import one_line


def test_a_json_body_becomes_its_detail():
    assert one_line('{"detail": "The model is rate limited right now."}') == (
        "The model is rate limited right now."
    )
    # FastAPI's validation errors arrive as a list of field objects.
    assert (
        one_line('{"detail": [{"type": "too_long", "msg": "String should have at most 1000"}]}')
        == "String should have at most 1000"
    )


def test_nothing_reaches_the_transcript_as_json():
    for raw in (
        '{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}',
        "{not even valid json",
        "[]",
        "",
        None,
    ):
        out = one_line(raw)
        assert out and not out.startswith(("{", "[")) and "\n" not in out


def test_a_long_traceback_is_one_short_line():
    out = one_line("backend not reachable: " + "ConnectError: [Errno 61] refused\n" * 40)
    assert len(out) <= 160 and "\n" not in out and out.endswith("…")
