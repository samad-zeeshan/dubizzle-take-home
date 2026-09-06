"""
Pull structured fields out of seller text with regexes, each with its evidence.

The same number can be a price, a salary requirement, or an RTA fee depending
on the words around it, and "701KM" on the BYD is battery range. Every value
therefore carries the snippet it came from and a confidence, and null is the
honest answer when the words do not settle it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from dubizzle_assistant.ingest.knowledge import (
    BODY_TYPE_BY_MODEL,
    BODY_WORDS_STRONG,
    BODY_WORDS_WEAK,
    COLOR_FALSE_FRIENDS,
    COLOR_WORDS,
    ELECTRIC_MODELS,
    EXPORT_ONLY_RE,
    REGIONAL_SPEC_PATTERNS,
)
from dubizzle_assistant.normalize import normalize_digits, parse_number


@dataclass
class Field:
    value: Any
    source: str  # column, regex, inferred, derived, llm, override
    evidence: str | None = None
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def null(source: str = "regex") -> Field:
    return Field(None, source, None, 0.0)


# Comma or dot grouped thousands first, then space grouped, then a plain run.
# Plain runs come last so "2024 11,000 KM" yields 11,000 and not "2024 11,000".
NUM = r"(?:\d{1,3}(?:[,\.]\d{3})+(?:\.\d{1,2})?|\d{1,3}(?: \d{3})+|\d+(?:\.\d+)?)"
CUR = r"(?:aed|dhs|dirhams?|درهم)"

MONEY_RE = re.compile(rf"(?:{CUR}\s*[:#]?\s*({NUM})|({NUM})\s*/?-?\s*{CUR})", re.I)
BARE_MONTHLY_RE = re.compile(
    rf"({NUM})\s*(?:aed|dhs)?\s*(?:/\s*mo(?:nth)?\b|per\s+month|monthl?y|monthy|p\.?\s?m\b|p/m|شهري)",
    re.I,
)
MONTHLY_CTX = re.compile(
    r"/\s*mo(?:nth)?\b|\bper\s+month\b|\bmonthl?y\b|\bmonthy\b|\bp\.?\s?m\b|\bp/m\b|\binstal+ment|\ba month\b|شهري",
    re.I,
)
DECOY_CTX = re.compile(
    r"salary|evaluation|\brta\b|insurance|\bfees?\b|report|deposit|registration|wps|discount|saving|cost of|servic|maintenance|charge",
    re.I,
)
PRICE_CTX = re.compile(
    r"price|cash|selling|offer|payment\s*:|السعر|reduced|asking|\bfor\b|/-|option\s*\d", re.I
)

MILEAGE_UNIT_RE = re.compile(rf"({NUM})\s*(?:km|kms|kilometers?|كم)\b(?!\s*/\s*[hs])", re.I)
MILEAGE_LABEL_RE = re.compile(
    rf"(?:mileage|odometer|driven|العداد|ممشى)\s*(?:\(kms?\))?\s*[:\-]?\s*(?:just|only|approx\.?|around|about)?\s*({NUM})\b"
    rf"|\bkm\s*-\s*({NUM})\b",
    re.I,
)
MILEAGE_KEYWORDS = re.compile(
    r"mileage|odometer|driven|\bonly\b|\bdone\b|العداد|ممشى|\bkm\b\s*-", re.I
)
MILEAGE_REJECT_BEFORE = re.compile(
    r"range|warranty|until|untill|till|valid|service|next|last|\bor\b|years?|0\s*-\s*100|speed|up to|contract|free|per\b|top",
    re.I,
)
MILEAGE_REJECT_AFTER = re.compile(
    r"^\s*(?:\(?kms?\)?\s*)?(?:range|/h|/s|\bor\b|warranty|per\b|driving)", re.I
)

BRAND_NEW_RE = re.compile(
    r"(?<!like )(?<!like a )\bbrand\s*new\b(?!\s*(?:tyres?|tires?|batter))|\bzero\s*km\b|(?<![\d.])0\s*-?\s*kms?\b|\b0km\b",
    re.I,
)
WARRANTY_RE = re.compile(r"warrant|ضمان", re.I)
NO_WARRANTY_RE = re.compile(r"\bno\s+warranty|without\s+warranty|بدون ضمان", re.I)
SERVICE_CONTRACT_RE = re.compile(r"service\s+(?:contract|package|plan)|عقد صيانة", re.I)
VAT_EXCL_RE = re.compile(
    r"exclu\w*\s+of\s+(?:5\s*%\s*)?vat|excludes?\s+(?:5\s*%\s*)?vat|plus\s+(?:applicable\s+)?(?:government\s+)?(?:fees\s+and\s+)?vat|\+\s*vat|excl\.?\s*vat",
    re.I,
)
VAT_INCL_RE = re.compile(r"includ\w*\s+(?:5\s*%\s*)?vat|inclusive\s+of\s+vat|incl\.?\s*vat", re.I)
DOWN_PAYMENT_RE = re.compile(r"(\d{1,2})\s*%\s*(?:down|dp\b)", re.I)
SEATS_RE = re.compile(r"\b([2-9])\s*[- ]?seat", re.I)
FUEL_PATTERNS: list[tuple[str, str]] = [
    (r"\belectric\b|\bev\b|\bkwh\b|fully electric", "electric"),
    (r"\bhybrid\b|e performance|e-performance|phev", "hybrid"),
    (r"\bdiesel\b|ديزل", "diesel"),
    (r"\bpetrol\b|\bgasoline\b|بنزين", "petrol"),
]
TRANSMISSION_PATTERNS: list[tuple[str, str]] = [
    (r"\bmanual\b|\bstd\s*-\s*manual|عادي|مانيوال", "manual"),
    (r"\bautomatic\b|\bauto\b|\bdsg\b|\btiptronic\b|\d-?speed|أوتوماتيك|اوتوماتيك", "automatic"),
]


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    return " ".join(text[max(0, start - pad) : end + pad].split())


_BOUNDARY_RE = re.compile(r"[!?\n|•]|\.\s")


def _window_after(text: str, pos: int, limit: int = 22) -> str:
    """Text after pos up to the next digit or sentence break, so a neighbour's context is not borrowed."""
    tail = text[pos : pos + limit]
    cuts = [m.start() for m in (re.search(r"\d", tail), _BOUNDARY_RE.search(tail)) if m]
    return tail[: min(cuts)] if cuts else tail


