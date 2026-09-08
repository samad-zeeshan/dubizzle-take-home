"""Adding a key from the app: it is written, it takes effect, and it never comes back out."""

from __future__ import annotations

from pathlib import Path

import pytest

from dubizzle_assistant.envfile import looks_like_a_key, masked, write_key

GOOD = "AIza" + "y" * 32
ROOT = Path(__file__).resolve().parents[1]


def test_both_key_shapes_google_issues_are_accepted():
    """Studio hands out AIza... and AQ.A... keys, and a prefix check refused the second."""
    assert looks_like_a_key(GOOD)
    assert looks_like_a_key("AQ.Ab8" + "z" * 47)
    assert looks_like_a_key(f"  {GOOD}  ")
    # What it still catches is a typo or a truncated paste.
    assert not looks_like_a_key("hunter2")
    assert not looks_like_a_key("")
    assert not looks_like_a_key("AIzaShort")
    assert not looks_like_a_key("AIza with a space" + "x" * 20)


def test_masking_shows_enough_to_recognise_and_no_more():
    out = masked(GOOD)
    assert out.startswith("AIza")
    assert out.endswith("yyyy")
    assert GOOD not in out


def test_writing_keeps_every_other_line(tmp_path):
    (tmp_path / ".env").write_text(
        "# a comment\nGEMINI_API_KEY=AIzaOLDOLDOLDOLDOLDOLDOLDOLDOLDOLD\nLLM_MODEL=gemini/x\n",
        encoding="utf-8",
    )
    write_key(tmp_path / ".env", GOOD)
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={GOOD}" in written
    assert written.count("GEMINI_API_KEY=") == 1
    assert "OLDOLD" not in written
    assert "# a comment" in written
    assert "LLM_MODEL=gemini/x" in written


def test_a_missing_env_is_seeded_from_the_example(tmp_path):
    (tmp_path / ".env.example").write_text(
        "# header\nGEMINI_API_KEY=\nRETRIEVAL_MODE=hybrid\n", encoding="utf-8"
    )
    write_key(tmp_path / ".env", GOOD)
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={GOOD}" in written
    assert "RETRIEVAL_MODE=hybrid" in written
    assert "# header" in written
    # The example is a template and must not be edited.
    assert GOOD not in (tmp_path / ".env.example").read_text(encoding="utf-8")


def test_a_bad_key_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError):
        write_key(tmp_path / ".env", "hunter2")
    assert not (tmp_path / ".env").exists()


def _local_client(app_settings):
    """A client the route will treat as the machine running the app."""
    from fastapi.testclient import TestClient

    from dubizzle_assistant.api.app import create_app

    return TestClient(create_app(app_settings), client=("127.0.0.1", 51234))


def test_a_caller_that_is_not_this_machine_is_turned_away(client):
    # The shared fixture presents as "testclient", which is exactly what the guard is for.
    assert client.post("/llm/key", json={"key": GOOD}).status_code == 403


def test_the_route_saves_the_key_and_never_sends_it_back(app_settings):
    with _local_client(app_settings) as c:
        bad = c.post("/llm/key", json={"key": "hunter2"})
        assert bad.status_code == 422
        assert "hunter2" not in bad.text

        ok = c.post("/llm/key", json={"key": GOOD})
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["saved"] is True
        assert GOOD not in ok.text, "the key must never come back out"
        assert body["key"].startswith("AIza") and body["key"].endswith("yyyy")

        # It landed in the temp file the settings point at, not the repository's own .env.
        written = app_settings.dotenv_path.read_text(encoding="utf-8")
        assert f"GEMINI_API_KEY={GOOD}" in written
        assert app_settings.dotenv_path != ROOT / ".env"

        # And the app stopped answering from the stand-in.
        assert c.get("/health").json()["llm"]["offline"] is False


def test_a_differently_named_env_file_is_the_one_written(tmp_path):
    """Passing a directory meant a custom name was ignored and the default file next door won."""
    target = tmp_path / "custom.env"
    write_key(target, GOOD)
    assert f"GEMINI_API_KEY={GOOD}" in target.read_text(encoding="utf-8")
    assert not (tmp_path / ".env").exists()
