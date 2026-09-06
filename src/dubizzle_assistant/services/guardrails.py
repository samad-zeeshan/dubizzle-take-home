"""
Deterministic control around the model: a pre-filter, a post-filter, and the grounding check.

None of this costs a model call. Patterns are anchored on intent phrases, so
"full service history" and "compare the X5 and X6" pass while "who won the
war" and "write me a scraper" are declined before any request is made.
"""

from __future__ import annotations

import re
from typing import Any

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
    r"|\belsewhere online\b|\bcompetitors?\b|\bcheaper (online|elsewhere)\b",
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
    r"|\bcapital of\b|\bworld cup\b|\bwhat year (did|was)\b|\bhistory of (the )?(?!service|this car|the car|ownership)\w+"
    r"|\bhow many (people|countries|planets)\b|\bwho (is|was) (the )?(first|last|current) (president|king|queen)",
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

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("competitor", COMPETITOR_RE),
    ("injection", INJECTION_RE),
    ("code", CODE_RE),
    ("seller_contact", SELLER_CONTACT_RE),
    ("advice", ADVICE_RE),
    ("trivia", TRIVIA_RE),
    ("offtopic", OFFTOPIC_RE),
]


def prefilter(text: str) -> dict[str, Any] | None:
    """Return a canned decline for hard cases, or None to let the model handle the message."""
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
                "reply": CANNED[name],
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
_NUM_RE = re.compile(r"(?<![\w#/-])(\d{1,3}(?:,\d{3})+|\d{3,})(?![\w-])")
_NUMERIC_FIELDS = ("price_aed", "monthly_aed", "mileage_km", "year", "seats", "down_payment_pct")


def _norm(n: str) -> str:
    return n.replace(",", "")


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
    for m in _NUM_RE.finditer(reply):
        key = _norm(m.group(1))
        # Display numbers (#1, #2) and short counts are under three digits and never reach here.
        spans.append(
            {
                "text": m.group(1),
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
