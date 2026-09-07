"""
CLI: run one fixed four-turn conversation against a model and print what it did, so local models can be compared.

    uv run python scripts/probe_local.py                       # the model in .env
    uv run python scripts/probe_local.py openai/google/gemma-4-12b openai/qwen/qwen3-4b-2507

Runs in process with a throwaway database, so it never touches the real one.
Load the model in LM Studio first: `lms load <id> --context-length 16384 --gpu max`.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from dubizzle_assistant.api.app import create_app  # noqa: E402
from dubizzle_assistant.config import DUBAI, Settings  # noqa: E402

# A Saturday afternoon, so "next monday" is two days out and inside the booking horizon.
NOW = datetime(2026, 9, 5, 14, 30, tzinfo=DUBAI)
TURNS = [
    ("show me hondas", lambda e: [c["id"] for c in e["cars"]] == ["R-078"]),
    ("what's the mileage on that first honda?", lambda e: "79,000" in e["reply"]),
    ("book it for next monday at 10am", lambda e: bool(e.get("pending_booking"))),
    ("yes confirm", lambda e: "BK-" in e["reply"]),
    ("show me the range rover velar", lambda e: [c["id"] for c in e["cars"]] == ["C-003"]),
    (
        "anything similar to the velar?",
        lambda e: bool(e["cars"]) and "C-003" not in [c["id"] for c in e["cars"]],
    ),
]


def probe(model: str | None) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="probe_"))
    overrides: dict[str, Any] = {
        "db_file": tmp / "app.db",
        "leads_file": tmp / "leads.csv",
        "bookings_file": tmp / "bookings.csv",
        "outbox_dir": tmp / "outbox",
        "logs_dir": tmp / "logs",
        "llm_cassette_mode": "off",
        "rate_limit_per_min": 1000,
        "daily_llm_budget": 100000,
        "demo_now": NOW,
        "log_level": "WARNING",
    }
    if model:
        overrides["llm_model"] = model
    settings = Settings(**overrides)
    print(
        f"\n=== {settings.llm_model}  structured={settings.use_structured_reply} max_tokens={settings.effective_max_tokens}"
    )
    passed = 0
    with TestClient(create_app(settings)) as client:
        sid = uid = None
        for text, check in TURNS:
            body: dict[str, Any] = {"message": text}
            if sid:
                body["session_id"] = sid
            if uid:
                body["user_id"] = uid
            t0 = time.monotonic()
            r = client.post("/chat", json=body)
            ms = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                print(f"  FAIL {ms:>6} ms  {text!r}: {r.status_code} {r.text[:160]}")
                continue
            e = r.json()
            sid, uid = e.get("session_id") or sid, e.get("user_id") or uid
            tools = [s["name"] for s in e["trace"]["stages"] if s.get("stage") == "tool"]
            g = e.get("grounding") or {}
            ok = bool(check(e))
            passed += ok
            print(
                f"  {'ok  ' if ok else 'MISS'} {ms:>6} ms  {text!r:44} tools={tools} grounded={g.get('grounded')}/{g.get('checked')}"
            )
            print(f"       {e['reply'][:110]!r}")
    print(f"  {passed}/{len(TURNS)} expectations met")


def main() -> int:
    # Replies carry markdown and the odd emoji; a redirected Windows stdout defaults to cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    models = sys.argv[1:] or [None]
    for m in models:
        probe(m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
