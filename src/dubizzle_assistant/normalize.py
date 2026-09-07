"""
Turn what people type into what the data uses: makes, models, money, numbers.

The dataset is lowercase and inconsistent ("land rover" holds every Range Rover,
"glc coupe" and "glc-class" are both present), and users say "Merc" and "$20k".
Every mapping here is a documented step so the trace can show it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

USD_TO_AED = 3.6725  # the dirham has been pegged at this rate since 1997

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

DATASET_MAKES: tuple[str, ...] = (
    "aston martin",
    "audi",
    "bentley",
    "bestune",
    "bmw",
    "bugatti",
    "byd",
    "chery",
    "chevrolet",
    "dodge",
    "ferrari",
    "ford",
    "genesis",
    "gwm",
    "haval",
    "honda",
    "hummer",
    "hyundai",
    "infiniti",
    "jac",
    "jaguar",
    "jeep",
    "kaiyi",
    "kia",
    "lamborghini",
    "land rover",
    "lexus",
    "lincoln",
    "maserati",
    "mazda",
    "mclaren",
    "mercedes-benz",
    "mini",
    "mitsubishi",
    "nissan",
    "opel",
    "peugeot",
    "porsche",
    "renault",
    "rolls-royce",
    "tesla",
    "tova",
    "toyota",
    "volkswagen",
    "volvo",
    "xiaomi",
)

MAKE_ALIASES: dict[str, str] = {
    **{m: m for m in DATASET_MAKES},
    "merc": "mercedes-benz",
    "mercedes": "mercedes-benz",
    "mercedes benz": "mercedes-benz",
    "benz": "mercedes-benz",
    "mercedes-benz": "mercedes-benz",
    "amg": "mercedes-benz",
    "range rover": "land rover",
    "rangerover": "land rover",
    "landrover": "land rover",
    "land rover": "land rover",
    "velar": "land rover",
    "evoque": "land rover",
    "defender": "land rover",
    "discovery": "land rover",
    "rolls": "rolls-royce",
    "rolls royce": "rolls-royce",
    "rolls-royce": "rolls-royce",
    "rr": "rolls-royce",
    "chevy": "chevrolet",
    "vw": "volkswagen",
    "beemer": "bmw",
    "bimmer": "bmw",
    "lambo": "lamborghini",
    "aston": "aston martin",
    "patrol": "nissan",
    "land cruiser": "toyota",
    "landcruiser": "toyota",
    "prado": "toyota",
    "camry": "toyota",
    "corolla": "toyota",
    "g-wagon": "mercedes-benz",
    "g wagon": "mercedes-benz",
    "gwagon": "mercedes-benz",
    "g63": "mercedes-benz",
    # Arabic spellings that appear in the listings or that users type
    "مرسيدس": "mercedes-benz",
    "نيسان": "nissan",
    "تويوتا": "toyota",
    "بي ام دبليو": "bmw",
    "لكزس": "lexus",
    "شفروليه": "chevrolet",
    "شيفروليه": "chevrolet",
    "هوندا": "honda",
    "فورد": "ford",
    "اودي": "audi",
    "أودي": "audi",
    "بورش": "porsche",
    "كيا": "kia",
    "هيونداي": "hyundai",
    "ميني": "mini",
    "جاكوار": "jaguar",
    "جاكور": "jaguar",
    "بنتلي": "bentley",
    "رولز رويس": "rolls-royce",
    "لاند روفر": "land rover",
    "رنج روفر": "land rover",
    "ميتسوبيشي": "mitsubishi",
    "باجيرو": "mitsubishi",
    "باترول": "nissan",
    "لاندكروزر": "toyota",
    "لاند كروزر": "toyota",
}

# Phrases that pin the model as well as the make. Longer phrases first.
MODEL_ALIASES: list[tuple[str, str, str]] = [
    ("range rover velar", "land rover", "range rover velar"),
    ("range rover evoque", "land rover", "range rover evoque"),
    ("range rover sport", "land rover", "range rover sport"),
    ("range rover", "land rover", "range rover"),
    ("velar", "land rover", "range rover velar"),
    ("evoque", "land rover", "range rover evoque"),
    ("land cruiser 70", "toyota", "land cruiser 70 series"),
    ("land cruiser 79", "toyota", "land cruiser 70 series"),
    ("landcruiser 79", "toyota", "land cruiser 70 series"),
    ("land cruiser", "toyota", "land cruiser"),
    ("landcruiser", "toyota", "land cruiser"),
    ("patrol safari", "nissan", "patrol safari"),
    ("super safari", "nissan", "patrol safari"),
    ("patrol", "nissan", "patrol"),
    ("g-class brabus", "mercedes-benz", "g-class brabus"),
    ("brabus", "mercedes-benz", "g-class brabus"),
    ("g-wagon", "mercedes-benz", "g-class"),
    ("g wagon", "mercedes-benz", "g-class"),
    ("g63", "mercedes-benz", "g-class"),
    ("g class", "mercedes-benz", "g-class"),
    ("glc coupe", "mercedes-benz", "glc coupe"),
    ("glc", "mercedes-benz", "glc-class"),
    ("gle", "mercedes-benz", "gle-class"),
    ("gls", "mercedes-benz", "gls-class"),
    ("gla", "mercedes-benz", "gla-class"),
    ("glk", "mercedes-benz", "glk-class"),
    ("cla", "mercedes-benz", "cla-class"),
    ("cls", "mercedes-benz", "cls-class"),
    ("c300", "mercedes-benz", "c-class"),
    ("c200", "mercedes-benz", "c-class"),
    ("c63", "mercedes-benz", "c-class"),
    ("c43", "mercedes-benz", "c-class"),
    ("c class", "mercedes-benz", "c-class"),
    ("c-class", "mercedes-benz", "c-class"),
    ("e350", "mercedes-benz", "e-class"),
    ("e450", "mercedes-benz", "e-class"),
    ("e200", "mercedes-benz", "e-class"),
    ("e class", "mercedes-benz", "e-class"),
    ("e-class", "mercedes-benz", "e-class"),
    ("s class", "mercedes-benz", "s-class"),
    ("s-class", "mercedes-benz", "s-class"),
    ("a45", "mercedes-benz", "a-class"),
    ("v class", "mercedes-benz", "v-class"),
    ("v220", "mercedes-benz", "v-class"),
    ("sprinter", "mercedes-benz", "sprinter"),
    ("pajero sport", "mitsubishi", "pajero sport"),
    ("pajero", "mitsubishi", "pajero"),
    ("x-trail", "nissan", "x-trail"),
    ("xtrail", "nissan", "x-trail"),
    ("cr-v", "honda", "cr-v"),
    ("crv", "honda", "cr-v"),
    ("rav4", "toyota", "rav 4"),
    ("rav 4", "toyota", "rav 4"),
    ("model x", "tesla", "model x"),
    ("cullinan", "rolls-royce", "cullinan"),
    ("phantom", "rolls-royce", "phantom"),
    ("ghost", "rolls-royce", "ghost"),
    ("wraith", "rolls-royce", "wraith"),
    ("dawn", "rolls-royce", "dawn"),
    ("bentayga", "bentley", "bentayga"),
    ("flying spur", "bentley", "continental"),
    ("continental", "bentley", "continental"),
    ("f-pace", "jaguar", "f-pace"),
    ("cayenne", "porsche", "cayenne"),
    ("wrangler", "jeep", "wrangler"),
    ("tucson", "hyundai", "tucson"),
    ("sportage", "kia", "sportage"),
    ("camry", "toyota", "camry"),
    ("corolla", "toyota", "corolla"),
    ("prado", "toyota", "prado"),
    ("hilux", "toyota", "hilux"),
    ("tundra", "toyota", "tundra"),
    ("yaris", "toyota", "yaris"),
    ("hiace", "toyota", "hiace"),
    ("explorer", "ford", "explorer"),
    ("mustang", "ford", "mustang"),
    ("territory", "ford", "territory"),
    ("tahoe", "chevrolet", "tahoe"),
    ("malibu", "chevrolet", "malibu"),
    ("camaro", "chevrolet", "camaro"),
    ("challenger", "dodge", "challenger"),
    ("charger", "dodge", "charger"),
    ("countryman", "mini", "countryman"),
    ("cooper", "mini", "cooper"),
    ("xc60", "volvo", "xc60"),
    ("levante", "maserati", "levante"),
    ("ghibli", "maserati", "ghibli"),
    ("aventador", "lamborghini", "aventador"),
    ("revuelto", "lamborghini", "revuelto"),
    ("chiron", "bugatti", "chiron"),
    ("dbx", "aston martin", "dbx"),
    ("vanquish", "aston martin", "vanquish"),
    ("sf90", "ferrari", "sf90 stradale"),
    ("f430", "ferrari", "f430"),
    ("q8", "audi", "q8"),
    ("q7", "audi", "q7"),
    ("rs7", "audi", "rs7"),
    ("x6", "bmw", "x6"),
    ("x1", "bmw", "x1"),
    ("i4", "bmw", "i4"),
    ("ix3", "bmw", "ix3"),
    ("m4", "bmw", "m4"),
    ("m5", "bmw", "m5"),
    ("m2", "bmw", "2-series"),
    ("320i", "bmw", "3-series"),
    ("325i", "bmw", "3-series"),
    ("3 series", "bmw", "3-series"),
    ("3-series", "bmw", "3-series"),
    ("باترول", "nissan", "patrol"),
    ("كامري", "toyota", "camry"),
    ("كورولا", "toyota", "corolla"),
    ("لاند كروزر", "toyota", "land cruiser"),
    ("لاندكروزر", "toyota", "land cruiser"),
    ("رنج روفر", "land rover", "range rover"),
    ("ماليبو", "chevrolet", "malibu"),
    ("باجيرو", "mitsubishi", "pajero"),
    ("تاهو", "chevrolet", "tahoe"),
    ("برادو", "toyota", "prado"),
]

BODY_TYPE_ALIASES: dict[str, str] = {
    "suv": "suv",
    "suvs": "suv",
    "4x4": "suv",
    "4wd": "suv",
    "jeep": "suv",
    "crossover": "suv",
    "family car": "suv",
    "7 seater": "suv",
    "seven seater": "suv",
    "sedan": "sedan",
    "saloon": "sedan",
    "coupe": "coupe",
    "coupé": "coupe",
    "hatchback": "hatchback",
    "hatch": "hatchback",
    "pickup": "pickup",
    "pick-up": "pickup",
    "pick up": "pickup",
    "truck": "pickup",
    "van": "van",
    "minivan": "van",
    "mpv": "van",
    "bus": "van",
    "convertible": "convertible",
    "cabriolet": "convertible",
    "cabrio": "convertible",
    "roadster": "convertible",
    "spider": "convertible",
    "spyder": "convertible",
    "drophead": "convertible",
    "wagon": "wagon",
    "estate": "wagon",
}


def normalize_digits(text: str) -> str:
    return text.translate(ARABIC_DIGITS)


def parse_number(raw: str) -> float | None:
    """Parse '115,750.00', '25.000', '89 900', '1,349,999', '150k', '1.2M', '150 thousand'."""
    s = normalize_digits(raw).strip().lower().replace(" ", " ")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(k|m|thousand|million|mil)\b", s)
    if m:
        return float(m.group(1)) * (1_000 if m.group(2) in ("k", "thousand") else 1_000_000)
    s = s.rstrip("/-").strip()
    # A dot followed by exactly three digits is a thousands separator here ("25.000AED").
    if re.fullmatch(r"\d{1,3}(?:[.,\s]\d{3})+", s):
        return float(re.sub(r"[.,\s]", "", s))
    if re.fullmatch(r"\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?", s):
        return float(re.sub(r"[,\s]", "", s))
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    return None


@dataclass
class Money:
    amount_aed: float
    mode: str  # cash or monthly
    steps: list[str] = field(default_factory=list)


_MONTHLY_HINT = re.compile(
    r"\b(a|per)\s+month\b|/\s*mo(nth)?\b|\bmonthly\b|\bp\.?m\.?\b|\binstal", re.I
)
_MONEY_RE = re.compile(
    r"(\$|usd|dollars?|aed|dhs|dirhams?|درهم)?\s*(\d[\d,\. ]*\s*(?:k|m|thousand|million|mil)?\b)\s*(\$|usd|dollars?|aed|dhs|dirhams?|درهم)?"
)


# The dirham is pegged to the dollar, which is the only reason those two convert. Everything here
# floats, so a rate written into the source would be wrong within a week. Reading "25,000 euros"
# as 25,000 AED was worse than not reading it: the figure reached the SQL, the price ceiling the
# buyer is judged against, and a lead row that then contradicted its own budget_original_text.
_FOREIGN_MONEY_RE = re.compile(
    r"\b(euros?|eur|pounds?|sterling|gbp|rupees?|inr|riyals?|sar|qar|kwd|bhd|omr"
    r"|dinars?|yen|jpy|yuan|rmb|cny|rand|zar|lira|roubles?|rubles?|francs?|chf)\b"
    r"|[€£₹¥]",
    re.I,
)


def unsupported_currency(text: str) -> str | None:
    """The currency beside a figure that this system will not convert, if there is one."""
    m = _FOREIGN_MONEY_RE.search(normalize_digits(text.lower()))
    return m.group(0) if m else None


def parse_budget(text: str) -> Money | None:
    """Pull one budget figure out of free text, converting dollars at the peg."""
    t = normalize_digits(text.lower())
    if unsupported_currency(t):
        return None
    m = _MONEY_RE.search(t)
    if not m:
        return None
    value = parse_number(m.group(2))
    if value is None:
        return None
    steps: list[str] = []
    cur = (m.group(1) or m.group(3) or "").strip()
    amount = value
    if cur in {"$", "usd", "dollar", "dollars"}:
        amount = round(value * USD_TO_AED)
        steps.append(f"{m.group(0).strip()} -> {amount:,.0f} AED (peg {USD_TO_AED})")
    else:
        steps.append(f"{m.group(0).strip()} -> {amount:,.0f} AED")
    mode = "monthly" if _MONTHLY_HINT.search(t) else "cash"
    if mode == "monthly":
        steps.append("month context -> monthly budget")
    return Money(amount_aed=amount, mode=mode, steps=steps)


def canonical_make(text: str) -> tuple[str | None, str]:
    """Map a user phrase to a dataset make. Returns (make, step_description)."""
    t = text.strip().lower()
    if t in MAKE_ALIASES:
        return MAKE_ALIASES[t], f"{text} -> {MAKE_ALIASES[t]} (alias)"
    return (t or None), f"{text} -> {t} (as typed)"


def _phrase_in(phrase: str, text: str) -> bool:
    # A trailing s covers "hondas" and "suvs" without matching "hondal".
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?:s|es)?(?![\w-])", text) is not None


def resolve_make_model(text: str) -> tuple[str | None, str | None, list[str]]:
    """Find a make and model mentioned anywhere in a phrase."""
    t = normalize_digits(text.lower())
    steps: list[str] = []
    # The loaded inventory goes first. A static alias mapped "flying spur" to continental, so
    # the two Flying Spurs in stock were unreachable by their own name and the reply named a
    # different car. What the data holds outranks what the table guessed.
    for phrase, make, model in [*DATA_MODEL_ALIASES, *MODEL_ALIASES]:
        if _phrase_in(phrase, t):
            steps.append(f"{phrase} -> make {make}, model {model} (alias)")
            return make, model, steps
    for phrase in sorted(MAKE_ALIASES, key=len, reverse=True):
        if _phrase_in(phrase, t):
            steps.append(f"{phrase} -> make {MAKE_ALIASES[phrase]} (alias)")
            return MAKE_ALIASES[phrase], None, steps
    return None, None, steps


def canonical_body_type(text: str) -> str | None:
    return BODY_TYPE_ALIASES.get(text.strip().lower())


# Whatever inventory is loaded teaches the resolver its makes and models; the static tables above are the seed.
KNOWN_MAKES: set[str] = set(DATASET_MAKES)
DATA_MODEL_ALIASES: list[tuple[str, str, str]] = []


def known_makes() -> set[str]:
    return KNOWN_MAKES


def register_makes(makes: Iterable[str]) -> int:
    added = 0
    for raw in makes:
        m = (raw or "").strip().lower()
        if not m:
            continue
        KNOWN_MAKES.add(m)
        if m not in MAKE_ALIASES:
            MAKE_ALIASES[m] = m
            added += 1
    return added


def register_models(pairs: Iterable[tuple[str, str]]) -> int:
    known = {p for p, _, _ in DATA_MODEL_ALIASES}
    added = 0
    for make, model in pairs:
        phrase = (model or "").strip().lower()
        # Short or numeric model names ("3", "x5") would match everywhere, so they stay out.
        if len(phrase) < 4 or not re.search(r"[a-z]{3}", phrase):
            continue
        # A phrase a static alias claims is registered anyway, because this model is in stock and
        # the resolver reads the data table first. Only a make this inventory really has still
        # wins, which leaves "genesis" a make and gives "discovery" back to Land Rover.
        if phrase in known or phrase in KNOWN_MAKES:
            continue
        DATA_MODEL_ALIASES.append((phrase, make.strip().lower(), phrase))
        known.add(phrase)
        added += 1
    DATA_MODEL_ALIASES.sort(key=lambda t: len(t[0]), reverse=True)
    return added
