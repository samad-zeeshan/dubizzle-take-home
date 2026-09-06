"""
CLI: one tool call and one plain call against the configured model, so a key or a local server can be checked before opening the UI.

    uv run python scripts/check_llm.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.config import get_settings  # noqa: E402
from dubizzle_assistant.services.llm import build_llm  # noqa: E402
from dubizzle_assistant.services.llm.base import LLMError  # noqa: E402
from dubizzle_assistant.services.tools import tool_schemas  # noqa: E402


def main() -> int:
    settings = get_settings()
    llm = build_llm(settings)
    if llm is None:
        print(
            "no model configured: set GEMINI_API_KEY or LLM_API_BASE in .env, or LLM_PROVIDER=mock"
        )
        return 1
    print(
        f"provider={settings.llm_provider} model={settings.llm_model} api_base={settings.llm_api_base or '-'} cassette={settings.llm_cassette_mode}"
    )
    msgs = [
        {"role": "system", "content": "You are a car inventory assistant. Use the tools."},
        {"role": "user", "content": "show me a honda"},
    ]
    t = time.monotonic()
    try:
        r = llm.complete(
            msgs,
            tool_schemas(),
            reasoning=settings.llm_reasoning,
            temperature=settings.temperature_for(settings.llm_model),
        )
    except LLMError as e:
        print(f"FAILED: {e}")
        return 1
    print(
        f"tool call round trip {int((time.monotonic() - t) * 1000)} ms, finish={r.finish_reason}, tools={[c.name for c in r.tool_calls]} args={[c.arguments for c in r.tool_calls]} tokens={r.usage}"
    )
    if not r.tool_calls:
        print(
            "WARNING: the model answered in text instead of calling search_inventory. Check the model id and tool support."
        )
    t = time.monotonic()
    r2 = llm.complete(
        [{"role": "user", "content": "Reply with the single word OK."}],
        None,
        reasoning=settings.llm_reasoning,
    )
    print(
        f"plain round trip {int((time.monotonic() - t) * 1000)} ms: {(r2.text or '').strip()[:40]!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
