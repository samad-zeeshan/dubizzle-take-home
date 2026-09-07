"""
Inventory endpoints: typed search with no LLM involved, listing detail with provenance, compare, similar.

The same search service backs the chat tool, so anything the assistant can
find, a reviewer can find here with curl and see how it was found.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dubizzle_assistant.api.deps import get_conn, get_embedder, get_settings_dep
from dubizzle_assistant.config import Settings
from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services.explain import filters_from_args

router = APIRouter(prefix="/inventory", tags=["inventory"])

Mode = Literal["structured", "fts", "hybrid", "embeddings"]


@router.get("/search")
def search_inventory(
    request: Request,
    make: str | None = Query(None, description="Any alias works: Merc, Range Rover, Chevy"),
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_max_aed: int | None = None,
    price_min_aed: int | None = None,
    monthly_max_aed: int | None = None,
    budget_text: str | None = Query(
        None, description="Verbatim budget phrase, e.g. '$20k' or 'under 2000 a month'"
    ),
    body_type: str | None = None,
    color: str | None = None,
    regional_spec: str | None = None,
    fuel_type: str | None = None,
    has_warranty: bool | None = None,
    mileage_max_km: int | None = None,
    is_brand_new: bool | None = None,
    is_dubizzle_managed: bool | None = None,
    exclude_export_only: bool = False,
    keywords: str | None = Query(
        None, description="Free text matched with FTS5 over titles, summaries and keywords"
    ),
    sort: Literal["price_asc", "price_desc", "year_desc", "year_asc", "mileage_asc"] | None = None,
    mode: Mode | None = Query(None, description="Overrides RETRIEVAL_MODE for this request"),
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    relax: bool = True,
    settings: Settings = Depends(get_settings_dep),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    args = {
        "make": make,
        "model": model,
        "year_min": year_min,
        "year_max": year_max,
        "price_max_aed": price_max_aed,
        "price_min_aed": price_min_aed,
        "monthly_max_aed": monthly_max_aed,
        "budget_text": budget_text,
        "body_type": body_type,
        "color": color,
        "regional_spec": regional_spec,
        "fuel_type": fuel_type,
        "has_warranty": has_warranty,
        "mileage_max_km": mileage_max_km,
        "is_brand_new": is_brand_new,
        "is_dubizzle_managed": is_dubizzle_managed,
        "exclude_export_only": exclude_export_only,
        "keywords": keywords,
        "sort": sort,
    }
    filters, steps = filters_from_args(args)
    result = inv.search(
        conn,
        filters,
        mode=mode or settings.retrieval_mode,
        limit=limit,
        offset=offset,
        relax=relax and not settings.ablate_relaxation,
        embedder=get_embedder(request),
        normalization=steps,
    )
    return result.as_dict()


@router.get("/makes")
def makes(conn: sqlite3.Connection = Depends(get_conn)) -> list[str]:
    return inv.all_makes(conn)


@router.get("/compare")
def compare(
    ids: str = Query(..., description="Comma separated listing ids, e.g. C-003,C-044"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    wanted = [i.strip().upper() for i in ids.split(",") if i.strip()]
    if not 2 <= len(wanted) <= 4:
        raise HTTPException(status_code=422, detail="compare takes 2 to 4 ids")
    out = inv.compare(conn, wanted)
    missing = [i for i in wanted if i not in out["ids"]]
    if missing:
        raise HTTPException(status_code=404, detail=f"unknown listing ids: {', '.join(missing)}")
    return out


@router.get("/{listing_id}")
def get_listing(listing_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    row = inv.get_listing(conn, listing_id.upper())
    if row is None:
        raise HTTPException(status_code=404, detail=f"no listing {listing_id}")
    return row


@router.get("/{listing_id}/similar")
def similar_listings(
    listing_id: str,
    limit: int = Query(5, ge=1, le=20),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    out = inv.similar(conn, listing_id.upper(), limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail=f"no listing {listing_id}")
    return out
