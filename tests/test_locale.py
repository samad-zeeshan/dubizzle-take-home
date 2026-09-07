"""Arabic is a setting, not a guess: the prompt, the canned declines, and the figure check all follow it."""

from __future__ import annotations

from views.i18n import LANGS, STRINGS, enum_label, t

from dubizzle_assistant.services import guardrails


def test_both_languages_carry_every_key():
    en, ar = set(STRINGS["en"]), set(STRINGS["ar"])
    assert en == ar, f"only in en: {sorted(en - ar)} | only in ar: {sorted(ar - en)}"
    assert set(LANGS) == set(STRINGS)
    # A gap has to fall back rather than crash a page mid-render.
    assert t("nav.home", "ar") == "الرئيسية"
    assert t("no.such.key", "ar") == "no.such.key"
    assert t("nav.home", "de") == "Home"
    assert t("chat.welcome_back", "en", name="Sara") == "Welcome back, Sara."


def test_card_vocabulary_translates_without_a_model_call():
    assert enum_label("suv", "ar") == "دفع رباعي"
    assert enum_label("GCC", "ar") == "خليجي"
    assert enum_label("suv", "en") == "suv"
    # Anything outside the closed set is left exactly as it came.
    assert enum_label("xdrive20i", "ar") == "xdrive20i"
    assert enum_label(None, "ar") == ""


def test_canned_declines_answer_in_the_session_language():
    en = guardrails.prefilter("is this cheaper on yallamotor?")
    ar = guardrails.prefilter("is this cheaper on yallamotor?", "ar")
    assert en and ar and en["rule"] == ar["rule"] == "competitor"
    assert "dubizzle" in en["reply"]
    # A tripped rule never reaches the model, so this is the one path Arabic cannot come free.
    assert ar["reply"] != en["reply"] and "دوبيزل" in ar["reply"]
    assert set(guardrails.CANNED) == set(guardrails.CANNED_AR)


def test_arabic_numerals_are_grounded_not_struck_through():
    sources = {"93000": {"listing_id": "R-078", "field": "mileage_km"}}
    for reply in ("It has 93,000 km.", "المسافة ٩٣٬٠٠٠ كم.", "المسافة 93,000 كم."):
        r = guardrails.grounding_spans(reply, sources)
        assert r["ungrounded"] == [], reply
        assert r["grounded"] == 1
    # A figure that is genuinely not in the tool results still fails, in either script.
    assert guardrails.grounding_spans("المسافة ٩٩٬٩٩٩ كم.", sources)["ungrounded"]


def test_the_english_prompt_is_untouched_by_the_locale_block(client):
    def blocks(locale):
        r = client.post("/chat", json={"message": "any hondas?", "name": "Sara", "locale": locale})
        assert r.status_code == 200, r.text
        stage = next(
            s for s in r.json()["trace"]["stages"] if s["stage"] == "prompt" and s.get("blocks")
        )
        return [b["name"] for b in stage["blocks"]]

    # English has to stay byte-identical, or every recorded cassette call stops matching.
    assert "locale" not in blocks("en")
    assert "locale" in blocks("ar")


def test_the_static_block_carries_the_price_labelling_rule(client):
    r = client.post("/chat", json={"message": "any hondas?", "name": "Static"})
    stage = next(
        s for s in r.json()["trace"]["stages"] if s["stage"] == "prompt" and s.get("blocks")
    )
    static = next(b["text"] for b in stage["blocks"] if b["name"] == "static")
    assert "Copy the year, make, and model verbatim from the tool result." in static
    assert '"price not listed" rather than placing it under a budget' in static
    # The greeting rule is turn-dependent, so it must not sit in the cached prefix.
    assert "Greet" not in static
    # Arithmetic is barred outright, not only for financing: the figures come from the ad.
    assert "do no arithmetic on any figure" in static
    for banned in (
        "no totals",
        "no interest rates",
        "no cost per kilometre",
        "no sums across years",
    ):
        assert banned in static
    assert "calculate financing" not in static
    # One chat, one person. Switching accounts is a deliberate act elsewhere.
    assert "One chat belongs to one person" in static
    assert "changing who is signed in happens in the account panel" in static
