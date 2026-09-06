"""
Structured columns another workbook might carry: parsed once, marked as column provenance, and they beat the text extractor.
"""

from __future__ import annotations

import re

from dubizzle_assistant.ingest.extract import Field
from dubizzle_assistant.ingest.knowledge import COLOR_WORDS
from dubizzle_assistant.ingest.load import COLUMN_ALIASES
from dubizzle_assistant.normalize import canonical_body_type, parse_number

COLUMN_KEYS = frozenset(COLUMN_ALIASES)
_NUMBER_RE = re.compile(r"\d[\d,.]*(?:\s*[kK]\b)?")
_TRUE = {"yes", "y", "true", "1", "included", "under warranty"}
_FALSE = {"no", "n", "false", "0", "none", "-", "expired"}


def _color(text: str) -> str | None:
    low = text.lower()
    if low in COLOR_WORDS:
        return COLOR_WORDS[low]
    for word in sorted(COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", low):
            return COLOR_WORDS[word]
    return None


def column_field(key: str, raw: str) -> Field | None:
    """One cell to one Field, or None when the cell says nothing usable."""
    text = raw.strip()
    if not text:
        return None
    evidence = f"column value {text!r}"
    if key in ("price_aed", "monthly_aed", "mileage_km", "seats"):
        # Cells arrive as "AED 145,000" or "12,500 km"; the first number is the value.
        m = _NUMBER_RE.search(text)
        n = parse_number(m.group(0)) if m else None
        if n is None or n <= 0:
            return None
        return Field(int(round(n)), "column", evidence, 1.0)
    if key == "exterior_color":
        color = _color(text)
        return Field(color or text.lower(), "column", evidence, 1.0 if color else 0.8)
    if key == "body_type":
        canon = canonical_body_type(text)
        return Field(canon or text.lower(), "column", evidence, 1.0 if canon else 0.8)
    if key == "has_warranty":
        low = text.lower()
        if low in _FALSE:
            return Field(False, "column", evidence, 1.0)
        if low in _TRUE or "warranty" in low:
            return Field(True, "column", evidence, 1.0)
        return None
    return Field(text.lower(), "column", evidence, 0.9)


def apply_columns(fields: dict[str, Field], extra: dict[str, object]) -> list[str]:
    """Overlay column values on the extracted fields. Returns the keys the columns decided."""
    used: list[str] = []
    for key, raw in extra.items():
        if key not in COLUMN_KEYS:
            continue
        f = column_field(key, str(raw))
        if f is not None:
            fields[key] = f
            used.append(key)
    return used
