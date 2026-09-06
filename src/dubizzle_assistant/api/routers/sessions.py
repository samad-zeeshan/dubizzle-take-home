"""Sessions: mint one, read it back with messages and context, export it with traces."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import memory
from dubizzle_assistant.services.trace import redact

router = APIRouter(prefix="/sessions", tags=["sessions"])


class NewSession(BaseModel):
    user_id: str


@router.post("")
def create(
    body: NewSession,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    now = settings.now()
    if not memory.get_user(conn, body.user_id):
        memory.identify_user(conn, now, user_id=body.user_id, name=body.user_id)
    return {"session_id": memory.create_session(conn, body.user_id, now), "user_id": body.user_id}


@router.get("/{session_id}")
def read(session_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    s = memory.get_session(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="no such session")
    ctx = memory.get_context(conn, session_id)
    return {"session": s, "messages": redact(memory.all_messages(conn, session_id)), "context": ctx}


def _render_markdown(
    session: dict[str, Any], messages: list[dict[str, Any]], traces: dict[int, dict[str, Any]]
) -> str:
    lines = [
        f"# Session {session['session_id']}",
        "",
        f"User: {session['user_id']}  ",
        f"Started: {session['created_at']}  ",
        f"Turns: {session['turn_counter']}",
        "",
    ]
    current = -1
    for m in messages:
        if int(m["turn"]) != current:
            current = int(m["turn"])
            lines.append(f"## Turn {current}")
            lines.append("")
        role = m["role"]
        if role == "user":
            lines.append(f"**User:** {m.get('content', '')}")
        elif role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(
                f"{tc['function']['name']}({tc['function'].get('arguments', '')})"
                for tc in m["tool_calls"]
                if isinstance(tc, dict) and tc.get("function")
            )
            lines.append(f"*Assistant calls:* `{calls}`")
        elif role == "assistant":
            lines.append(f"**Assistant:** {m.get('content', '')}")
        elif role == "tool":
            content = str(m.get("content", ""))
            lines.append(
                f"*Tool {m.get('name')} returned* `{content[:300]}{'...' if len(content) > 300 else ''}`"
            )
        lines.append("")
        t = traces.get(current)
        if t and role == "assistant" and not m.get("tool_calls"):
            stage_line = " -> ".join(
                f"{s['stage']}"
                + (f" {s.get('name')}" if s.get("name") else "")
                + (f" ({s.get('ms')} ms)" if s.get("ms") is not None else "")
                for s in t["stages"]
            )
            lines.append(f"<sub>trace: {stage_line}</sub>")
            g = next((s for s in t["stages"] if s["stage"] == "grounding"), None)
            if g and "checked" in g:
                lines.append(
                    f"<sub>grounding: {g.get('grounded')}/{g.get('checked')} figures sourced</sub>"
                )
            lines.append("")
    return "\n".join(lines)


@router.get("/{session_id}/export")
def export(
    session_id: str, format: str = "md", conn: sqlite3.Connection = Depends(get_conn)
) -> Any:
    """The conversation with its traces, redacted. This is the terminal log artefact."""
    s = memory.get_session(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="no such session")
    messages = redact(memory.all_messages(conn, session_id))
    trace_rows = conn.execute(
        "SELECT turn, trace_json FROM turn_traces WHERE session_id = ? ORDER BY turn", (session_id,)
    ).fetchall()
    traces = {r["turn"]: json.loads(r["trace_json"]) for r in trace_rows}
    if format == "json":
        return {"session": s, "messages": messages, "traces": traces}
    if format != "md":
        raise HTTPException(status_code=422, detail="format must be md or json")
    return PlainTextResponse(
        _render_markdown(s, messages, traces), media_type="text/markdown; charset=utf-8"
    )
