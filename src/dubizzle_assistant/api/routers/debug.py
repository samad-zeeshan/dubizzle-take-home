"""
Debug endpoints, mounted only when DEBUG_ENDPOINTS is on: traces, the prompt inspector, config.

Traces are stored already redacted, and the prompt needs no redaction because
nothing sensitive is ever in it. The config view masks the key regardless.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings

router = APIRouter(prefix="/debug", tags=["debug"])


def _traces(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT turn, request_id, trace_json, created_at FROM turn_traces WHERE session_id = ? ORDER BY turn",
        (session_id,),
    ).fetchall()
    return [
        {
            "turn": r["turn"],
            "request_id": r["request_id"],
            "created_at": r["created_at"],
            **json.loads(r["trace_json"]),
        }
        for r in rows
    ]


@router.get("/turns/{session_id}")
def list_turns(
    session_id: str, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict[str, Any]]:
    out = []
    for t in _traces(conn, session_id):
        stages = t["stages"]
        out.append(
            {
                "turn": t["turn"],
                "request_id": t["request_id"],
                "created_at": t["created_at"],
                "total_ms": t.get("total_ms"),
                "stages": [s["stage"] for s in stages],
                "tools": [s.get("name") for s in stages if s["stage"] == "tool"],
                "llm_calls": sum(1 for s in stages if s["stage"] == "llm_call"),
                "intent": next((s.get("intent") for s in stages if s["stage"] == "reply"), None),
                "ablations_active": t.get("ablations_active", []),
            }
        )
    return out


@router.get("/turns/{session_id}/{turn}")
def get_turn(
    session_id: str, turn: int, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    for t in _traces(conn, session_id):
        if t["turn"] == turn:
            return t
    raise HTTPException(status_code=404, detail="no such turn")


@router.get("/prompt/{session_id}")
def prompt(session_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    traces = [
        t for t in _traces(conn, session_id) if any(s["stage"] == "prompt" for s in t["stages"])
    ]
    if not traces:
        raise HTTPException(status_code=404, detail="no prompt recorded for this session yet")
    last = traces[-1]
    stage = next(s for s in last["stages"] if s["stage"] == "prompt")
    blocks = stage.get("blocks", [])
    diff: list[str] = []
    if len(traces) > 1:
        prev = next(s for s in traces[-2]["stages"] if s["stage"] == "prompt").get("blocks", [])
        prev_dyn = "\n".join(b["text"] for b in prev if b["name"] != "static")
        cur_dyn = "\n".join(b["text"] for b in blocks if b["name"] != "static")
        diff = list(
            difflib.unified_diff(
                prev_dyn.splitlines(),
                cur_dyn.splitlines(),
                "previous turn",
                "this turn",
                lineterm="",
                n=1,
            )
        )
    return {
        "session_id": session_id,
        "turn": last["turn"],
        "blocks": [{"name": b["name"], "tokens": b["tokens"], "text": b["text"]} for b in blocks],
        "total_tokens_estimate": stage.get("total_tokens_estimate"),
        "history_messages": stage.get("history_messages"),
        "diff_vs_previous_turn": diff,
    }


@router.get("/config")
def config(settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    data = settings.model_dump(mode="json")
    data["gemini_api_key"] = "set" if settings.gemini_api_key else None
    data["llm_api_key"] = "set" if settings.llm_api_key else None
    data["ablations_active"] = settings.ablations_active
    return data
