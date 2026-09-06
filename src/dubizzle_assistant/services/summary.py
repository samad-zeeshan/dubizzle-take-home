"""
Rolling session summary: turns that fall out of the history window collapse into one block.

One model call every few turns keeps long sessions cheap and keeps the early
part of a conversation available to the model. The block is stored in the
session context and shows up in the prompt inspector like any other block.
"""

from __future__ import annotations

import json
from typing import Any

from dubizzle_assistant.services import memory
from dubizzle_assistant.services.context import TurnContext
from dubizzle_assistant.services.llm.base import LLMClient, LLMError

PROMPT = (
    "Summarise the earlier part of this car-shopping conversation for the assistant's own use. Keep it under 120 words. "
    "Keep listing ids, budgets, preferences, cars the user liked or rejected, and any booking. Plain sentences, no advice, "
    "no phone numbers or links. If there is a previous summary, fold it in."
)


def due(ctx: TurnContext, summary_through_turn: int) -> int | None:
    """Return the cutoff turn to summarise through, or None when nothing new has left the window."""
    s = ctx.settings
    cutoff = ctx.turn - s.history_turns
    if ctx.turn < s.summary_after_turns or cutoff <= summary_through_turn:
        return None
    if cutoff - summary_through_turn < max(2, s.summary_after_turns // 2):
        return None
    return cutoff


def maybe_update(
    ctx: TurnContext, llm: LLMClient, previous: str | None, summary_through_turn: int
) -> dict[str, Any] | None:
    cutoff = due(ctx, summary_through_turn)
    if cutoff is None:
        return None
    rows = ctx.conn.execute(
        "SELECT turn, role, blob_json FROM messages WHERE session_id = ? AND turn > ? AND turn <= ? ORDER BY id",
        (ctx.session_id, summary_through_turn, cutoff),
    ).fetchall()
    lines: list[str] = []
    for r in rows:
        blob = json.loads(r["blob_json"])
        if (
            r["role"] in ("user", "assistant")
            and isinstance(blob.get("content"), str)
            and blob["content"].strip()
        ):
            lines.append(f"{r['role']}: {blob['content'][:400]}")
    if not lines:
        return None
    text = (
        (f"Previous summary:\n{previous}\n\n" if previous else "")
        + "Conversation:\n"
        + "\n".join(lines)
    )
    with ctx.trace.stage("summary", through_turn=cutoff, messages=len(lines)) as rec:
        try:
            resp = llm.complete(
                [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
                None,
                reasoning="minimal",
                purpose="summary",
                temperature=ctx.settings.temperature_for(ctx.settings.llm_model),
            )
        except LLMError as e:
            rec["error"] = str(e)
            return None
        summary = (resp.text or "").strip()
        rec["chars"] = len(summary)
        rec["tokens"] = resp.usage
    if not summary:
        return None
    memory.save_context(
        ctx.conn,
        ctx.session_id,
        shown=ctx.shown,
        focus_id=ctx.focus_id,
        pending_booking=ctx.pending_booking,
        summary_text=summary,
        summary_through_turn=cutoff,
    )
    ctx.note_write("session_context", "summary", through_turn=cutoff)
    return {"through_turn": cutoff, "summary": summary}
