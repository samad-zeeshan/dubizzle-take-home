"""
Search and fetch listings from SQLite, and say exactly how each result was found.

Hybrid by default: structured filters narrow, FTS5 ranks within, and a fixed
relaxation ladder turns "no exact match" into "closest matches" with the
relaxed filters named. Every search returns the SQL it ran and the row count
at each ladder stage, so "how did it find this" has a literal answer.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from dubizzle_assistant.db import LISTING_COLUMNS
from dubizzle_assistant.normalize import (
    canonical_body_type,
    canonical_make,
    known_makes,
    register_makes,
    register_models,
    resolve_make_model,
)
from dubizzle_assistant.services.embeddings import RetrievalUnavailableError
from dubizzle_assistant.text import strip_contacts

# bm25 weights: id (unindexed), make, model, trim, title, english_summary, keywords_en, description_clean.
# Make and model dominate so dealer prose mentioning "Toyota service history" cannot outrank a Toyota.
FTS_WEIGHTS = "0.0, 10.0, 8.0, 4.0, 3.0, 2.0, 2.0, 1.0"

CARD_FIELDS = (
    "id",
    "year",
    "make",
    "model",
    "trim",
    "title",
    "photo_url",
    "price_aed",
    "monthly_aed",
    "mileage_km",
    "exterior_color",
    "body_type",
    "regional_spec",
    "fuel_type",
    "has_warranty",
    "service_contract",
    "is_dubizzle_managed",
    "is_export_only",
    "is_brand_new",
    "english_summary",
    "language",
    "description_quality",
)

Embedder = Callable[[str], list[float]]


@dataclass
class SearchFilters:
    make: str | None = None
    model: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    price_max_aed: int | None = None
    price_min_aed: int | None = None
    monthly_max_aed: int | None = None
    body_type: str | None = None
    color: str | None = None
    regional_spec: str | None = None
    fuel_type: str | None = None
    has_warranty: bool | None = None
    mileage_max_km: int | None = None
    is_brand_new: bool | None = None
    is_dubizzle_managed: bool | None = None
    exclude_export_only: bool = False
    keywords: str | None = None
    sort: str | None = None  # not a filter, carried so the ladder keeps it

    def active(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, False, "") and k != "sort"}


@dataclass
class SearchResult:
    mode: str
    total_matches: int
    shown: int
    offset: int
    applied_filters: dict[str, Any]
    relaxed_filters: list[str]
    stage_counts: dict[str, int]
    price_buckets: dict[str, int]
    normalization: list[str]
    executed: dict[str, Any]
    results: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def thumb_url(photo_url: str) -> str:
    # The CDN serves a 6 KB webp at this width instead of the 100 KB original.
    return re.sub(r"\?.*$", "", photo_url) + "?imwidth=400" if photo_url else photo_url


def load_inventory(conn: sqlite3.Connection, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    # The resolver learns this inventory's makes and models, so another dataset resolves "the civic" too.
    register_makes(r["make"] for r in data["listings"])
    register_models((r["make"], r["model"]) for r in data["listings"])
    rows: list[tuple[Any, ...]] = []
    for rec in data["listings"]:
        f = rec["fields"]

        def v(k: str, f: dict[str, Any] = f) -> Any:
            return f[k]["value"]

        rows.append(
            (
                rec["id"],
                rec["source_sheet"],
                rec["source_row"],
                rec["make"],
                rec["model"],
                rec["trim"],
                rec["year"],
                rec["title"],
                rec["description_raw"],
                rec["description_clean"],
                rec["english_summary"],
                rec["keywords_en"],
                rec["photo_url"],
                v("price_aed"),
                v("monthly_aed"),
                v("price_vat_status"),
                v("down_payment_pct"),
                v("mileage_km"),
                int(bool(v("is_brand_new"))),
                v("exterior_color"),
                v("interior_color"),
                v("body_type"),
                v("regional_spec"),
                v("fuel_type"),
                v("transmission"),
                v("seats"),
                int(bool(v("has_warranty"))),
                v("warranty_text"),
                int(bool(v("service_contract"))),
                int(bool(v("is_export_only"))),
                int(bool(v("is_dubizzle_managed"))),
                rec["language"],
                int(bool(rec["truncated"])),
                rec["description_quality"],
                rec.get("dealer_name"),
                json.dumps(f, ensure_ascii=False),
                json.dumps(rec.get("dealer_contact", {}), ensure_ascii=False),
            )
        )
    placeholders = ", ".join("?" for _ in LISTING_COLUMNS)
    with conn:
        conn.execute("DELETE FROM listings")
        conn.execute("DELETE FROM listings_fts")
        conn.executemany(
            f"INSERT INTO listings ({', '.join(LISTING_COLUMNS)}) VALUES ({placeholders})", rows
        )
        conn.execute(
            "INSERT INTO listings_fts (id, make, model, trim, title, english_summary, keywords_en, description_clean) "
            "SELECT id, make, model, trim, title, english_summary, keywords_en, description_clean FROM listings"
        )
    return len(rows)


def all_makes(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT make FROM listings ORDER BY make")]


def card(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    out = {k: d.get(k) for k in CARD_FIELDS}
    for k in (
        "has_warranty",
        "service_contract",
        "is_dubizzle_managed",
        "is_export_only",
        "is_brand_new",
    ):
        out[k] = bool(out[k])
    out["thumb_url"] = thumb_url(d.get("photo_url") or "")
    return out


def _norm_model(expr: str) -> str:
    return f"replace(replace({expr}, '-', ' '), '  ', ' ')"


def _where(f: SearchFilters, mode: str) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if mode == "fts":
        return clauses, params
    if f.make:
        clauses.append("make = :make")
        params["make"] = f.make
    if f.model:
        # "range rover" should find the Sport and the Velar as well as the plain one, and "sport"
        # on its own should still find the Range Rover Sport: the phrase matches whole words anywhere.
        m = _norm_model("model")
        clauses.append(
            f"({m} = :model OR {m} LIKE :model || ' %' OR {m} LIKE '% ' || :model"
            f" OR {m} LIKE '% ' || :model || ' %')"
        )
        params["model"] = f.model.replace("-", " ")
    if f.year_min is not None:
        clauses.append("year >= :year_min")
        params["year_min"] = f.year_min
    if f.year_max is not None:
        clauses.append("year <= :year_max")
        params["year_max"] = f.year_max
    if f.price_max_aed is not None:
        # Unknown price is a soft pass: most listings have none, and dropping them hides the inventory.
        clauses.append("(price_aed IS NULL OR price_aed <= :price_max)")
        params["price_max"] = f.price_max_aed
    if f.price_min_aed is not None:
        clauses.append("(price_aed IS NULL OR price_aed >= :price_min)")
        params["price_min"] = f.price_min_aed
    if f.monthly_max_aed is not None:
        clauses.append("(monthly_aed IS NULL OR monthly_aed <= :monthly_max)")
        params["monthly_max"] = f.monthly_max_aed
    if f.body_type:
        clauses.append("body_type = :body_type")
        params["body_type"] = f.body_type
    if f.color:
        clauses.append("exterior_color = :color")
        params["color"] = f.color
    if f.regional_spec:
        clauses.append("regional_spec = :spec")
        params["spec"] = f.regional_spec
    if f.fuel_type:
        clauses.append("fuel_type = :fuel")
        params["fuel"] = f.fuel_type
    if f.has_warranty:
        clauses.append("has_warranty = 1")
    if f.mileage_max_km is not None:
        clauses.append("mileage_km IS NOT NULL AND mileage_km <= :mileage_max")
        params["mileage_max"] = f.mileage_max_km
    if f.is_brand_new:
        clauses.append("is_brand_new = 1")
    if f.is_dubizzle_managed:
        clauses.append("is_dubizzle_managed = 1")
    if f.exclude_export_only:
        clauses.append("is_export_only = 0")
    return clauses, params


_FTS_TOKEN_RE = re.compile(r"[\w؀-ۿ][\w؀-ۿ'-]*")
_FTS_STOP = {
    "a",
    "an",
    "the",
    "with",
    "and",
    "or",
    "for",
    "in",
    "of",
    "to",
    "me",
    "show",
    "any",
    "car",
    "cars",
    "under",
    "below",
    "above",
    "over",
}


def fts_match_string(text: str) -> str:
    tokens = [t.lower() for t in _FTS_TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if t not in _FTS_STOP and len(t) > 1]
    if not tokens:
        return ""
    parts = [f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in dict.fromkeys(tokens)]
    return " OR ".join(parts)


PHRASE_BONUS = (
    6.0  # bm25 is negative and lower is better; an exact phrase hit jumps ahead of loose token hits
)


def fts_scores_for(conn: sqlite3.Connection, text: str) -> tuple[str, dict[str, float]]:
    """Loose token match for recall, then the exact phrase pulled to the front for precision ("7 seats")."""
    match = fts_match_string(text)
    scores = _fts_scores(conn, match)
    tokens = [t.lower() for t in _FTS_TOKEN_RE.findall(text) if t.lower() not in _FTS_STOP]
    if len(tokens) >= 2:
        phrase = '"' + " ".join(tokens) + '"'
        hits = _fts_scores(conn, phrase)
        if hits:
            match = f"{phrase} OR {match}" if match else phrase
            for lid, score in hits.items():
                scores[lid] = min(scores.get(lid, 0.0), score) - PHRASE_BONUS
    return match, scores


def _fts_scores(conn: sqlite3.Connection, match: str) -> dict[str, float]:
    if not match:
        return {}
    sql = f"SELECT id, bm25(listings_fts, {FTS_WEIGHTS}) AS score FROM listings_fts WHERE listings_fts MATCH :q"
    try:
        return {r["id"]: float(r["score"]) for r in conn.execute(sql, {"q": match})}
    except sqlite3.OperationalError:
        # A stray quote or operator in user text must not turn into a 500.
        safe = " OR ".join(f'"{t}"' for t in re.findall(r"\w+", match) if t.lower() != "or")
        return {r["id"]: float(r["score"]) for r in conn.execute(sql, {"q": safe})} if safe else {}


def _fts_text_for(f: SearchFilters) -> str:
    bits = [
        f.keywords or "",
        f.make or "",
        f.model or "",
        f.body_type or "",
        f.color or "",
        f.regional_spec or "",
        f.fuel_type or "",
    ]
    return " ".join(b for b in bits if b)


# Stages of the relaxation ladder, in order. Each one returns the filters to try next.
LADDER: list[tuple[str, Callable[[SearchFilters], SearchFilters | None]]] = [
    ("exact", lambda f: f),
    ("drop_color", lambda f: replace(f, color=None) if f.color else None),
    (
        "widen_year",
        lambda f: (
            replace(
                f,
                year_min=(f.year_min - 2) if f.year_min is not None else None,
                year_max=(f.year_max + 2) if f.year_max is not None else None,
            )
            if (f.year_min is not None or f.year_max is not None)
            else None
        ),
    ),
    (
        "raise_budget",
        lambda f: (
            replace(
                f,
                price_max_aed=int(f.price_max_aed * 1.15) if f.price_max_aed else None,
                monthly_max_aed=int(f.monthly_max_aed * 1.15) if f.monthly_max_aed else None,
            )
            if (f.price_max_aed or f.monthly_max_aed)
            else None
        ),
    ),
    ("drop_keywords", lambda f: replace(f, keywords=None) if f.keywords else None),
    ("drop_body_type", lambda f: replace(f, body_type=None) if f.body_type else None),
    (
        "make_only",
        lambda f: (
            SearchFilters(
                make=f.make, model=f.model, exclude_export_only=f.exclude_export_only, sort=f.sort
            )
            if (f.make or f.model)
            else None
        ),
    ),
]


def _run_stage(
    conn: sqlite3.Connection, f: SearchFilters, mode: str, embedder: Embedder | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ordered matching rows plus the executed query for one ladder stage."""
    clauses, params = _where(f, mode)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM listings{where}"
    rows = [dict(r) for r in conn.execute(sql, params)]
    executed: dict[str, Any] = {"sql": sql, "params": params, "fts": None}

    fts_text = _fts_text_for(f) if mode == "fts" else (f.keywords or "")
    scores: dict[str, float] = {}
    if mode in ("fts", "hybrid") and fts_text:
        match, scores = fts_scores_for(conn, fts_text)
        executed["fts"] = match
        rows = [r for r in rows if r["id"] in scores]
        for r in rows:
            r["_bm25"] = scores[r["id"]]
    elif mode == "embeddings":
        from dubizzle_assistant.services.embeddings import rank_by_similarity

        query_text = _fts_text_for(f) or "any car"
        sims = rank_by_similarity(query_text, embedder)
        executed["embedding_query"] = query_text
        for r in rows:
            r["_cosine"] = sims.get(r["id"], 0.0)

    if f.sort:
        executed["sort"] = f.sort
        rows.sort(key=_sort_key(f.sort))
    elif mode == "embeddings":
        rows.sort(key=lambda r: (-(r.get("_cosine") or 0.0), r["id"]))
    elif scores:
        # bm25 is negative in FTS5, lower is better. Listed figures then newer years break ties.
        rows.sort(key=lambda r: (r["_bm25"], _unknown(r, f), -(r["year"] or 0), r["id"]))
    else:
        rows.sort(key=lambda r: (_unknown(r, f), -(r["year"] or 0), r["id"]))
    return rows, executed


