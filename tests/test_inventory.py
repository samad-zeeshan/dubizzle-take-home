"""
The committed inventory must reflect the workbook's quirks, not paper over them.

These assertions pin the facts found by inspecting the data: the merged count,
the one Honda, the ten managed rows, the BYD range decoy, the int-typed cells.
"""

from __future__ import annotations

from dubizzle_assistant.ingest.extract import extract_mileage, extract_prices
from dubizzle_assistant.ingest.load import clean_html, load_all
from dubizzle_assistant.ingest.sanitize import sanitize
from dubizzle_assistant.text import PHONE_RE, URL_RE


def test_merge_counts(inventory):
    ids = [row["id"] for row in inventory["listings"]]
    assert len(ids) == 189
    assert len(set(ids)) == 189
    assert sum(i.startswith("C-") for i in ids) == 100
    assert sum(i.startswith("R-") for i in ids) == 89
    reasons = [r["reason"] for r in inventory["meta"]["removed"]]
    assert reasons.count("exact duplicate within raw") == 10
    assert sum(r.startswith("same listing") for r in reasons) == 1


def test_int_cells_are_text(listings):
    mazda = next(row for row in listings.values() if row["make"] == "mazda" and row["model"] == "3")
    dbx = next(row for row in listings.values() if row["model"] == "dbx")
    assert mazda["model"] == "3"
    assert dbx["trim"] == "707"


def test_only_one_honda_and_it_is_the_crv(listings):
    hondas = [row for row in listings.values() if row["make"] == "honda"]
    assert len(hondas) == 1
    h = hondas[0]
    assert h["id"].startswith("R-")
    assert h["fields"]["mileage_km"]["value"] == 79000
    assert h["fields"]["exterior_color"]["value"] == "white"
    assert h["fields"]["body_type"]["value"] == "suv"
    assert h["fields"]["price_aed"]["value"] is None
    assert h["fields"]["monthly_aed"]["value"] == 1048
    assert h["fields"]["has_warranty"]["value"] is False


def test_managed_flag_comes_from_boilerplate(listings):
    managed = [row for row in listings.values() if row["fields"]["is_dubizzle_managed"]["value"]]
    assert len(managed) == 10
    assert all(row["id"].startswith("R-") for row in managed)
    assert all("dubizzle cars" not in row["description_clean"].lower() for row in managed)


def test_export_only_flagged(listings):
    export = {row["model"] for row in listings.values() if row["fields"]["is_export_only"]["value"]}
    assert {"j14", "wingle 5", "land cruiser 70 series"} <= export


def test_velar_price_and_monthly(listings):
    velar = listings["C-003"]
    assert velar["fields"]["price_aed"]["value"] == 119750
    assert "119,750" in velar["fields"]["price_aed"]["evidence"]
    assert velar["fields"]["monthly_aed"]["value"] == 1876
    assert velar["fields"]["mileage_km"]["value"] == 68000
    assert velar["fields"]["has_warranty"]["value"] is True


def test_camry_km_is_not_its_price(listings):
    camry = next(row for row in listings.values() if row["model"] == "camry")
    assert camry["fields"]["price_aed"]["value"] == 36999
    assert camry["fields"]["mileage_km"]["value"] == 169859


def test_byd_range_is_not_mileage(listings):
    byd = next(row for row in listings.values() if row["make"] == "byd")
    assert byd["fields"]["mileage_km"]["value"] is None
    assert any(r["value"] == 701 for r in byd["rejected"])


def test_salary_and_fees_rejected():
    price, monthly, rejected = extract_prices(
        "Salary requirement: AED 3000 (WPS). Condition report for only AED 369. "
        "AED 1,000 - Evaluation. Selling Price: AED 204,999"
    )
    assert price.value == 204999
    assert monthly.value is None
    assert {r["value"] for r in rejected} >= {3000.0, 369.0, 1000.0}


def test_instalment_not_mistaken_for_total():
    price, monthly, _ = extract_prices("1,349,999 AED / 25,683 AED per Month with 20% Down")
    assert price.value == 1349999
    assert monthly.value == 25683
    price, monthly, _ = extract_prices(
        "Starting from 1611 per month Payable in 60 months. AED 106000"
    )
    assert price.value == 106000
    assert monthly.value == 1611


def test_warranty_km_caps_and_speeds_rejected():
    mileage, _, rejected = extract_mileage(
        "Ford warranty until 6/2028 or 100,000 kms. 0-100 km/h in 3.8 sec. Top speed 250 km/h. "
        "Last Service: 17,611 Km. Mileage: 37,062 km",
        "",
    )
    assert mileage.value == 37062
    assert 100000.0 in {r["value"] for r in rejected}


def test_brand_new_tyres_are_not_a_new_car():
    _, brand_new, _ = extract_mileage("Brand new tyres, mileage 42,000 km", "Rolls Royce Wraith")
    assert brand_new.value is False
    mileage, brand_new, _ = extract_mileage("Odometer : 0 KM Brand New Warranty", "Opel Grandland")
    assert brand_new.value is True
    assert mileage.value == 0


def test_no_contact_details_survive_sanitizing(listings):
    for row in listings.values():
        assert not PHONE_RE.search(row["description_clean"]), row["id"]
        assert not URL_RE.search(row["description_clean"]), row["id"]
        assert not PHONE_RE.search(row["english_summary"]), row["id"]


def test_sanitizer_keeps_facts_and_drops_ctas():
    text = clean_html(
        "Full service history.<br>Service contract until 2028.<br>Contact us now on +971 50 123 4567!"
        "<br>Follow us on Instagram @dealer<br>Mileage: 45,000 km"
    )
    out = sanitize(text)
    assert "service history" in out.clean.lower()
    assert "service contract" in out.clean.lower()
    assert "45,000 km" in out.clean
    assert "instagram" not in out.clean.lower()
    assert "971" not in out.clean
    assert out.dealer_contact["phones"] == ["971501234567"]


def test_year_column_wins_over_title(listings):
    assert listings["C-052"]["year"] == 2015
    assert "2014" in listings["C-052"]["title"]


def test_arabic_only_rows_are_searchable_in_english(listings):
    arabic = [row for row in listings.values() if row["language"] == "ar"]
    assert len(arabic) >= 5
    for row in arabic:
        assert row["english_summary"]
        assert row["make"] in row["keywords_en"]
    patrol = next(row for row in arabic if row["model"] == "patrol safari")
    assert "super safari" in patrol["keywords_en"]


def test_shared_dealer_paragraph_marked_boilerplate(listings):
    boiler = [row["id"] for row in listings.values() if row["description_quality"] == "boilerplate"]
    assert len(boiler) >= 3


def test_loader_reads_both_sheets(xlsx_path):
    rows, removed = load_all(xlsx_path)
    assert len(rows) == 189
    assert all(r.id for r in rows)
    assert all(r.trim for r in rows)
