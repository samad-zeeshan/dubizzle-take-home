"""
Read both worksheets, clean the HTML, drop duplicates, and assign stable ids.

The two sheets are different listings, not raw and clean copies of the same
rows. Only one car appears in both, so the merge is a union, not a join.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from dubizzle_assistant.text import ARABIC_RE

RAW_SHEET = "raw dataset"
CLEAN_SHEET = "cleaned dataset"

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_UNCLOSED_TAIL_RE = re.compile(r"<[^>]*$|&[a-zA-Z#0-9]*$")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_MULTI_NL_RE = re.compile(r"\n\s*\n+")
# Bullet glyphs the dealers use as list markers. Normalized to a plain bullet.
_BULLET_RE = re.compile(r"[•▪◦●✅✔️☑️➤➔→\u2022\u25aa\u2713\u2714]|\uFE0F|\u200f|\u200e|\ufffc|\u2060")


@dataclass
class Row:
    source_sheet: str
    source_row: int
    make: str
    model: str
    trim: str
    year: int
    title: str
    description_raw: str
    photo_url: str
    listing_id: int | None = None
    id: str = ""
    language: str = "en"
    truncated: bool = False
    dedup_note: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def clean_html(text: str) -> str:
    """Strip tags and entities while keeping line breaks as sentence boundaries."""
    out = _BR_RE.sub("\n", text)
    out = _TAG_RE.sub(" ", out)
    out = html.unescape(out)
    out = _BULLET_RE.sub(" ", out)
    out = out.replace("\t", " ")
    out = _WS_RE.sub(" ", out)
    out = "\n".join(line.strip() for line in out.split("\n"))
    out = _MULTI_NL_RE.sub("\n", out)
    return out.strip()


def detect_language(text: str) -> str:
    arabic = len(ARABIC_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    total = arabic + latin
    if total == 0:
        return "en"
    share = arabic / total
    if share > 0.6:
        return "ar"
    if share > 0.05:
        return "mixed"
    return "en"


def is_truncated(raw: str) -> bool:
    # The export clipped descriptions at about 2,047 characters, often mid tag.
    return len(raw) >= 1900 or bool(_UNCLOSED_TAIL_RE.search(raw.rstrip()))


def _cell(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


# Header spellings seen across marketplace exports. Matching is case-insensitive after punctuation is dropped.
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "make": ("make", "brand", "manufacturer", "car_make", "make_name"),
    "model": ("model", "car_model", "model_name"),
    "trim": ("trim", "variant", "version", "grade", "trim_level"),
    "year": ("year", "model_year", "manufacture_year", "year_of_manufacture"),
    "title": ("title", "listing_title", "ad_title", "heading"),
    "description": (
        "description",
        "desc",
        "details",
        "description_raw",
        "body",
        "text",
        "ad_description",
    ),
    "photo_url": ("photo_url", "photo", "image", "image_url", "picture", "photos", "thumbnail"),
    "listing_id": ("listing_id", "id", "ad_id", "ref", "reference"),
}
# Structured columns this dataset lacks but another might carry. They beat the text extractor.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "price_aed": ("price", "price_aed", "cash_price", "asking_price"),
    "monthly_aed": (
        "monthly",
        "monthly_aed",
        "installment",
        "instalment",
        "emi",
        "monthly_payment",
    ),
    "mileage_km": ("mileage", "mileage_km", "km", "kms", "kilometers", "kilometres", "odometer"),
    "exterior_color": ("color", "colour", "exterior_color", "exterior_colour", "ext_color"),
    "body_type": ("body_type", "body", "body_style", "category"),
    "fuel_type": ("fuel", "fuel_type"),
    "transmission": ("transmission", "gearbox"),
    "regional_spec": ("spec", "specs", "regional_spec"),
    "seats": ("seats", "seating"),
    "has_warranty": ("warranty", "has_warranty", "under_warranty"),
}
_HEADER_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def _header_key(h: str) -> str:
    return _HEADER_CLEAN_RE.sub("_", h.strip().lower()).strip("_")


def resolve_header(header: list[str]) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Map the core fields and optional columns to positions, and list the headers nothing claimed."""
    keys = [_header_key(h) for h in header]
    core: dict[str, int] = {}
    extra: dict[str, int] = {}
    claimed: set[int] = set()
    for table, out in ((HEADER_ALIASES, core), (COLUMN_ALIASES, extra)):
        for canon, names in table.items():
            for i, k in enumerate(keys):
                if k in names and i not in claimed:
                    out[canon] = i
                    claimed.add(i)
                    break
    unmapped = [h for i, h in enumerate(header) if i not in claimed and h]
    return core, extra, unmapped


def _sheet_kind(name: str, core: dict[str, int]) -> str:
    low = name.lower()
    if "clean" in low:
        return "cleaned"
    if "raw" in low:
        return "raw"
    return "cleaned" if "listing_id" in core else "raw"


def _int_or_none(text: str) -> int | None:
    try:
        return int(float(text))
    except ValueError:
        return None


def read_sheet(path: Path, sheet: str, kind: str | None = None) -> list[Row]:
    return read_sheet_with_report(path, sheet, kind)[0]


