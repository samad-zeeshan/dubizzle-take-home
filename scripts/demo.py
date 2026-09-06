"""
CLI: replay the two rubric scenarios over HTTP against a running backend and print the transcript.

    uv run python scripts/demo.py                  # against BACKEND_URL (default http://127.0.0.1:8000)
    uv run python scripts/demo.py --scenario recall
    uv run python scripts/demo.py --out logs/demo_transcript.json

Recording and replay are server settings: start the backend with LLM_CASSETTE_MODE=record to
capture a real run, then LLM_CASSETTE_MODE=replay to reproduce it with no key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

SCENARIO_A = [
    "hi",
    "show me SUVs with warranty under AED 150k",
    "what's the mileage on the first one?",
    "does it have a warranty?",
    "compare it with the second one",
    "what about that first Honda?",
    "I like the velar",
    "book a viewing for the velar tomorrow at 9am",
    "book it for monday at 9am then",
    "yes please",
    "write me a python scraper for car prices",
    "is it cheaper on other sites?",
    "who won the 1998 world cup?",
]
SCENARIO_B = ["hi, it's Sara again", "what was I looking at last time?"]


def turn(
    client: httpx.Client,
    base: str,
    message: str,
    user_id: str | None,
    session_id: str | None,
    name: str,
) -> dict:
    body: dict = {"message": message, "name": name}
    if user_id:
        body["user_id"] = user_id
    if session_id:
        body["session_id"] = session_id
    r = client.post(
        f"{base}/chat", json=body, headers={"Idempotency-Key": str(uuid.uuid4())}, timeout=120
    )
    if r.status_code != 200:
        return {"error": r.status_code, "detail": r.text}
    return r.json()


def show(env: dict, message: str) -> None:
    if "error" in env:
        print(f"\n> {message}\n  !! {env['error']}: {env['detail'][:200]}")
        return
    tools = [s.get("name") for s in env["trace"]["stages"] if s["stage"] == "tool"]
    g = env.get("grounding") or {}
    res = env.get("resolver") or {}
    print(f"\n> {message}")
    print(
        f"  intent={env['intent']} tools={tools} resolver={res.get('rule')} -> {res.get('resolved')} cars={[c['id'] for c in env['cars']]} "
        f"grounded={g.get('grounded', '-')}/{g.get('checked', '-')} model={env.get('model')} {env.get('latency_ms')}ms"
    )
    if env.get("query_explain") and env["query_explain"].get("normalization"):
        print(f"  normalization: {env['query_explain']['normalization']}")
    print("  " + env["reply"].replace("\n", "\n  ")[:600])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", default=os.environ.get("BACKEND_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--scenario", choices=["all", "explore", "recall"], default="all")
    ap.add_argument("--name", default="Sara")
    ap.add_argument("--out", type=Path, default=ROOT / "logs" / "demo_transcript.json")
    ap.add_argument(
        "--pause", type=float, default=0.0, help="seconds between turns, useful against a live key"
    )
    args = ap.parse_args()
    # Replies carry markdown and the odd emoji; a redirected Windows stdout defaults to cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = httpx.Client()
    try:
        health = client.get(f"{args.base}/health", timeout=10).json()
    except httpx.HTTPError as e:
        print(
            f"backend not reachable at {args.base}: {e}\nstart it with: uv run uvicorn main:app --reload"
        )
        return 1
    print(
        f"backend ok: provider={health['llm']['provider']} model={health['llm']['model']} cassette={health['llm']['cassette_mode']} retrieval={health['retrieval_mode']}"
    )
    transcript: list[dict] = []
    user_id = None
    if args.scenario in ("all", "explore"):
        print("\n=== Scenario A: exploring, memory, booking, guardrails ===")
        session_id = None
        for m in SCENARIO_A:
            env = turn(client, args.base, m, user_id, session_id, args.name)
            show(env, m)
            transcript.append({"scenario": "A", "message": m, "envelope": env})
            if "error" not in env:
                user_id, session_id = env["user_id"], env["session_id"]
            time.sleep(args.pause)
        if user_id:
            prof = client.get(f"{args.base}/users/{user_id}/profile").json()
            print(
                f"\n  profile after A: prefs={prof.get('preferences')} likes={[c['id'] for c in prof.get('liked_cars', [])]} bookings={[b['ref'] for b in prof.get('upcoming_bookings', [])]}"
            )
    if args.scenario in ("all", "recall"):
        print("\n=== Scenario B: a brand new session, same person ===")
        session_id = None
        for m in SCENARIO_B:
            env = turn(client, args.base, m, user_id, session_id, args.name)
            show(env, m)
            transcript.append({"scenario": "B", "message": m, "envelope": env})
            if "error" not in env:
                user_id, session_id = env["user_id"], env["session_id"]
                if m == SCENARIO_B[0]:
                    print(
                        f"  new_session={env['new_session']} memory.read:\n    "
                        + str(env["memory"]["read"]).replace("\n", "\n    ")
                    )
            time.sleep(args.pause)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(transcript, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8",
        newline="\n",
    )
    errors = sum(1 for t in transcript if "error" in t["envelope"])
    ungrounded = sum(
        len((t["envelope"].get("grounding") or {}).get("ungrounded", []))
        for t in transcript
        if "error" not in t["envelope"]
    )
    print(
        f"\nturns={len(transcript)} errors={errors} ungrounded_figures={ungrounded} transcript={args.out}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
