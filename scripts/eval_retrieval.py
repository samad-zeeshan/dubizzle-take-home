"""
CLI: run the golden set under every retrieval mode and write docs/retrieval_eval.md.

    uv run python scripts/eval_retrieval.py            # structured, fts, hybrid (embeddings if the vector file exists and a key is set)
    uv run python scripts/eval_retrieval.py --modes hybrid fts
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.config import get_settings  # noqa: E402
from dubizzle_assistant.db import connect, init_db  # noqa: E402
from dubizzle_assistant.evaluation import MODES, evaluate, render  # noqa: E402
from dubizzle_assistant.services import embeddings  # noqa: E402
from dubizzle_assistant.services.inventory import load_inventory  # noqa: E402
from dubizzle_assistant.services.llm import build_embedder, build_llm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--modes", nargs="*", default=None, choices=MODES)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "retrieval_eval.md")
    ap.add_argument("--json", type=Path, default=None, help="also write the raw results as JSON")
    args = ap.parse_args()
    settings = get_settings()
    # A throwaway database so the evaluation never touches app.db.
    db = Path(tempfile.mkdtemp()) / "eval.db"
    init_db(db)
    conn = connect(db)
    load_inventory(conn, settings.inventory_path)
    listing_ids = [str(r[0]) for r in conn.execute("SELECT id FROM listings")]
    embeddings_ok, embeddings_reason = embeddings.available(
        model=settings.embedding_model, ids=listing_ids
    )
    modes = (
        tuple(args.modes)
        if args.modes
        else tuple(m for m in MODES if m != "embeddings" or embeddings_ok)
    )
    if "embeddings" in modes and not embeddings_ok:
        print(f"note: {embeddings_reason}")
    embedder = build_embedder(settings, build_llm(settings)) if "embeddings" in modes else None
    report = evaluate(conn, settings.inventory_path, modes, embedder)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report), encoding="utf-8", newline="\n")
    if args.json:
        args.json.write_text(
            json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
        )
    for m, s in report["summary"].items():
        print(
            f"{m:11s} passed {s['passed']}/{s['cases']}  precision@k {s['mean_precision_at_k']}  recall {s['mean_recall']}"
            + (f"  ({s['unavailable']})" if s["unavailable"] else "")
        )
    print(f"wrote {args.out}")
    conn.close()
    return (
        0
        if report["summary"].get("hybrid", {}).get("passed")
        == report["summary"].get("hybrid", {}).get("cases")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
