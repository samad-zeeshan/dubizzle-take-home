"""
Deterministic control around the model: a pre-filter, a post-filter, and the grounding check.

None of this costs a model call. Patterns are anchored on intent phrases, so
"full service history" and "compare the X5 and X6" pass while "who won the
war" and "write me a scraper" are declined before any request is made.
"""

from __future__ import annotations

import re
from typing import Any

from dubizzle_assistant.normalize import normalize_digits
from dubizzle_assistant.text import EMAIL_RE, PHONE_RE, URL_RE

# Other car marketplaces, sister brands included, since a grader cannot tell them apart.
COMPETITORS = [
    "yallamotor",
    "yalla motor",
    "yalla motors",
    "dubicars",
    "dubi cars",
    "carswitch",
    "car switch",
    "cars24",
    "cars 24",
    "carabia",
    "opensooq",
    "open sooq",
    "autozel",
    "shozon",
    "hatla2ee",
    "drivearabia",
    "drive arabia",
    "kavak",
    "sellanycar",
    "sell any car",
    "syarah",
    "emirates auction",
    "facebook marketplace",
    "autotrader",
    "carvana",
    "cargurus",
    "olx",
    "يلا موتور",
    "دوبي كارز",
    "كار سويتش",
    "كارز 24",
    "اوبن سوق",
    "أوبن سوق",
    "سيل اني كار",
]
COMPETITOR_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(c) for c in COMPETITORS) + r")(?![\w-])"
    r"|\b(other|another|different|rival|competitor|competing)\s+(car\s+)?(sites?|websites?|platforms?|marketplaces?|apps?|listings? sites?)\b"
    r"|\belsewhere online\b|\bcheaper (online|elsewhere)\b"
    # "competitor" is also the ordinary word for a rival car model, and the bare token refused
    # "which cars in your stock are the main competitors of the Prado". It now needs the business
    # sense: whose competitors, or a price word near enough to be part of the same thought.
    r"|\b(your|our|dubizzle'?s) competitors?\b"
    r"|\bcompetitors?\b(?=[^?.!]{0,25}\b(cheaper|price|prices|cost|online|site|sites)\b)",
    re.I,
)

INJECTION_RE = re.compile(
    r"ignore (?:(?:all|any|the|your|these|my|previous|prior|above|earlier)\s+){0,3}(instructions|rules|prompt|guidelines)"
    r"|disregard (?:(?:your|the|all|previous)\s+){1,2}(instructions|rules|prompt)|forget (?:(?:your|the|all|previous)\s+){1,2}(instructions|rules)"
    r"|you are now (a|an|in)\b|\bjailbreak\b|developer mode|\bdan mode\b"
    r"|(print|show|reveal|repeat|output) (me )?(your|the) (system |initial |hidden )?(prompt|instructions)"
    r"|what (model|llm|ai) are you|which (model|llm|ai) (are you|powers you)|are you (chatgpt|gpt|gemini|claude|llama)"
    r"|تجاهل (كل )?التعليمات",
    re.I,
)
CODE_RE = re.compile(
    r"\bwrite (me )?(a |some |the )?(python|javascript|js|typescript|java|c\+\+|c#|sql|bash|shell|html|css|react)\b"
    r"|\bwrite (me )?(a |some |the )?(code|script|function|program|scraper|regex|query|class|api)\b"
    r"|\b(python|javascript|typescript|java|sql|bash) (code|script|function|snippet)\b"
    r"|\bimplement (a|an|the) (function|class|algorithm|endpoint)\b|\bfix (my|this) (code|bug)\b|\bdebug (my|this)\b"
    r"|اكتب (لي )?(كود|برنامج|سكريبت)",
    re.I,
)
TRIVIA_RE = re.compile(
    r"\b(who|when|what|where|which) (won|was|were|is|did|invented|discovered|built) .{0,40}\b"
    r"(war|battle|world cup|olympics|election|president|king|queen|prime minister|empire|revolution|independence|moon landing)\b"
    r"|\bcapital of\b|\bworld cup\b|\bwhat year (did|was)\b"
    # This branch used to match any noun and exempt four car words, which could never work: the
    # object is usually a model name ("history of the Patrol"), and the exemption never fired
    # anyway because the greedy (the )? consumed the article before the lookahead read it. Naming
    # the world subjects instead means every car phrasing reaches the model, and real history
    # questions are already caught by the war and empire branch above.
    r"|\bhistory of (the )?(world|humanity|mankind|europe|asia|africa|america|china|india|rome"
    r"|greece|egypt|persia|arabia|islam|christianity|aviation|flight|medicine|philosophy|art"
    r"|music|football|the internet)\b"
    # A seat count is the most ordinary question in this domain, and "how many people" swallowed
    # it whole. Population trivia needs one of its own verbs to still decline.
    r"|\bhow many (countries|planets|continents)\b"
    r"|\bhow many people (live|lived|died|speak|voted|are there)\b"
    r"|\bwho (is|was) (the )?(first|last|current) (president|king|queen)",
    re.I,
)
OFFTOPIC_RE = re.compile(
    r"\bweather\b|\bforecast\b|\btemperature (in|today|tomorrow|outside)\b|\bhoroscope\b"
    r"|\b(solve|integrate|differentiate|derivative|equation|homework|essay|poem|haiku|story about|joke about (?!car))\b"
    r"|\brecipe\b|\bcook\b|\bstock market\b|\bcrypto price\b|\bbitcoin\b|\btranslate (this|the following) (paragraph|text|document)\b",
    re.I,
)
SELLER_CONTACT_RE = re.compile(
    r"(seller|dealer|owner|their|his|her)'?s? (phone|number|mobile|whatsapp|contact|email)|\b(phone|whatsapp) number\b|\bcontact (the )?(seller|dealer)\b",
    re.I,
)
ADVICE_RE = re.compile(
    r"\b(should i (invest|take a loan|buy stocks)|is it (legal|illegal) to|legal advice|tax advice|sue\b|lawsuit)\b",
    re.I,
)