def _unknown(row: dict[str, Any], f: SearchFilters) -> bool:
    # A soft pass must rank after a real match, and a monthly budget judges the instalment, not the cash price.
    if f.monthly_max_aed is not None:
        return row["monthly_aed"] is None
    return row["price_aed"] is None


def _sort_key(sort: str) -> Callable[[dict[str, Any]], tuple[Any, ...]]:
    # Unknown values always sink to the bottom whichever direction the sort runs.
    if sort == "price_asc":
        return lambda r: (r["price_aed"] is None, r["price_aed"] or 0, r["id"])
    if sort == "price_desc":
        return lambda r: (r["price_aed"] is None, -(r["price_aed"] or 0), r["id"])
    if sort == "year_asc":
        return lambda r: (r["year"] or 0, r["id"])
    if sort == "mileage_asc":
        return lambda r: (r["mileage_km"] is None, r["mileage_km"] or 0, r["id"])
    return lambda r: (-(r["year"] or 0), r["id"])


def _explain(row: dict[str, Any], f: SearchFilters, stage: str, position: int) -> dict[str, Any]:
    matched: list[str] = []
    for k in f.active():
        if k == "price_max_aed" and row["price_aed"] is None:
            matched.append("price_max_aed (price not listed, soft pass)")
        elif k == "monthly_max_aed" and row["monthly_aed"] is None:
            matched.append("monthly_max_aed (no instalment listed, soft pass)")
        else:
            matched.append(k)
    if f.sort:
        reason = f"sorted by {f.sort}"
    elif "_bm25" in row:
        reason = f"text relevance bm25 {row['_bm25']:.2f}"
    elif "_cosine" in row:
        reason = f"embedding similarity {row['_cosine']:.3f}"
    else:
        reason = (
            "listed price, " if row["price_aed"] is not None else "price not listed, "
        ) + f"year {row['year']}"
    return {
        "matched_filters": matched,
        "admitted_at_stage": stage,
        "bm25": round(row["_bm25"], 3) if "_bm25" in row else None,
        "cosine": round(row["_cosine"], 4) if "_cosine" in row else None,
        "rank_reason": f"#{position}: {reason}",
    }


