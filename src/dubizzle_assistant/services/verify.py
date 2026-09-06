"""
Optional second opinion: ask the model whether each claim in the reply is backed by the tool results.

Off by default because it doubles the calls per turn. When on, an unsupported
claim triggers one regeneration with the verdicts attached, and the verdicts
are recorded in the trace either way.
"""

from __future__ import annotations

import json
from typing import Any

from dubizzle_assistant.services.context import TurnContext
from dubizzle_assistant.services.llm.base import LLMClient, LLMError

PROMPT = (
    "You check a car assistant's reply against the data it was given. List each factual claim about a car (price, mileage, "
    "year, colour, spec, warranty, availability) and say whether the tool results support it. Return JSON only: "
    '{"verdicts": [{"claim": str, "supported": bool, "source": str}], "all_supported": bool}'
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "source": {"type": "string"},
                },
                "required": ["claim", "supported"],
            },
        },
        "all_supported": {"type": "boolean"},
    },
    "required": ["verdicts", "all_supported"],
}


def run(
    ctx: TurnContext,
    llm: LLMClient,
    reply: str,
    messages: list[dict[str, Any]],
    usage: dict[str, int],
) -> dict[str, Any] | None:
    evidence = json.dumps(
        [{"tool": t["name"], "result": t["result"]} for t in ctx.tool_results],
        ensure_ascii=False,
        default=str,
    )[:12000]
    with ctx.trace.stage("verify") as rec:
        try:
            resp = llm.complete(
                [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": f"Tool results:\n{evidence}\n\nReply:\n{reply}"},
                ],
                None,
                reasoning="low",
                response_schema=SCHEMA,
                purpose="verify",
                temperature=ctx.settings.temperature_for(ctx.settings.llm_model),
            )
        except LLMError as e:
            rec["error"] = str(e)
            return None
        for k in usage:
            usage[k] += resp.usage.get(k, 0)
        try:
            data = json.loads((resp.text or "{}").strip().strip("`").removeprefix("json"))
        except json.JSONDecodeError:
            rec["error"] = "verifier returned no JSON"
            return {
                "all_supported": True,
                "verdicts": [],
                "note": "unparseable verdict, treated as supported",
            }
        verdicts = data.get("verdicts") or []
        all_ok = bool(
            data.get("all_supported", not any(not v.get("supported", True) for v in verdicts))
        )
        rec.update(
            {
                "claims": len(verdicts),
                "unsupported": [v.get("claim") for v in verdicts if not v.get("supported", True)],
                "all_supported": all_ok,
            }
        )
    return {"all_supported": all_ok, "verdicts": verdicts}
