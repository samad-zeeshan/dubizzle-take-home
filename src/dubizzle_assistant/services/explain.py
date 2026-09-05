"""
Turn the search tool's arguments into filters, recording every normalization step.

The model passes what the user said; this layer says what that became: "$20k"
to AED at the peg, "Merc" to mercedes-benz, "family car" to suv. The steps
travel with the search result so the trace can show them.
"""

from __future__ import annotations

from typing import Any

from dubizzle_assistant.normalize import (
    canonical_body_type,
    canonical_make,
    parse_budget,
    resolve_make_model,
)
from dubizzle_assistant.services.inventory import SearchFilters

_INT_ARGS = (
    "year_min",
    "year_max",
    "price_max_aed",
    "price_min_aed",
    "monthly_max_aed",
    "mileage_max_km",
)
_BOOL_ARGS = ("has_warranty", "is_brand_new", "is_dubizzle_managed", "exclude_export_only")


def filters_from_args(args: dict[str, Any]) -> tuple[SearchFilters, list[str]]:
    steps: list[str] = []
    f = SearchFilters()

    make = (args.get("make") or "").strip().lower() or None
    model = (args.get("model") or "").strip().lower() or None
    if make:
        canon, step = canonical_make(make)
        if canon != make:
            steps.append(step)
        make = canon
    if model and not make:
        m2, mo2, s2 = resolve_make_model(model)
        if m2:
            steps.extend(s2)
            make, model = m2, mo2 or model
    elif model:
        m2, mo2, s2 = resolve_make_model(model)
        if mo2 and mo2 != model:
            steps.extend(s2)
            model = mo2
    f.make, f.model = make, model

    for k in _INT_ARGS:
        v = args.get(k)
        if v not in (None, "", 0):
            try:
                setattr(f, k, int(float(v)))
            except (TypeError, ValueError):
                steps.append(f"ignored {k}={v!r} (not a number)")
    for k in _BOOL_ARGS:
        v = args.get(k)
        if v is not None:
            setattr(f, k, bool(v))

    budget_text = args.get("budget_text")
    if budget_text:
        money = parse_budget(str(budget_text))
        if money:
            steps.extend(money.steps)
            if money.mode == "monthly":
                f.monthly_max_aed = int(money.amount_aed)
            else:
                f.price_max_aed = int(money.amount_aed)

    bt = (args.get("body_type") or "").strip().lower() or None
    if bt:
        canon_bt = canonical_body_type(bt)
        if canon_bt and canon_bt != bt:
            steps.append(f"{bt} -> {canon_bt} (body type alias)")
        f.body_type = canon_bt or bt
    for k in ("color", "regional_spec", "fuel_type"):
        v = (args.get(k) or "").strip().lower() or None
        if v:
            setattr(f, k, v)
    if args.get("keywords"):
        f.keywords = str(args["keywords"]).strip()
    if args.get("sort"):
        f.sort = str(args["sort"])
    return f, steps
