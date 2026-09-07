"""
CLI: embed every listing once and save the vectors, so the embeddings mode costs one call per query.

    uv run python scripts/build_embeddings.py          # needs GEMINI_API_KEY or LLM_API_BASE
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.config import get_settings  # noqa: E402
from dubizzle_assistant.services import embeddings  # noqa: E402
from dubizzle_assistant.services.llm.litellm_client import LiteLLMClient  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not (settings.gemini_api_key or settings.llm_local):
        print(
            "No model endpoint: set GEMINI_API_KEY or LLM_API_BASE. The hybrid mode works without embeddings."
        )
        return 1
    data = json.loads(settings.inventory_path.read_text(encoding="utf-8"))
    ids = [r["id"] for r in data["listings"]]
    texts = [
        f"{r['year']} {r['make']} {r['model']} {r['trim']}. {r['english_summary']} Keywords: {r['keywords_en']}"
        for r in data["listings"]
    ]
    client = LiteLLMClient(
        settings.llm_model,
        settings.gemini_api_key,
        api_base=settings.llm_api_base,
        api_base_key=settings.llm_api_key,
        local=settings.llm_local,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
    )
    vectors = client.embed_many(texts, batch_size=16)
    embeddings.save(ids, vectors, settings.embeddings_path, model=settings.embedding_model)
    print(
        f"wrote {settings.embeddings_path} ({len(ids)} x {len(vectors[0])}) and {settings.embeddings_path.with_suffix('.ids.json')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
