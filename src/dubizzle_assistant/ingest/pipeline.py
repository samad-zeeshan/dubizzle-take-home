"""
Run the whole build: workbook in, inventory.json and the audit report out.

Idempotent and offline by default. The optional enrich step is the only part
that talks to an LLM, and it is run once by hand so the server never spends a
grader's quota at startup.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dubizzle_assistant.ingest import report as report_mod
from dubizzle_assistant.ingest.extract import Field, extract_all
from dubizzle_assistant.ingest.load import Row, clean_html, load_all
from dubizzle_assistant.ingest.sanitize import sanitize
from dubizzle_assistant.ingest.summarize import english_summary, keywords

Enricher = Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], list[dict[str, Any]], str]]

QUIRKS = [
    "There is no price column. Prices live in free text and most listings have none.",
    "The two sheets are different listings, not raw and clean versions of the same rows. One car overlaps.",
    "Cleaned Listing_ID 52 says 2015 in the year column and 2014 in the title. The column wins.",
    "Mazda model '3' and Aston Martin DBX trim '707' are integers in the workbook and are cast to text.",
    "Ten raw listings carry dubizzle's managed-inventory boilerplate. That block is the is_dubizzle_managed marker.",
    "The BYD Han L repeats '701KM' six times. It is battery range, not mileage, and is rejected as such.",
    "Dealer opening hours in descriptions include Sundays. They are removed and never used for booking.",
]


def _row_to_record(row: Row) -> dict[str, Any]:
    cleaned_html = clean_html(row.description_raw)
    san = sanitize(cleaned_html)
    fields, rejected = extract_all(row.make, row.model, row.title, san.clean)
    fields["is_dubizzle_managed"] = Field(
        san.is_dubizzle_managed,
        "regex",
        "dubizzle cars boilerplate present" if san.is_dubizzle_managed else None,
        0.95,
    )
    flags = {
        "is_dubizzle_managed": san.is_dubizzle_managed,
        "is_export_only": bool(fields["is_export_only"].value),
    }
    quality = (
        "minimal"
        if len(san.clean) < 40
        else "boilerplate"
        if san.has_boilerplate and len(san.clean) < 160
        else "ok"
    )
    return {
        "id": row.id,
        "source_sheet": row.source_sheet,
        "source_row": row.source_row,
        "make": row.make,
        "model": row.model,
        "trim": row.trim,
        "year": row.year,
        "title": row.title,
        "description_raw": cleaned_html,
        "description_clean": san.clean,
        "english_summary": english_summary(row.make, row.model, row.trim, row.year, fields, flags),
        "keywords_en": keywords(row.make, row.model, row.trim, row.title, san.clean, fields),
        "photo_url": row.photo_url,
        "language": row.language,
        "truncated": row.truncated,
        "description_quality": quality,
        "dealer_name": san.dealer_name,
        "dealer_contact": san.dealer_contact,
        "removed_sentences": san.removed_sentences,
        "fields": {k: v.as_dict() for k, v in fields.items()},
        "rejected": rejected,
    }


def _mark_shared_descriptions(records: list[dict[str, Any]]) -> None:
    # Three cleaned listings share one dealer paragraph that says nothing about any of them.
    counts = Counter(r["description_raw"] for r in records if len(r["description_raw"]) >= 40)
    for r in records:
        if counts[r["description_raw"]] > 1:
            r["description_quality"] = "boilerplate"


def build(xlsx: Path, enricher: Enricher | None = None) -> dict[str, Any]:
    rows, removed = load_all(xlsx)
    records = [_row_to_record(r) for r in rows]
    _mark_shared_descriptions(records)

    disagreements: list[dict[str, Any]] = []
    llm_model = None
    if enricher is not None:
        records, disagreements, llm_model = enricher(records)

    sha = hashlib.sha256(xlsx.read_bytes()).hexdigest()
    years = [r["year"] for r in records if r["year"]]
    meta = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "source_file": xlsx.name,
        "source_sha256": sha,
        "llm_model": llm_model,
        "counts": {
            "cleaned_read": sum(1 for r in rows if r.source_sheet == "cleaned"),
            "raw_read": sum(1 for r in rows if r.source_sheet == "raw") + len(removed),
            "cleaned_kept": sum(1 for r in records if r["source_sheet"] == "cleaned"),
            "raw_kept": sum(1 for r in records if r["source_sheet"] == "raw"),
            "makes": len({r["make"] for r in records}),
            "year_min": min(years),
            "year_max": max(years),
        },
        "removed": removed,
        "disagreements": disagreements,
        "quirks": QUIRKS,
    }
    return {"meta": meta, "listings": records}


def write(out_json: Path, out_report: Path, inventory: dict[str, Any]) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=1)
        f.write("\n")
    out_report.write_text(
        report_mod.render(inventory["listings"], inventory["meta"]), encoding="utf-8", newline="\n"
    )