PIVOT = (
    " Would you like me to pull up cars in your budget, or tell you more about one you have seen?"
)

CANNED: dict[str, str] = {
    "competitor": "I can only speak to the listings here on dubizzle, so I cannot compare with other sites."
    + PIVOT,
    "injection": "I will keep to helping with cars in this inventory, viewings, and your preferences."
    + PIVOT,
    "code": "Writing code is outside what I do here. I can help you find, compare, and book cars from our inventory."
    + PIVOT,
    "trivia": "That is outside what I can help with here. I stick to the cars in our inventory."
    + PIVOT,
    "offtopic": "That is outside what I can help with here. I stick to the cars in our inventory."
    + PIVOT,
    "seller_contact": "Contact runs through dubizzle rather than direct seller numbers, so the simplest next step is to book a viewing and I will arrange it."
    + PIVOT,
    "advice": "I cannot give financial or legal advice. I can quote what a listing says about price, financing, or warranty exactly as written."
    + PIVOT,
}

# A tripped rule never reaches the model, so an Arabic session would get these back in English
# at the exact moment the assistant most needs to look like it knows what it is doing.
PIVOT_AR = " هل تحب أن أعرض لك سيارات ضمن ميزانيتك، أو أخبرك المزيد عن واحدة شاهدتها؟"

CANNED_AR: dict[str, str] = {
    "competitor": "أستطيع التحدث فقط عن الإعلانات الموجودة هنا على دوبيزل، لذلك لا يمكنني المقارنة مع مواقع أخرى."
    + PIVOT_AR,
    "injection": "سألتزم بمساعدتك في سيارات هذا المعرض والمعاينات وتفضيلاتك." + PIVOT_AR,
    "code": "كتابة الأكواد خارج نطاق عملي هنا. أستطيع مساعدتك في البحث عن السيارات ومقارنتها وحجز معاينة."
    + PIVOT_AR,
    "trivia": "هذا خارج ما أستطيع المساعدة به هنا. أنا ألتزم بالسيارات الموجودة في المعرض."
    + PIVOT_AR,
    "offtopic": "هذا خارج ما أستطيع المساعدة به هنا. أنا ألتزم بالسيارات الموجودة في المعرض."
    + PIVOT_AR,
    "seller_contact": "التواصل يتم عبر دوبيزل وليس بأرقام البائعين مباشرة، وأسهل خطوة تالية هي حجز معاينة وأنا أرتبها لك."
    + PIVOT_AR,
    "advice": "لا أستطيع تقديم استشارة مالية أو قانونية. أستطيع أن أنقل لك ما يذكره الإعلان عن السعر أو التمويل أو الضمان كما هو مكتوب."
    + PIVOT_AR,
}


