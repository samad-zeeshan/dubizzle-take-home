"""
POST /chat/stream: the same turn as /chat, with one Server-Sent Event per trace stage and one per streamed sentence.

Stage events show what the system is doing: "searching inventory", "12
matches, relaxed colour", "composing reply". Token events carry draft reply
text, already scrubbed, when the model supports streaming. The envelope at
the end holds the final reply, which may differ from the draft after the
grounding check.
"""

from __future__ import annotations

import asyncio
import json
import queue
import secrets
import sqlite3
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from dubizzle_assistant.api.deps import get_conn, get_settings_dep
from dubizzle_assistant.api.routers.chat import ChatRequest, prepare, store_idempotent
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services.agent import ChatUnavailableError, run_turn
from dubizzle_assistant.services.trace import TurnTrace

router = APIRouter(tags=["chat"])


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> StreamingResponse:
    prep = prepare(req, request, settings, conn, idempotency_key)

    async def events() -> AsyncIterator[str]:
        if "replay" in prep:
            yield _sse("envelope", prep["replay"])
            return
        q: queue.Queue[tuple[str, Any] | None] = queue.Queue()
        labeller = TurnTrace("", 0, "")

        def on_stage(record: dict[str, Any]) -> None:
            q.put(
                (
                    "stage",
                    {
                        "stage": record["stage"],
                        "label": labeller.label(record),
                        "at_ms": record.get("at_ms"),
                    },
                )
            )

        def on_token(text: str) -> None:
            q.put(("token", {"text": text}))

        def work() -> None:
            try:
                env = run_turn(
                    settings=settings,
                    conn=conn,
                    llm=prep["llm"],
                    user_id=prep["user_id"],
                    session_id=prep["session_id"],
                    message=prep["text"],
                    request_id=secrets.token_hex(6),
                    on_stage=on_stage,
                    embedder=getattr(request.app.state, "embedder", None),
                    on_token=on_token,
                )
                env["new_session"] = prep["new_session"]
                env["degraded"] = prep["degraded"]
                store_idempotent(conn, prep, env)
                q.put(("envelope", env))
            except ChatUnavailableError as e:
                request.app.state.llm_error = str(e)
                q.put(
                    ("error", {"status": e.status, "detail": str(e), "retry_after": e.retry_after})
                )
            except Exception as e:  # noqa: BLE001
                q.put(("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"}))
            finally:
                q.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                break
            yield _sse(item[0], item[1])

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