def _window_before(text: str, pos: int, limit: int = 14) -> str:
    head = text[max(0, pos - limit) : pos]
    starts = [m.end() for m in re.finditer(r"\d", head)] + [
        m.end() for m in _BOUNDARY_RE.finditer(head)
    ]
    return head[max(starts) :] if starts else head


def extract_prices(text: str) -> tuple[Field, Field, list[dict[str, Any]]]:
    """Return (price_aed, monthly_aed, rejected) from one text."""
    t = normalize_digits(text)
    totals: list[tuple[float, float, str]] = []
    monthlies: list[tuple[float, str]] = []
    rejected: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    for m in BARE_MONTHLY_RE.finditer(t):
        v = parse_number(m.group(1))
        if v is not None and 100 <= v <= 60_000:
            monthlies.append((v, _snippet(t, m.start(), m.end())))
            seen_spans.add((m.start(1), m.end(1)))

    for m in MONEY_RE.finditer(t):
        g = 1 if m.group(1) else 2
        span = (m.start(g), m.end(g))
        if span in seen_spans:
            continue
        v = parse_number(m.group(g))
        if v is None:
            continue
        after = _window_after(t, m.end())
        before = _window_before(t, m.start())
        snippet = _snippet(t, m.start(), m.end())
        if MONTHLY_CTX.search(after) or MONTHLY_CTX.search(before):
            if 100 <= v <= 60_000:
                monthlies.append((v, snippet))
            continue
        # Digit-bounded on both sides so a neighbouring fee cannot veto the real price.
        ctx = _window_before(t, m.start(), 28) + " " + _window_after(t, m.end(), 28)
        if DECOY_CTX.search(ctx):
            rejected.append({"value": v, "reason": "decoy context", "snippet": snippet})
            continue
        if not 15_000 <= v <= 6_000_000:
            rejected.append({"value": v, "reason": "out of price range", "snippet": snippet})
            continue
        conf = 0.9 if PRICE_CTX.search(ctx) else 0.7
        totals.append((v, conf, snippet))

    price = null()
    if totals:
        # Highest confidence wins, then the largest figure: a cash total beats a leftover fee.
        v, conf, snip = sorted(totals, key=lambda x: (x[1], x[0]), reverse=True)[0]
        price = Field(int(v), "regex", snip, conf)
    monthly = null()
    if monthlies:
        # Dealers quote the 20%-down plan as the headline; the smallest figure is that one.
        v, snip = sorted(monthlies, key=lambda x: x[0])[0]
        monthly = Field(int(v), "regex", snip, 0.85)
    if price.value is not None and monthly.value is not None and monthly.value * 12 > price.value:
        rejected.append(
            {
                "value": monthly.value,
                "reason": "monthly*12 exceeds total",
                "snippet": monthly.evidence,
            }
        )
        monthly = null()
    return price, monthly, rejected