def read_sheet_with_report(
    path: Path, sheet: str, kind: str | None = None
) -> tuple[list[Row], dict[str, Any]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows_iter = ws.iter_rows(values_only=True)
    header = [_cell(h) for h in next(rows_iter, ())]
    core, extra, unmapped = resolve_header(header)
    kind = kind or _sheet_kind(sheet, core)
    out: list[Row] = []
    for n, values in enumerate(rows_iter, start=2):
        if all(v is None for v in values):
            continue

        def get(k: str, values: tuple[object, ...] = values) -> str:
            i = core.get(k)
            return _cell(values[i]) if i is not None and i < len(values) else ""

        raw_desc = get("description")
        lid = get("listing_id")
        row = Row(
            source_sheet=kind,
            source_row=n,
            # Mazda "3" and the DBX "707" arrive as ints from the workbook.
            make=get("make").lower(),
            model=get("model").lower(),
            trim=get("trim").lower() or "other",
            year=_int_or_none(get("year")) or 0,
            title=clean_html(get("title")),
            description_raw=raw_desc,
            photo_url=get("photo_url"),
            listing_id=_int_or_none(lid) if lid else None,
        )
        if lid and row.listing_id is None:
            row.extra["source_id"] = lid
        if not row.title:
            # Cards, search, and summaries all lean on the title, so a missing one is rebuilt from the columns.
            row.title = " ".join(p for p in (str(row.year or ""), row.make, row.model) if p).title()
            row.extra["title_synthesized"] = True
        for key, i in extra.items():
            v = _cell(values[i]) if i < len(values) else ""
            if v:
                row.extra[key] = v
        row.truncated = is_truncated(raw_desc)
        row.language = detect_language(row.title + " " + clean_html(raw_desc))
        out.append(row)
    wb.close()
    report = {
        "sheet": sheet,
        "kind": kind,
        "rows": len(out),
        "columns": {k: header[i] for k, i in core.items()},
        "optional_columns": {k: header[i] for k, i in extra.items()},
        "unmapped": unmapped,
    }
    return out, report


def merge_sheets(cleaned: list[Row], raw: list[Row]) -> tuple[list[Row], list[dict[str, object]]]:
    """Union both sheets. Cleaned keeps its ids, raw is deduped then numbered."""
    removed: list[dict[str, object]] = []
    for r in cleaned:
        r.id = f"C-{r.listing_id:03d}"

    seen_text: dict[tuple[str, str], Row] = {}
    kept_raw: list[Row] = []
    for r in raw:
        key = (r.title, r.description_raw)
        if key in seen_text:
            removed.append(
                {
                    "reason": "exact duplicate within raw",
                    "kept_row": seen_text[key].source_row,
                    "dropped_row": r.source_row,
                    "title": r.title,
                }
            )
            continue
        seen_text[key] = r
        kept_raw.append(r)

    cleaned_photos = {r.photo_url: r for r in cleaned if r.photo_url}
    final_raw: list[Row] = []
    for r in kept_raw:
        if r.photo_url in cleaned_photos:
            removed.append(
                {
                    "reason": "same listing in both sheets (photo_url), cleaned copy kept",
                    "kept_row": cleaned_photos[r.photo_url].id,
                    "dropped_row": r.source_row,
                    "title": r.title,
                }
            )
            continue
        final_raw.append(r)

    for n, r in enumerate(final_raw, start=1):
        r.id = f"R-{n:03d}"
    return cleaned + final_raw, removed


def resolve_sheets(names: list[str]) -> list[str]:
    """The two canonical sheets when present, otherwise every sheet in the workbook."""
    if CLEAN_SHEET in names and RAW_SHEET in names:
        return [CLEAN_SHEET, RAW_SHEET]
    return list(names)


def load_workbook_rows(
    path: Path,
) -> tuple[list[Row], list[dict[str, object]], list[dict[str, Any]]]:
    wb = load_workbook(path, read_only=True)
    names = resolve_sheets(wb.sheetnames)
    wb.close()
    cleaned: list[Row] = []
    raw: list[Row] = []
    reports: list[dict[str, Any]] = []
    taken: set[int] = set()
    for name in names:
        kind = "cleaned" if name == CLEAN_SHEET else "raw" if name == RAW_SHEET else None
        rows, rep = read_sheet_with_report(path, name, kind)
        reports.append(rep)
        for r in rows:
            # Two sheets can both number from 1; the second copy of an id is numbered with the raw rows.
            if (
                r.source_sheet == "cleaned"
                and r.listing_id is not None
                and r.listing_id not in taken
            ):
                taken.add(r.listing_id)
                cleaned.append(r)
            else:
                # Without a numeric id a row cannot keep one, so it is numbered with the raw rows.
                r.source_sheet = "raw"
                raw.append(r)
    merged, removed = merge_sheets(cleaned, raw)
    if not merged:
        raise ValueError(
            f"no listings found in {path.name}: sheets {names}; check the column mapping in the build report"
        )
    return merged, removed, reports


def load_all(path: Path) -> tuple[list[Row], list[dict[str, object]]]:
    rows, removed, _ = load_workbook_rows(path)
    return rows, removed
