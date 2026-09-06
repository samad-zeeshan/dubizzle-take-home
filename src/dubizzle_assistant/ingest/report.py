"""Write the enrichment audit report so the data work can be reviewed without running anything."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

FIELD_ORDER = [
    "price_aed",
    "monthly_aed",
    "price_vat_status",
    "down_payment_pct",
    "mileage_km",
    "is_brand_new",
    "exterior_color",
    "interior_color",
    "body_type",
    "regional_spec",
    "fuel_type",
    "transmission",
    "seats",
    "has_warranty",
    "warranty_text",
    "service_contract",
    "is_export_only",
    "is_dubizzle_managed",
]


def _pct(n: int, total: int) -> str:
    return f"{n} ({100 * n // max(total, 1)}%)"


def render(listings: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    total = len(listings)
    lines: list[str] = []
    lines.append("# Inventory enrichment report\n")
    lines.append(
        f"Generated {meta['generated_at']} from `{meta['source_file']}` (sha256 {meta['source_sha256'][:12]})."
    )
    lines.append(
        f"LLM enrichment: {'yes, ' + meta['llm_model'] if meta.get('llm_model') else 'not run (regex and model knowledge only)'}.\n"
    )

    if meta.get("sheets"):
        lines.append("## Sheets and columns\n")
        lines.append("| sheet | kind | rows | core columns | optional columns | unmapped |")
        lines.append("|---|---|---|---|---|---|")
        for sh in meta["sheets"]:
            core = ", ".join(f"{k}={v}" for k, v in sh["columns"].items()) or "none"
            opt = ", ".join(f"{k}={v}" for k, v in sh["optional_columns"].items()) or "none"
            lines.append(
                f"| {sh['sheet']} | {sh['kind']} | {sh['rows']} | {core} | {opt} | {', '.join(sh['unmapped']) or 'none'} |"
            )
        lines.append(
            f"\n{meta['counts'].get('column_fields', 0)} field values came straight from columns and outrank the text extractor.\n"
        )
    lines.append("## Rows\n")
    c = meta["counts"]
    lines.append("| stage | cleaned sheet | raw sheet |")
    lines.append("|---|---|---|")
    lines.append(f"| read from workbook | {c['cleaned_read']} | {c['raw_read']} |")
    lines.append(f"| kept after dedup | {c['cleaned_kept']} | {c['raw_kept']} |")
    lines.append(
        f"\nTotal listings: **{total}**, {c['makes']} makes, years {c['year_min']} to {c['year_max']}.\n"
    )
    if meta["removed"]:
        lines.append("### Duplicates removed\n")
        lines.append("| reason | kept | dropped row | title |")
        lines.append("|---|---|---|---|")
        for r in meta["removed"]:
            lines.append(
                f"| {r['reason']} | {r['kept_row']} | {r['dropped_row']} | {r['title'][:70]} |"
            )
        lines.append("")

    lines.append("## Field coverage\n")
    lines.append("| field | known | column | regex | inferred | derived | llm | override |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in FIELD_ORDER:
        known = 0
        src: Counter[str] = Counter()
        for row in listings:
            fld = row["fields"].get(f)
            if fld and fld["value"] is not None and fld["value"] is not False:
                known += 1
                src[fld["source"]] += 1
        lines.append(
            f"| {f} | {_pct(known, total)} | "
            + " | ".join(
                str(src.get(s, 0))
                for s in ("column", "regex", "inferred", "derived", "llm", "override")
            )
            + " |"
        )
    lines.append("")

    lines.append("## Price picture\n")
    cash = sum(1 for row in listings if row["fields"]["price_aed"]["value"] is not None)
    monthly_only = sum(
        1
        for row in listings
        if row["fields"]["price_aed"]["value"] is None
        and row["fields"]["monthly_aed"]["value"] is not None
    )
    lines.append(f"- Cash price stated: {_pct(cash, total)}")
    lines.append(f"- Monthly instalment only: {_pct(monthly_only, total)}")
    lines.append(f"- No price at all: {_pct(total - cash - monthly_only, total)}\n")

    lines.append("## Rejected numbers\n")
    lines.append(
        "Figures that looked like a price or an odometer reading but were rejected by context.\n"
    )
    lines.append("| listing | value | reason | snippet |")
    lines.append("|---|---|---|---|")
    n = 0
    for row in listings:
        for r in row.get("rejected", []):
            lines.append(
                f"| {row['id']} | {r['value']:,.0f} | {r['reason']} | {r['snippet'][:90].replace('|', '/')} |"
            )
            n += 1
    if n == 0:
        lines.append("| | | none | |")
    lines.append("")

    if meta.get("disagreements"):
        lines.append("## Regex versus LLM disagreements\n")
        lines.append("| listing | field | regex | llm | resolution |")
        lines.append("|---|---|---|---|---|")
        for d in meta["disagreements"]:
            lines.append(
                f"| {d['id']} | {d['field']} | {d['regex']} | {d['llm']} | {d['resolution']} |"
            )
        lines.append("")

    lines.append("## Flags\n")

    def ids(pred: Callable[[dict[str, Any]], bool]) -> str:
        found = [row["id"] for row in listings if pred(row)]
        return f"{len(found)}: " + ", ".join(found) if found else "0"

    lines.append(
        f"- dubizzle managed boilerplate: {ids(lambda row: row['fields']['is_dubizzle_managed']['value'])}"
    )
    lines.append(f"- export only: {ids(lambda row: row['fields']['is_export_only']['value'])}")
    lines.append(f"- brand new: {ids(lambda row: row['fields']['is_brand_new']['value'])}")
    lines.append(f"- Arabic only: {ids(lambda row: row['language'] == 'ar')}")
    lines.append(f"- mixed language: {ids(lambda row: row['language'] == 'mixed')}")
    lines.append(f"- truncated description: {ids(lambda row: row['truncated'])}")
    lines.append(
        f"- minimal description: {ids(lambda row: row['description_quality'] == 'minimal')}"
    )
    lines.append(
        f"- boilerplate description: {ids(lambda row: row['description_quality'] == 'boilerplate')}"
    )
    lines.append(
        f"- contact details stripped: {ids(lambda row: any(row['dealer_contact'].values()))}"
    )
    lines.append("")

    lines.append("## Known quirks\n")
    for q in meta.get("quirks", []):
        lines.append(f"- {q}")
    lines.append("")
    return "\n".join(lines)