def extract_mileage(text: str, title: str) -> tuple[Field, Field, list[dict[str, Any]]]:
    """Return (mileage_km, is_brand_new, rejected)."""
    t = normalize_digits(text)
    cands: list[tuple[float, float, str]] = []
    rejected: list[dict[str, Any]] = []
    covered: list[tuple[int, int]] = []
    for rx, base in ((MILEAGE_LABEL_RE, 0.9), (MILEAGE_UNIT_RE, 0.7)):
        for m in rx.finditer(t):
            gi = next((i for i, g in enumerate(m.groups(), start=1) if g), None)
            if gi is None:
                continue
            v = parse_number(m.group(gi))
            if v is None:
                continue
            span = (m.start(gi), m.end(gi))
            # The label and the unit regex usually hit the same figure; judge it once, by the label.
            if any(a <= span[0] < b for a, b in covered):
                continue
            covered.append(span)
            # An explicit odometer label settles it; only a bare unit needs the wide look back.
            reach = 12 if rx is MILEAGE_LABEL_RE else 40
            before = t[max(0, m.start() - reach) : m.start()]
            after = t[m.end() : m.end() + 24]
            snippet = _snippet(t, m.start(), m.end())
            if MILEAGE_REJECT_BEFORE.search(before) or MILEAGE_REJECT_AFTER.search(after):
                rejected.append(
                    {
                        "value": v,
                        "reason": "range, warranty, service or speed context",
                        "snippet": snippet,
                    }
                )
                continue
            if v > 600_000:
                rejected.append({"value": v, "reason": "implausible odometer", "snippet": snippet})
                continue
            conf = 0.9 if MILEAGE_KEYWORDS.search(before + " " + after) else base
            cands.append((v, conf, snippet))
    range_values = {r["value"] for r in rejected}
    cands = [c for c in cands if c[0] not in range_values]
    mileage = null()
    if cands:
        v, conf, snip = sorted(cands, key=lambda x: -x[1])[0]
        mileage = Field(int(v), "regex", snip, conf)

    brand_new = null()
    bn = BRAND_NEW_RE.search(title) or BRAND_NEW_RE.search(t)
    if bn:
        src_text = title if BRAND_NEW_RE.search(title) else t
        brand_new = Field(True, "regex", _snippet(src_text, bn.start(), bn.end()), 0.9)
        if mileage.value is None and re.search(r"0\s*-?\s*kms?\b|zero\s*km", bn.group(0), re.I):
            mileage = Field(0, "regex", brand_new.evidence, 0.9)
    elif mileage.value is not None and mileage.value <= 100:
        brand_new = Field(True, "derived", mileage.evidence, 0.7)
    else:
        brand_new = Field(False, "derived", None, 0.6)
    return mileage, brand_new, rejected


def _color_in(phrase: str) -> str | None:
    low = phrase.lower()
    for word in sorted(COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"(?<![\w؀-ۿ]){re.escape(word)}(?![\w؀-ۿ])", low):
            return COLOR_WORDS[word]
    return None


_INTERIOR_RE = re.compile(
    r"(\w+(?:\s*/\s*\w+)?)\s+(?:leather\s+|fabric\s+)?interior\b"
    r"|interior\s*(?:colou?r)?\s*[:\-]\s*(\w+(?:\s+and\s+\w+)?)"
    r"|(\w+)\s+leather\b"
)
_INTERIOR_SCRUB_RE = re.compile(
    r"(?:\w+\s*/\s*)?\w+\s+(?:leather\s+|fabric\s+)?interior\b"
    r"|interior\s*(?:colou?r)?\s*[:\-]\s*\w+(?:\s+and\s+\w+)?"
    r"|\w+\s+leather\b"
)
_EXTERIOR_PATTERNS: list[tuple[str, float]] = [
    (r"(?:exterior|ext\.?|paint|body)\s*(?:colou?r)?\s*[:\-]?\s*(\w+(?:\s\w+)?)", 0.9),
    (r"colou?r\s*[:\-]?\s*(\w+(?:\s\w+)?)", 0.85),
    (r"(\w+)\s+(?:exterior|colou?r|paint)\b", 0.85),
    (r"اللون\s*[:\-]?\s*(\S+)|لون\s+(\S+)", 0.85),
    (r"\b(\w+)\s+with\s+(?:leather|fabric)\b", 0.7),
    (r"(?:in|stunning|sleek|finished in)\s+(\w+)\b", 0.6),
]


