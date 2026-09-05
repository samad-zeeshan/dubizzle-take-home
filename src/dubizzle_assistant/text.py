"""
Shared regexes for contact details and secrets, used at ingest and at reply time.

Kept in one place so the sanitizer, the output filter, and the trace redactor
agree on what counts as a phone number or a URL.
"""

from __future__ import annotations

import re

# UAE numbers appear in every shape the dealers could think of: +971 58 543 8686,
# 97144501601, 00971589695000, 0555540224, 052 996 5849, (+971) 0542211117.
# The token boundaries keep digit runs inside URL hashes from counting as phones.
PHONE_RE = re.compile(
    r"(?<![\w/.#-])(?:\(\+?\s?971\)|\+?\s?971|00971|0?5\d)[\s\-\.\)\(]*\d(?:[\s\-\.\)\(]*\d){6,10}(?![\w/-])"
)

URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>()\"']+"
    r"|(?<![\w@])[\w\-]+\.(?:com|ae|net|org|app|ly|gl|at|io)\b(?:/[^\s<>()\"']*)?",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# "Ref#410818" must survive, so the hash may not be glued to a word character.
HASHTAG_RE = re.compile(r"(?<!\w)#\w+")

HANDLE_RE = re.compile(r"(?<![\w/.])@\w{3,}")

# Google API keys all start with this prefix. Traces and logs must never carry one.
API_KEY_RE = re.compile(r"AIza[0-9A-Za-z\-_]{20,}")

ARABIC_RE = re.compile(r"[؀-ۿ]")


def find_phones(text: str) -> list[str]:
    return [re.sub(r"\D", "", m.group(0)) for m in PHONE_RE.finditer(text)]


def find_urls(text: str) -> list[str]:
    return [m.group(0) for m in URL_RE.finditer(text)]


def find_handles(text: str) -> list[str]:
    return [m.group(0) for m in HANDLE_RE.finditer(text)]


def strip_contacts(text: str) -> str:
    """Remove phones, URLs, emails, handles, and hashtags, leaving the rest intact."""
    out = URL_RE.sub(" ", text)
    out = EMAIL_RE.sub(" ", out)
    out = PHONE_RE.sub(" ", out)
    out = HANDLE_RE.sub(" ", out)
    out = HASHTAG_RE.sub(" ", out)
    return out


def contains_contact(text: str) -> bool:
    return bool(PHONE_RE.search(text) or URL_RE.search(text) or EMAIL_RE.search(text))
