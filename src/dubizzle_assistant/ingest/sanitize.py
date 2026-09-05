"""
Produce the text the model is allowed to see.

Half the descriptions carry dealer phone numbers, WhatsApp links, showroom
hours, and "contact us to book a test drive". Fed to the model, those become
its advice. So contact details are cut here, once, and only the clean view
ever reaches a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dubizzle_assistant.ingest.knowledge import BOILERPLATE_MARKERS, DEALER_NAME_RE, MANAGED_MARKERS
from dubizzle_assistant.text import (
    EMAIL_RE,
    HANDLE_RE,
    HASHTAG_RE,
    PHONE_RE,
    URL_RE,
    find_handles,
    find_phones,
    find_urls,
)

# Sentences with these are calls to action or dealer logistics, not facts about the car.
# Anchored on phrases so "service contract" and "full service history" survive.
_CTA_RE = re.compile(
    r"\bcontact\s+(us|me|our|now|for|the|:)|\bcontact\b\s*[:\-]|\bcall\s+(us|now|our|me|for|or|:)|\bcalling\b"
    r"|\bwhats?app\b|\bvisit\s+(us|our|the showroom)|\bfollow\s+us\b|\bdm\s+us\b|\bmessage\s+us\b"
    r"|\binstagram\b|\bfacebook\b|\btiktok\b|\bsnapchat\b|\byoutube\b|\blinkedin\b|\btwitter\b|\bpinterest\b"
    r"|\bopening\s+hours\b|\bworking\s+hours\b|\bshowroom\s+(hours|timing|no\b|number|\d)|\btimings?\s*:"
    r"|\bopen\s+(daily|7 days|all week|every ?day)|\bmonday\s*(to|-)\s*(saturday|friday|sunday)"
    r"|\bsaturday\s*(to|-)\s*(thursday|friday)|\bsat\s*-\s*thu|\bmon\s*-\s*(fri|sat)|\bsunday\s*:"
    r"|\bfriday\s*:|\bdaily\s*:|\bfor\s+(calling|whatsapp)\b|\bwe are located\b|\blocation\s*:"
    r"|\bsell\s+your\s+car\b|\bwant\s+to\s+sell\b|\bbuy\s+back\b|\bclick\s+(on\s+)?the\s+link"
    r"|\bjust\s+click\b|\bstay\s+connected\b|\bcheck\s+out\s+our\b|\bour\s+website\b|\bwebsite\s*:"
    r"|\bللتواصل\b|\bتفضلوا بزيارتنا\b|\bزيارتنا\b|\bاتصال\b|\bواتساب\b|\bالاتصال\b|\bللاستفسار\b|\bتواصل\b"
    r"|\bmobile\s+no\b|\bmob\s*:|\btel\s*:|\bphone\s*:|\boffice\s*:|\bsales\s*:",
    re.IGNORECASE,
)

# Decorative separator lines and emoji-only fragments.
_DECOR_RE = re.compile(r"^[\s\-_=~•*·▔▁▬═─━┄┈⸻—–.]{3,}$")
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff\U0001f900-\U0001f9ff"
    "\U0001fa70-\U0001faff\u2b50\u2b06\u2705\u274c\u2714\u2728\u203c\u2049\u3030\u303d\u3297\u3299"
    "\u00a9\u00ae\u2122\u2139\u2194-\u2199\u21a9\u21aa\u231a\u231b\u2328\u23cf\u23e9-\u23f3\u23f8-\u23fa"
    "\u24c2\u25aa\u25ab\u25b6\u25c0\u25fb-\u25fe\u2600-\u2604\u260e\u2611\u2614\u2615\u2618\u261d\u2620"
    "\u2622\u2623\u2626\u262a\u262e\u262f\u2638-\u263a\u2640\u2642\u2648-\u2653\u265f\u2660\u2663\u2665"
    "\u2666\u2668\u267b\u267e\u267f\u2692-\u2697\u2699\u269b\u269c\u26a0\u26a1\u26a7\u26aa\u26ab\u26b0"
    "\u26b1\u26bd\u26be\u26c4\u26c5\u26c8\u26ce\u26cf\u26d1\u26d3\u26d4\u26e9\u26ea\u26f0-\u26f5"
    "\u26f7-\u26fa\u26fd\u2702\u2705\u2708-\u270d\u270f\u2712\u2714\u2716\u271d\u2721\u2728\u2733"
    "\u2734\u2744\u2747\u274c\u274e\u2753-\u2755\u2757\u2763\u2764\u2795-\u2797\u27a1\u27b0\u27bf"
    "\u2934\u2935\u2b05-\u2b07\u2b1b\u2b1c\u2b50\u2b55\U0001f1e6-\U0001f1ff\ufe0f\u200d"
    "\ufe0f\u20e3]"
)
_KEYCAP_RE = re.compile(r"[0-9]\uFE0F?\u20E3")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟])\s+|\n+|\s+[|]\s+|\s+•\s+|\s+\*\s+(?=[A-Z])")


@dataclass
class Sanitized:
    clean: str
    dealer_contact: dict[str, list[str]] = field(default_factory=dict)
    dealer_name: str | None = None
    removed_sentences: int = 0
    is_dubizzle_managed: bool = False
    has_boilerplate: bool = False


def _cut_block(text: str, markers: tuple[str, ...]) -> tuple[str, bool]:
    """Remove everything from the first marker onward. Boilerplate always trails."""
    low = text.lower()
    positions = [low.find(m) for m in markers if m in low]
    if not positions:
        return text, False
    cut = min(positions)
    # Back up to the start of that sentence so no half sentence is left behind.
    start = max(low.rfind("\n", 0, cut), low.rfind(". ", 0, cut) + 1, 0)
    return text[:start].rstrip(), True


def sanitize(description_clean_html: str) -> Sanitized:
    text = description_clean_html
    contact = {
        "phones": sorted(set(find_phones(text))),
        "urls": sorted(set(find_urls(text))),
        "handles": sorted(set(find_handles(text))),
    }
    dealer_match = re.search(DEALER_NAME_RE, text)
    dealer_name = dealer_match.group(1) if dealer_match else None

    text, managed = _cut_block(text, MANAGED_MARKERS)
    text, boilerplate = _cut_block(text, BOILERPLATE_MARKERS)

    text = _KEYCAP_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = EMAIL_RE.sub(" ", text)
    text = PHONE_RE.sub(" ", text)
    text = HANDLE_RE.sub(" ", text)
    text = HASHTAG_RE.sub(" ", text)

    kept: list[str] = []
    removed = 0
    for piece in _SENTENCE_SPLIT_RE.split(text):
        s = piece.strip(" \t-–—•*|")
        if not s or _DECOR_RE.match(s):
            continue
        if _CTA_RE.search(s):
            removed += 1
            continue
        # A bare 7+ digit run after phone stripping is a landline or a leftover number.
        if re.fullmatch(r"[\d\s\-()+]{7,}", s):
            removed += 1
            continue
        kept.append(s)

    clean = " ".join(kept)
    clean = re.sub(r"\s{2,}", " ", clean).strip(" .-")
    return Sanitized(
        clean=clean,
        dealer_contact=contact,
        dealer_name=dealer_name,
        removed_sentences=removed,
        is_dubizzle_managed=managed,
        has_boilerplate=boilerplate,
    )