def extract_colors(text: str) -> tuple[Field, Field]:
    low = text.lower()
    for ff in COLOR_FALSE_FRIENDS:
        low = low.replace(ff, " " * len(ff))
    interior = null()
    for m in _INTERIOR_RE.finditer(low):
        phrase = next(g for g in m.groups() if g)
        c = _color_in(phrase)
        if c:
            interior = Field(c, "regex", _snippet(text, m.start(), m.end()), 0.8)
            break
    # Blank out interior phrases so an exterior fallback cannot pick them up.
    scrub = _INTERIOR_SCRUB_RE.sub(lambda m: " " * len(m.group(0)), low)
    exterior = null()
    for rx, conf in _EXTERIOR_PATTERNS:
        for m in re.finditer(rx, scrub):
            phrase = next((g for g in m.groups() if g), "")
            c = _color_in(phrase)
            if c:
                exterior = Field(c, "regex", _snippet(text, m.start(), m.end()), conf)
                break
        if exterior.value:
            break
    if exterior.value is None:
        c = _color_in(scrub)
        if c:
            m = re.search(rf"(?<!\w){c}(?!\w)", scrub)
            exterior = Field(c, "regex", _snippet(text, m.start(), m.end()) if m else None, 0.5)
    return exterior, interior


def extract_body_type(make: str, model: str, title: str, text: str) -> Field:
    joined = title + " " + text
    low = joined.lower()
    for word, bt in BODY_WORDS_STRONG.items():
        m = re.search(rf"\b{re.escape(word)}\b", low)
        if m:
            return Field(bt, "regex", _snippet(joined, m.start(), m.end()), 0.85)
    if (make, model) in BODY_TYPE_BY_MODEL:
        return Field(
            BODY_TYPE_BY_MODEL[(make, model)], "inferred", f"model knowledge: {make} {model}", 0.8
        )
    for word, bt in BODY_WORDS_WEAK.items():
        m = re.search(rf"\b{re.escape(word)}\b", low)
        if m:
            return Field(bt, "regex", _snippet(joined, m.start(), m.end()), 0.6)
    return null("inferred")


def _first_match(patterns: list[tuple[str, str]], text: str) -> Field:
    for rx, value in patterns:
        m = re.search(rx, text, re.I)
        if m:
            return Field(value, "regex", _snippet(text, m.start(), m.end()), 0.85)
    return null()


def extract_all(
    make: str, model: str, title: str, clean: str
) -> tuple[dict[str, Field], list[dict[str, Any]]]:
    """Run every extractor over title plus clean description."""
    text = title + "\n" + clean
    fields: dict[str, Field] = {}
    price, monthly, rej_p = extract_prices(text)
    mileage, brand_new, rej_m = extract_mileage(clean, title)
    fields["price_aed"], fields["monthly_aed"] = price, monthly
    fields["mileage_km"], fields["is_brand_new"] = mileage, brand_new
    fields["exterior_color"], fields["interior_color"] = extract_colors(text)
    fields["body_type"] = extract_body_type(make, model, title, clean)
    fields["regional_spec"] = _first_match(REGIONAL_SPEC_PATTERNS, text)
    fuel = _first_match(FUEL_PATTERNS, text)
    if fuel.value is None and (make, model) in ELECTRIC_MODELS:
        fuel = Field("electric", "inferred", f"model knowledge: {make} {model}", 0.8)
    fields["fuel_type"] = fuel
    fields["transmission"] = _first_match(TRANSMISSION_PATTERNS, text)
    sm = SEATS_RE.search(text)
    fields["seats"] = (
        Field(int(sm.group(1)), "regex", _snippet(text, sm.start(), sm.end()), 0.8)
        if sm
        else null()
    )
    wm = WARRANTY_RE.search(text)
    if wm and not NO_WARRANTY_RE.search(text):
        fields["has_warranty"] = Field(
            True, "regex", _snippet(text, wm.start(), wm.end(), 50), 0.85
        )
        fields["warranty_text"] = Field(
            _snippet(text, wm.start(), wm.end(), 60), "regex", None, 0.8
        )
    else:
        fields["has_warranty"] = Field(False, "regex", None, 0.8 if wm else 0.6)
        fields["warranty_text"] = null()
    scm = SERVICE_CONTRACT_RE.search(text)
    fields["service_contract"] = Field(
        bool(scm),
        "regex",
        _snippet(text, scm.start(), scm.end()) if scm else None,
        0.8 if scm else 0.6,
    )
    vat = "excl" if VAT_EXCL_RE.search(text) else "incl" if VAT_INCL_RE.search(text) else None
    fields["price_vat_status"] = Field(vat, "regex", None, 0.8) if vat else null()
    dps = [int(m.group(1)) for m in DOWN_PAYMENT_RE.finditer(text)]
    fields["down_payment_pct"] = Field(min(dps), "regex", None, 0.8) if dps else null()
    em = re.search(EXPORT_ONLY_RE, text, re.I)
    fields["is_export_only"] = Field(
        bool(em), "regex", _snippet(text, em.start(), em.end()) if em else None, 0.9 if em else 0.7
    )
    return fields, rej_p + rej_m
