"""The one-command launcher: the mode it picks, the key it takes, and what it seeds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import run

from dubizzle_assistant.db import connect
from dubizzle_assistant.services import memory

ROOT = Path(__file__).resolve().parents[1]


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


def test_the_database_it_checks_is_the_one_it_will_use(tmp_path, monkeypatch):
    """Seeding is keyed on the database being absent, so it has to be the configured one."""
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.delenv("DB_FILE", raising=False)
    assert run.database_path() == tmp_path / "data" / "app.db"
    monkeypatch.setenv("DB_FILE", "data/other.db")
    assert run.database_path() == tmp_path / "data" / "other.db"


def test_the_seeded_customer_has_a_conversation_to_reopen(tmp_path):
    """The greeting says "last time you searched for ...", so that chat has to be openable.

    The seed used to write searches, likes and a booking but no messages, which left the
    conversation list empty for the one customer the demo is built around.
    """
    db = tmp_path / "seeded.db"
    env = {
        **os.environ,
        "DB_FILE": str(db),
        "LEADS_FILE": str(tmp_path / "leads.csv"),
        "BOOKINGS_FILE": str(tmp_path / "bookings.csv"),
        "LLM_PROVIDER": "mock",
    }
    done = subprocess.run(
        [sys.executable, "scripts/seed_demo_user.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr

    conn = connect(db)
    uid = conn.execute("SELECT user_id FROM users WHERE name_key = 'sara'").fetchone()[0]
    chats = memory.list_sessions(conn, uid)
    assert chats, "the seeded customer has no conversation to open"
    opening = chats[0]["preview"]
    assert opening, "the conversation has no opening line to label it with"
    # What the recall block promises has to be in the transcript it points at.
    text = " ".join(
        str(m.get("content") or "") for m in memory.all_messages(conn, chats[0]["session_id"])
    )
    assert "AED 150,000" in text
    assert "Velar" in text
