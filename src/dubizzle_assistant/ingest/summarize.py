"""
Derive the English summary and search keywords from extracted fields.

The summary is what the model sees instead of the seller's text, so it is
built from fields only and never quotes marketing copy. Arabic-only listings
get their facts here too, which is what makes them searchable in English.
"""

from __future__ import annotations

import re

from dubizzle_assistant.ingest.extract import Field
from dubizzle_assistant.ingest.knowledge import ARABIC_GLOSSARY, FEATURE_KEYWORDS

_DISPLAY_MAKE = {
    "mercedes-benz": "Mercedes-Benz",
    "bmw": "BMW",
    "gwm": "GWM",
    "jac": "JAC",
    "byd": "BYD",
    "land rover": "Land Rover",
    "rolls-royce": "Rolls-Royce",
    "aston martin": "Aston Martin",
    "mini": "MINI",
    "mclaren": "McLaren",
}


def display_make(make: str) -> str:
    return _DISPLAY_MAKE.get(make, make.title())


def display_model(model: str) -> str:
    keep_upper = {
        "cr-v",
        "cx-5",
        "rs7",
        "rs q3",
        "sf90",
        "dbx",
        "lr4",
        "js4",
        "yu7",
        "bz4x",
        "t99",
        "h9",
        "x7",
        "q8",
        "q7",
        "x1",
        "x6",
        "i4",
        "ix3",
        "m4",
        "m5",
        "xe",
        "g90",
        "q50",
        "mkx",
        "slr",
        "xc60",
        "t-roc",
        "h3",
        "f430",
        "675lt",
        "j14",
        "x-trail",
    }
    if model in keep_upper:
        return model.upper()
    return re.sub(r"\b(\w)", lambda m: m.group(1).upper(), model)


def english_summary(
    make: str, model: str, trim: str, year: int, fields: dict[str, Field], flags: dict[str, bool]
) -> str:
    name = f"{year} {display_make(make)} {display_model(model)}"
    if trim and trim != "other":
        name += f" {trim.upper() if len(trim) <= 4 else trim.title()}"
    bits: list[str] = []
    bt = fields["body_type"].value
    if bt:
        bits.append(bt.replace("_", " ").upper() if bt == "suv" else bt.replace("_", " "))
    spec = fields["regional_spec"].value
    if spec:
        bits.append(f"{spec.upper() if spec in ('gcc', 'us') else spec.title()} spec")
    color = fields["exterior_color"].value
    if color:
        bits.append(f"{color} exterior")
    first = name + (" (" + ", ".join(bits) + ")" if bits else "") + "."
    facts: list[str] = []
    if fields["is_brand_new"].value:
        facts.append("Brand new")
    elif fields["mileage_km"].value is not None:
        facts.append(f"{fields['mileage_km'].value:,} km")
    else:
        facts.append("mileage not stated")
    if fields["price_aed"].value is not None:
        facts.append(f"listed at AED {fields['price_aed'].value:,}")
    if fields["monthly_aed"].value is not None:
        facts.append(f"AED {fields['monthly_aed'].value:,} per month offered")
    if fields["price_aed"].value is None and fields["monthly_aed"].value is None:
        facts.append("price not stated")
    if fields["has_warranty"].value:
        facts.append("warranty mentioned")
    if fields["service_contract"].value:
        facts.append("service contract mentioned")
    if flags.get("is_dubizzle_managed"):
        facts.append("dubizzle inspected listing")
    if flags.get("is_export_only"):
        facts.append("export only")
    second = "; ".join(facts)
    second = second[0].upper() + second[1:] + "."
    return f"{first} {second}"


def keywords(
    make: str, model: str, trim: str, title: str, clean: str, fields: dict[str, Field]
) -> str:
    text = (title + " " + clean).lower()
    found: list[str] = [make, model]
    if trim and trim != "other":
        found.append(trim)
    for needle, label in FEATURE_KEYWORDS.items():
        if needle in text and label not in found:
            found.append(label)
    for needle, label in ARABIC_GLOSSARY.items():
        if needle in text and label not in found:
            found.append(label)
    for key in ("body_type", "regional_spec", "exterior_color", "fuel_type", "transmission"):
        v = fields[key].value
        if v and v not in found:
            found.append(str(v).replace("_", " "))
    if fields["seats"].value:
        found.append(f"{fields['seats'].value} seats")
    if fields["is_brand_new"].value and "brand new" not in found:
        found.append("brand new")
    return ", ".join(found)
