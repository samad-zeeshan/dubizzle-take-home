"""
CLI: build data/inventory.json and docs/enrichment_report.md from data/cars.xlsx.

    uv run python scripts/build_inventory.py            # regex and model knowledge only
    uv run python scripts/build_inventory.py --llm      # also run the batched LLM pass (needs a key)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.ingest.pipeline import build, write  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--xlsx", type=Path, default=ROOT / "data" / "cars.xlsx")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "inventory.json")
    ap.add_argument("--report", type=Path, default=ROOT / "docs" / "enrichment_report.md")
    ap.add_argument("--llm", action="store_true", help="run the batched LLM enrichment pass")
    ap.add_argument("--regex-only", action="store_true", help="explicit no-LLM build (the default)")
    ap.add_argument("--batch-size", type=int, default=12)
    args = ap.parse_args()

    enricher = None
    if args.llm and not args.regex_only:
        from dubizzle_assistant.ingest.enrich import make_enricher

        enricher = make_enricher(batch_size=args.batch_size)

    inventory = build(args.xlsx, enricher)
    write(args.out, args.report, inventory)
    n = len(inventory["listings"])
    priced = sum(
        1 for row in inventory["listings"] if row["fields"]["price_aed"]["value"] is not None
    )
    print(f"wrote {args.out} ({n} listings, {priced} with a cash price) and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
