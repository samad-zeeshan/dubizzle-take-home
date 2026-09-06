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


def read_sheet(path: Path, sheet: str) -> list[Row]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows_iter = ws.iter_rows(values_only=True)
    header = [_cell(h).lower() for h in next(rows_iter)]
    idx = {name: i for i, name in enumerate(header)}
    out: list[Row] = []
    for n, values in enumerate(rows_iter, start=2):
        if all(v is None for v in values):
            continue

        def get(k: str, values: tuple[object, ...] = values) -> str:
            return _cell(values[idx[k]]) if k in idx else ""

        raw_desc = get("description")
        row = Row(
            source_sheet="cleaned" if sheet == CLEAN_SHEET else "raw",
            source_row=n,
            # Mazda "3" and the DBX "707" arrive as ints from the workbook.
            make=get("make").lower(),
            model=get("model").lower(),
            trim=get("trim").lower() or "other",
            year=int(float(get("year") or 0)),
            title=clean_html(get("title")),
            description_raw=raw_desc,
            photo_url=get("photo_url"),
            listing_id=int(float(get("listing_id"))) if get("listing_id") else None,
        )
        row.truncated = is_truncated(raw_desc)
        row.language = detect_language(row.title + " " + clean_html(raw_desc))
        out.append(row)
    wb.close()
    return out


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


def load_all(path: Path) -> tuple[list[Row], list[dict[str, object]]]:
    cleaned = read_sheet(path, CLEAN_SHEET)
    raw = read_sheet(path, RAW_SHEET)
    return merge_sheets(cleaned, raw)