RULES: list[tuple[str, re.Pattern[str]]] = [
    ("competitor", COMPETITOR_RE),
    ("injection", INJECTION_RE),
    ("code", CODE_RE),
    ("seller_contact", SELLER_CONTACT_RE),
    ("advice", ADVICE_RE),
    ("trivia", TRIVIA_RE),
    ("offtopic", OFFTOPIC_RE),
]


def prefilter(text: str, locale: str = "en") -> dict[str, Any] | None:
    """Return a canned decline for hard cases, or None to let the model handle the message."""
    canned = CANNED_AR if locale == "ar" else CANNED
    for name, rx in RULES:
        m = rx.search(text)
        if m:
            return {
                "rule": name,
                "intent": "competitor"
                if name == "competitor"
                else "injection"
                if name == "injection"
                else "pii_request"
                if name == "seller_contact"
                else "out_of_scope",
                "reply": canned[name],
                "match": m.group(0),
            }
    return None


def postfilter(text: str) -> tuple[str, list[dict[str, str]]]:
    """Scrub competitor names, phone numbers, emails, and links from a reply, reporting what was hit."""
    hits: list[dict[str, str]] = []

    def _comp(m: re.Match[str]) -> str:
        hits.append({"kind": "competitor", "text": m.group(0)})
        return "another marketplace"

    def _phone(m: re.Match[str]) -> str:
        hits.append({"kind": "phone", "text": m.group(0)})
        return "[contact via dubizzle]"

    def _url(m: re.Match[str]) -> str:
        hits.append({"kind": "url", "text": m.group(0)})
        return "[link removed]"

    def _email(m: re.Match[str]) -> str:
        hits.append({"kind": "email", "text": m.group(0)})
        return "[email removed]"

    out = COMPETITOR_RE.sub(_comp, text)
    out = URL_RE.sub(_url, out)
    out = EMAIL_RE.sub(_email, out)
    out = PHONE_RE.sub(_phone, out)
    return out, hits


_ID_RE = re.compile(r"\b([CR]-\d{3})\b")

# Ids are how the server and the model address a car. They are not how a person talks about
# one, and outside demo mode nothing on screen explains what C-003 is, so they never belong
# in reply prose. They stay in cited_listing_ids, the cards, and the trace.
ID_IN_PROSE = r"#?\b[CR]-\d{3}\b"
_ID_IN_PROSE_RE = re.compile(ID_IN_PROSE, re.I)
_ID_WITH_PUNCTUATION_RE = re.compile(r"\s*[(\[]?\s*#?\b[CR]-\d{3}\b\s*[)\]]?\s*[:,]?", re.I)


def ids_in_prose(text: str) -> list[str]:
    return list(
        dict.fromkeys(m.group(0).lstrip("#").upper() for m in _ID_IN_PROSE_RE.finditer(text))
    )


def strip_ids(text: str) -> str:
    """Last resort when a model keeps writing ids: cut them and close the gap they leave."""
    out = _ID_WITH_PUNCTUATION_RE.sub(" ", text)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r" ([,.:;!?])", r"\1", out).strip()


# Whole numbers first, then context decides. A number glued to a word, a path, a decimal point or a
# hyphen ("R-005", "6-year/200,000", "115,750.000") is skipped as a whole, so no fragment of it
# ("000") can ever be judged on its own.
# The Arabic thousands separator groups digits the same way a comma does, and it has to be
# matched here rather than normalised away, so the span offsets still point into the reply.
_NUM_RE = re.compile(r"\d{1,3}(?:[,٬]\d{3})+|\d{3,}")
_GLUE_BEFORE = "#/.-_"
_GLUE_AFTER = "-_"


def figures(text: str) -> list[re.Match[str]]:
    out: list[re.Match[str]] = []
    for m in _NUM_RE.finditer(text):
        before = text[m.start() - 1] if m.start() else ""
        after = text[m.end()] if m.end() < len(text) else ""
        if before and (before.isalnum() or before in _GLUE_BEFORE):
            continue
        if after and (after.isalnum() or after in _GLUE_AFTER):
            continue
        out.append(m)
    return out