def search(
    conn: sqlite3.Connection,
    filters: SearchFilters,
    *,
    mode: str = "hybrid",
    limit: int = 5,
    offset: int = 0,
    relax: bool = True,
    embedder: Embedder | None = None,
    normalization: list[str] | None = None,
) -> SearchResult:
    if mode == "embeddings":
        from dubizzle_assistant.services.embeddings import available

        if not available():
            raise RetrievalUnavailableError(
                "embeddings mode needs data/embeddings.npy; run scripts/build_embeddings.py"
            )
    steps = list(normalization or [])
    if filters.make:
        make, step = canonical_make(filters.make)
        if make not in known_makes():
            # Models send a model name as the make now and then ("range rover"); read it as a phrase.
            make2, model2, steps2 = resolve_make_model(filters.make)
            if make2:
                make, step = make2, steps2[0]
                if model2 and not filters.model:
                    filters = replace(filters, model=model2)
        if make != filters.make:
            steps.append(step)
        filters = replace(filters, make=make)
    if filters.body_type and canonical_body_type(filters.body_type) not in (
        None,
        filters.body_type,
    ):
        steps.append(
            f"{filters.body_type} -> {canonical_body_type(filters.body_type)} (body type alias)"
        )
        filters = replace(filters, body_type=canonical_body_type(filters.body_type))
    if mode == "structured" and filters.keywords:
        steps.append("keywords ignored in structured mode")

    stage_counts: dict[str, int] = {}
    relaxed: list[str] = []
    current = filters
    rows: list[dict[str, Any]] = []
    executed: dict[str, Any] = {}
    stage_used = "exact"
    for name, fn in LADDER if relax else LADDER[:1]:
        nxt = fn(current)
        if nxt is None:
            continue
        rows, executed = _run_stage(conn, nxt, mode, embedder)
        stage_counts[name] = len(rows)
        if name != "exact":
            relaxed.append(name)
        current = nxt
        stage_used = name
        if rows:
            break

    within = sum(1 for r in rows if r["price_aed"] is not None)
    excluded = 0
    if current.price_max_aed is not None and mode != "fts":
        hard = replace(current, price_max_aed=None)
        clauses, params = _where(hard, mode)
        clauses.append("price_aed > :price_max")
        params["price_max"] = current.price_max_aed
        excluded = conn.execute(
            f"SELECT COUNT(*) FROM listings WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
    buckets = {
        "listed_within_budget": within if current.price_max_aed is not None else within,
        "price_not_listed": len(rows) - within,
        "excluded_over_budget": excluded,
    }

    page = rows[offset : offset + limit]
    results = []
    for i, r in enumerate(page, start=offset + 1):
        c = card(r)
        c["explain"] = _explain(r, current, stage_used, i)
        results.append(c)
    return SearchResult(
        mode=mode,
        total_matches=len(rows),
        shown=len(results),
        offset=offset,
        applied_filters=current.active(),
        relaxed_filters=relaxed,
        stage_counts=stage_counts,
        price_buckets=buckets,
        normalization=steps,
        executed=executed,
        results=results,
    )


def get_listing(conn: sqlite3.Connection, listing_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    out = card(d)
    out.update(
        {
            "source_sheet": d["source_sheet"],
            "source_row": d["source_row"],
            "interior_color": d["interior_color"],
            "transmission": d["transmission"],
            "seats": d["seats"],
            "warranty_text": d["warranty_text"],
            "price_vat_status": d["price_vat_status"],
            "down_payment_pct": d["down_payment_pct"],
            "truncated": bool(d["truncated"]),
            "dealer_name": d["dealer_name"],
            "keywords_en": d["keywords_en"],
            "description_clean": d["description_clean"],
            # The seller's full wording for the explorer, minus every contact detail.
            "description_original": strip_contacts(d["description_raw"] or ""),
            "fields": json.loads(d["provenance_json"] or "{}"),
        }
    )
    return out


def get_cards(conn: sqlite3.Connection, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = {
        r["id"]: dict(r) for r in conn.execute(f"SELECT * FROM listings WHERE id IN ({marks})", ids)
    }
    return [card(rows[i]) for i in ids if i in rows]


def compare(conn: sqlite3.Connection, ids: list[str]) -> dict[str, Any]:
    cards = get_cards(conn, ids)
    keys = [
        "year",
        "price_aed",
        "monthly_aed",
        "mileage_km",
        "exterior_color",
        "body_type",
        "regional_spec",
        "fuel_type",
        "has_warranty",
        "service_contract",
        "is_dubizzle_managed",
    ]
    table = {k: [c.get(k) for c in cards] for k in keys}
    return {"ids": [c["id"] for c in cards], "cards": cards, "table": table}


PRICE_BAND = (
    0.30  # a listed price this far either side of the anchor's still counts as an alternative
)


def _vs_anchor(anchor: dict[str, Any], row: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    """Score one candidate against the anchor and say how it differs, in words a reply can reuse."""
    score, matched, words = 0, [], []
    if anchor["body_type"] and row["body_type"] == anchor["body_type"]:
        score += 3
        matched.append("body_type")
        words.append("same body type")
    ap, rp = anchor["price_aed"], row["price_aed"]
    if ap and rp:
        gap = abs(rp - ap) / ap
        if gap <= 0.15:
            score += 3
        elif gap <= PRICE_BAND:
            score += 2
        elif gap <= 0.5:
            score += 1
        if gap <= PRICE_BAND:
            matched.append("price_band")
        words.append(
            "same price" if rp == ap else f"AED {abs(rp - ap):,} {'more' if rp > ap else 'less'}"
        )
    elif rp is None:
        words.append("price not listed")
    if anchor["year"] and row["year"]:
        dy = row["year"] - anchor["year"]
        if abs(dy) <= 1:
            score += 2
        elif abs(dy) <= 3:
            score += 1
        if abs(dy) <= 3:
            matched.append("year")
        words.append(
            "same year"
            if dy == 0
            else f"{abs(dy)} year{'s' if abs(dy) != 1 else ''} {'newer' if dy > 0 else 'older'}"
        )
    if row["make"] == anchor["make"]:
        score += 1
        matched.append("make")
        words.append(f"also a {row['make']}")
    return score, matched, words


def similar(conn: sqlite3.Connection, listing_id: str, limit: int = 5) -> dict[str, Any] | None:
    """Alternatives to one listing, never the listing itself.

    A candidate qualifies on the same body type or a listed price within the band, and ranks on
    how much of body type, price, year, and make it shares. Attribute scoring rather than
    embeddings, so each result carries a reason the trace and the reply can quote.
    """
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if row is None:
        return None
    anchor = dict(row)
    sql = "SELECT * FROM listings WHERE id != :id"
    ranked: list[tuple[tuple[int, bool, int, str], dict[str, Any], list[str], list[str]]] = []
    for r in conn.execute(sql, {"id": listing_id}):
        cand = dict(r)
        score, matched, words = _vs_anchor(anchor, cand)
        if "body_type" not in matched and "price_band" not in matched:
            continue
        gap = (
            abs(cand["price_aed"] - anchor["price_aed"])
            if cand["price_aed"] and anchor["price_aed"]
            else 0
        )
        ranked.append(((-score, cand["price_aed"] is None, gap, cand["id"]), cand, matched, words))
    ranked.sort(key=lambda t: t[0])
    results = []
    for i, (_, cand, matched, words) in enumerate(ranked[:limit], start=1):
        c = card(cand)
        c["explain"] = {
            "matched_filters": matched,
            "admitted_at_stage": "similar",
            "bm25": None,
            "cosine": None,
            "rank_reason": f"#{i}: " + ", ".join(words),
            "vs_anchor": ", ".join(words),
        }
        results.append(c)
    criteria = "same body type"
    if anchor["price_aed"]:
        criteria += (
            f" or a listed price within {int(PRICE_BAND * 100)}% of AED {anchor['price_aed']:,}"
        )
    return {
        "anchor": card(anchor),
        "criteria": criteria,
        "total_matches": len(ranked),
        "results": results,
        "executed": {
            "sql": sql,
            "params": {"id": listing_id},
            "scoring": "body type 3; price within 15% 3, 30% 2, 50% 1; year within 1 2, within 3 1; same make 1",
        },
    }


def raw_text(conn: sqlite3.Connection, listing_id: str) -> str:
    """The seller's text with contact details intact. Only the sanitizer ablation ever reads this."""
    row = conn.execute(
        "SELECT description_raw FROM listings WHERE id = ?", (listing_id,)
    ).fetchone()
    return (row["description_raw"] if row else "") or ""
