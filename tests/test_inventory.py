"""
The committed inventory must reflect the workbook's quirks, not paper over them.

These assertions pin the facts found by inspecting the data: the merged count,
the one Honda, the ten managed rows, the BYD range decoy, the int-typed cells.
"""

from __future__ import annotations

from dubizzle_assistant.ingest.enrich import _figure_in_text, merge
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


def test_a_zero_reading_needs_a_distance():
    def ad(text):
        return {"title": "", "description_clean": text, "description_raw": ""}

    # Both of these phrases are in half the ads, and each one used to ground a 0 km
    # reading the model had invented for a used car.
    assert not _figure_in_text(0, ad("Instant torque, smooth acceleration, zero emissions"))
    assert not _figure_in_text(0, ad("Auto Loan at 0% Down Payment, 2022 Nissan X-Trail"))
    assert _figure_in_text(0, ad("2025 Hyundai Tucson 0km, brand new"))
    assert _figure_in_text(0, ad("Odometer : 0 KM Brand New Warranty"))
    assert _figure_in_text(0, ad("Mileage: zero, still in the wrapper"))
    # A real figure is still matched by the digits printed in the ad.
    assert _figure_in_text(169859, ad("Driven 169,859 km"))
    assert not _figure_in_text(169859, ad("Driven 12,000 km"))


def test_a_monthly_needs_monthly_wording():
    def rec(text):
        return {
            "id": "C-000",
            "title": "",
            "description_clean": text,
            "description_raw": "",
            "fields": {},
        }

    # The model read this car's cash price back as an instalment, which the ad never mentions.
    r = rec("Renault Megane RS 2020 Payment: AED 54,500 ---------")
    merge(r, {"monthly_aed": 54500}, [])
    assert "monthly_aed" not in r["fields"]

    r = rec("2020 C-Class, 200 hp, GCC spec, agency maintained")
    merge(r, {"monthly_aed": 200}, [])
    assert "monthly_aed" not in r["fields"]

    # The wordings these ads actually use are all accepted.
    for text, n in [
        ("GLS 63 AMG | From AED 5,805/mo | Up to 3Y Warranty", 5805),
        ("Option 2 - AED 2,731 P/M for 5 years with 20% Downpayment", 2731),
        ("From 1099 Pm. Massive Price Drop", 1099),
        ("Only AED 1,876 per month", 1876),
    ]:
        r = rec(text)
        merge(r, {"monthly_aed": n}, [])
        assert r["fields"]["monthly_aed"]["value"] == n, text


def test_the_word_for_empty_is_not_a_colour():
    def rec(**fields):
        return {
            "id": "C-000",
            "title": "",
            "description_clean": "",
            "description_raw": "",
            "keywords_en": "",
            "fields": fields,
        }

    # 118 fields in the committed build carried the string "null" as their value.
    for word in ("null", "None", " N/A ", "unknown", "not stated", "-", "  "):
        r = rec()
        merge(r, {"exterior_color": word, "transmission": word}, [])
        assert r["fields"] == {}, word

    # Worse than cosmetic: it overwrote a colour regex had read out of the ad.
    r = rec(
        exterior_color={"value": "black", "source": "regex", "evidence": "black", "confidence": 0.5}
    )
    merge(r, {"exterior_color": "null"}, [])
    assert r["fields"]["exterior_color"]["value"] == "black"

    # A real answer still lands.
    r = rec()
    merge(
        r, {"exterior_color": "Diamond White", "english_summary": "none", "keywords_en": "null"}, []
    )
    assert r["fields"]["exterior_color"]["value"] == "diamond white"
    assert not r.get("english_summary") and not r["keywords_en"]


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