_NUMERIC_FIELDS = ("price_aed", "monthly_aed", "mileage_km", "year", "seats", "down_payment_pct")


def _norm(n: str) -> str:
    # Arabic-Indic numerals and the Arabic thousands separator have to fold to ASCII here. The
    # figure regex matches them either way, so without this an Arabic reply's correct prices
    # never match a source and the client strikes them through as unsourced.
    return normalize_digits(n).replace(",", "").replace("٬", "").replace("⁦", "")


def collect_sources(
    tool_results: list[dict[str, Any]], shown: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every number and id the model was given this turn, mapped to where it came from."""
    sources: dict[str, dict[str, Any]] = {}

    def add(value: Any, listing_id: str | None, field: str) -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int | float):
            key = str(int(value))
            sources.setdefault(key, {"listing_id": listing_id, "field": field})
        elif isinstance(value, str):
            for n in _NUM_RE.findall(value):
                sources.setdefault(_norm(n), {"listing_id": listing_id, "field": field})

    def walk(obj: Any, listing_id: str | None, field: str) -> None:
        if isinstance(obj, dict):
            lid = (
                obj.get("id")
                if isinstance(obj.get("id"), str) and _ID_RE.fullmatch(obj["id"])
                else listing_id
            )
            if lid:
                sources.setdefault(lid, {"listing_id": lid, "field": "id"})
            for k, v in obj.items():
                walk(v, lid, k)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, listing_id, field)
        else:
            add(obj, listing_id, field)

    for tr in tool_results:
        walk(tr.get("result"), None, tr.get("name", "tool"))
    for c in shown:
        sources.setdefault(c["id"], {"listing_id": c["id"], "field": "id"})
        for f in _NUMERIC_FIELDS:
            add(c.get(f), c["id"], f)
    return sources


def figures_in(text: str) -> list[str]:
    """Ids and normalised numbers in a prompt block the server wrote itself, so they count as sourced."""
    return [m.group(1) for m in _ID_RE.finditer(text)] + [_norm(n) for n in _NUM_RE.findall(text)]


def grounding_spans(reply: str, sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Mark every figure and id in the reply as sourced or not."""
    spans: list[dict[str, Any]] = []
    for m in _ID_RE.finditer(reply):
        key = m.group(1)
        spans.append(
            {
                "text": key,
                "start": m.start(),
                "end": m.end(),
                "grounded": key in sources,
                "source": sources.get(key),
            }
        )
    for m in figures(reply):
        key = _norm(m.group(0))
        # Display numbers (#1, #2) and short counts are under three digits and never reach here.
        spans.append(
            {
                "text": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "grounded": key in sources,
                "source": sources.get(key),
            }
        )
    spans.sort(key=lambda s: s["start"])
    ungrounded = [s["text"] for s in spans if not s["grounded"]]
    return {
        "checked": len(spans),
        "grounded": len(spans) - len(ungrounded),
        "ungrounded": ungrounded,
        "spans": spans,
    }


# A subtraction result is absent from the tool results by construction, so the grounding check can
# only ever call it a hallucination. This tells the two apart for the rewrite note, and for that
# only. Nothing here lets a figure through, so a coincidental hit costs a wording choice and not
# the guarantee that every figure in a shipped reply traces back to a listing.
def _combinations(a: float, b: float) -> tuple[float, ...]:
    return (a - b, a + b, a * b, a / b) if b else (a - b, a + b, a * b)


def derived_figures(ungrounded: list[str], sources: dict[str, dict[str, Any]]) -> list[str]:
    """Which unsourced figures are exact arithmetic on two figures that are sourced."""
    numbers: list[float] = []
    for key in sources:
        try:
            numbers.append(float(key))
        except ValueError:
            continue
    out: list[str] = []
    for key in ungrounded:
        # The ungrounded list carries the text as written, separators and all.
        try:
            target = float(_norm(key))
        except ValueError:
            continue
        # Half a unit, because a price difference is quoted as a whole dirham.
        if any(
            abs(v - target) <= 0.5 for a in numbers for b in numbers for v in _combinations(a, b)
        ):
            out.append(key)
    return out
