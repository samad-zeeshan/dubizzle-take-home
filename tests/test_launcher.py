"""The one-command launcher: picking a mode, and taking a key without leaking it."""

from __future__ import annotations

import run


def _fake_key() -> str:
    return "AIza" + "x" * 32


def test_set_key_writes_the_file_without_echoing_the_key(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text(
        "GEMINI_API_KEY=\nLLM_PROVIDER=litellm\nRETRIEVAL_MODE=hybrid\n", encoding="utf-8"
    )
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run.getpass, "getpass", lambda *_a, **_k: _fake_key())

    assert run.set_key() == 0
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={_fake_key()}" in written
    # The rest of the example file is carried over, not thrown away.
    assert "LLM_PROVIDER=litellm" in written
    assert "RETRIEVAL_MODE=hybrid" in written
    # Nothing prints the secret back at the person who just hid it.
    assert _fake_key() not in capsys.readouterr().out


def test_set_key_replaces_an_existing_key_and_keeps_the_rest(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=AIzaOLDOLDOLDOLDOLDOLDOLDOLDOLDOLD\nLLM_MODEL=gemini/x\n", encoding="utf-8"
    )
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run.getpass, "getpass", lambda *_a, **_k: _fake_key())

    assert run.set_key() == 0
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OLDOLD" not in written
    assert written.count("GEMINI_API_KEY=") == 1
    assert "LLM_MODEL=gemini/x" in written


def test_a_key_that_is_not_a_key_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run.getpass, "getpass", lambda *_a, **_k: "hunter2")
    assert run.set_key() == 1
    assert not (tmp_path / ".env").exists()


def test_pressing_enter_leaves_everything_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run.getpass, "getpass", lambda *_a, **_k: "   ")
    assert run.set_key() == 0
    assert not (tmp_path / ".env").exists()


def test_the_mode_follows_whether_a_key_is_present(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert run.gemini_key_present() is False
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={_fake_key()}\n", encoding="utf-8")
    assert run.gemini_key_present() is True
    # An empty assignment is not a key, which is what .env.example ships with.
    (tmp_path / ".env").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    assert run.gemini_key_present() is False
