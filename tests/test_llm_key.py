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


class _Reachable:
    """Stands in for a provider that accepts the key, so no test touches the network."""

    model = "gemini/gemini-3.5-flash-lite"

    def complete(self, *_a, **_k):
        return None


class _Rejecting:
    model = "gemini/gemini-3.5-flash-lite"

    def complete(self, *_a, **_k):
        raise RuntimeError("401 API key not valid")


def _provider(monkeypatch, client):
    from dubizzle_assistant.api.routers import health

    monkeypatch.setattr(health, "build_llm", lambda _s: client)
    monkeypatch.setattr(health, "build_embedder", lambda _s, _l: None)


def test_a_key_with_a_null_byte_is_refused_and_nothing_is_written(app_settings, monkeypatch):
    """isspace() missed a null byte, so it reached os.environ and took the process with it."""
    _provider(monkeypatch, _Reachable())
    with _local_client(app_settings) as c:
        before = app_settings.dotenv_path.read_bytes() if app_settings.dotenv_path.exists() else b""
        r = c.post("/llm/key", json={"key": "AIza" + "x" * 30 + chr(0)})
        assert r.status_code == 422
        after = app_settings.dotenv_path.read_bytes() if app_settings.dotenv_path.exists() else b""
        assert after == before, "a refused key must not reach the file"


def test_an_absurdly_long_key_is_refused(app_settings, monkeypatch):
    """Two megabytes of it was written to .env before anything objected."""
    _provider(monkeypatch, _Reachable())
    with _local_client(app_settings) as c:
        r = c.post("/llm/key", json={"key": "A" * 2_000_000})
        assert r.status_code == 422
        if app_settings.dotenv_path.exists():
            assert app_settings.dotenv_path.stat().st_size < 100_000


def test_a_key_the_provider_rejects_changes_nothing(app_settings, monkeypatch):
    """It used to save, swap the client, report success, then answer 503 to every turn."""
    _provider(monkeypatch, _Rejecting())
    with _local_client(app_settings) as c:
        working = c.post("/chat", json={"message": "hello"})
        assert working.status_code == 200

        r = c.post("/llm/key", json={"key": GOOD})
        assert r.status_code == 422
        assert "rejected" in r.text

        still = c.post("/chat", json={"message": "hello again"})
        assert still.status_code == 200, "a bad key must not take chat down with it"
        if app_settings.dotenv_path.exists():
            assert GOOD not in app_settings.dotenv_path.read_text(encoding="utf-8")


def test_the_route_saves_the_key_and_never_sends_it_back(app_settings, monkeypatch):
    _provider(monkeypatch, _Reachable())
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


def test_a_differently_named_env_file_is_the_one_written(tmp_path):
    """Passing a directory meant a custom name was ignored and the default file next door won."""
    target = tmp_path / "custom.env"
    write_key(target, GOOD)
    assert f"GEMINI_API_KEY={GOOD}" in target.read_text(encoding="utf-8")
    assert not (tmp_path / ".env").exists()
