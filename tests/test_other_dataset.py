"""A workbook that looks nothing like the assignment's: one sheet, other headers, structured columns, unknown makes."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from dubizzle_assistant import db
from dubizzle_assistant.evaluation import evaluate
from dubizzle_assistant.ingest.load import resolve_header
from dubizzle_assistant.ingest.pipeline import build
from dubizzle_assistant.normalize import resolve_make_model
from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services.explain import filters_from_args

HEADERS = [
    "Ad ID",
    "Brand",
    "Model",
    "Year",
    "Details",
    "Price (AED)",
    "Mileage",
    "Colour",
    "Body Style",
    "Warranty",
    "Seller Notes",
]
ROWS = [
    [
        501,
        "Zeekr",
        "001",
        2024,
        "Long range, one owner, service history.",
        "AED 145,000",
        "12,500 km",
        "Pearl White",
        "SUV",
        "Yes",
        "n/a",
    ],
    [502, "Toyota", "Corolla", 2019, "Well kept sedan.", 48000, 90000, "silver", "Sedan", "No", ""],
    [503, "Zeekr", "X", 2023, "", "", "", "", "", "", ""],
]


def make_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Listings"
    ws.append(HEADERS)
    for r in ROWS:
        ws.append(r)
    wb.save(path)
    return path


def test_header_aliases_and_unmapped_report() -> None:
    core, extra, unmapped = resolve_header(HEADERS)
    assert (
        core["make"] == 1
        and core["model"] == 2
        and core["listing_id"] == 0
        and core["description"] == 4
    )
    assert extra["price_aed"] == 5 and extra["mileage_km"] == 6 and extra["exterior_color"] == 7
    assert unmapped == ["Seller Notes"]


def test_foreign_workbook_builds_with_column_provenance(tmp_path: Path) -> None:
    inventory = build(make_workbook(tmp_path / "other.xlsx"))
    recs = {r["id"]: r for r in inventory["listings"]}
    # A numeric id column makes the sheet "cleaned", so the ids are kept.
    assert set(recs) == {"C-501", "C-502", "C-503"}
    zeekr = recs["C-501"]["fields"]
    assert zeekr["price_aed"] == {
        "value": 145000,
        "source": "column",
        "evidence": "column value 'AED 145,000'",
        "confidence": 1.0,
    }
    assert zeekr["mileage_km"]["value"] == 12500 and zeekr["exterior_color"]["value"] == "white"
    assert zeekr["body_type"]["value"] == "suv" and zeekr["has_warranty"]["value"] is True
    assert recs["C-502"]["fields"]["has_warranty"]["value"] is False
    # No title column: one is rebuilt from the year, make, and model.
    assert recs["C-503"]["title"] == "2023 Zeekr X"
    sheets = inventory["meta"]["sheets"]
    assert sheets[0]["kind"] == "cleaned" and sheets[0]["unmapped"] == ["Seller Notes"]
    assert inventory["meta"]["counts"]["column_fields"] >= 7

    out = tmp_path / "inventory.json"
    out.write_text(json.dumps(inventory), encoding="utf-8")
    db.init_db(tmp_path / "t.db")
    conn = db.connect(tmp_path / "t.db")
    inv.load_inventory(conn, out)
    # The resolver learned the new make from the data, plural included.
    assert resolve_make_model("any zeekrs?")[0] == "zeekr"
    filters, _ = filters_from_args({"make": "zeekr", "body_type": "suv"})
    hits = inv.search(conn, filters, mode="hybrid", limit=5).as_dict()
    assert [c["id"] for c in hits["results"]] == ["C-501"]

    report = evaluate(conn, out, modes=("structured",))
    summary = report["summary"]["structured"]
    assert summary["not_applicable"] >= 20 and summary["unavailable"] is None
    conn.close()
