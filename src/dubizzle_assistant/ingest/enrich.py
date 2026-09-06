"""
One-time LLM pass over the listings: batched, cached by content, merged under regex authority.

Run by hand with scripts/build_inventory.py --llm and committed, so the server
never spends a grader's quota at startup. The model fills what regex cannot
read, such as colour phrased oddly or Arabic-only facts, and every value it
contributes is tagged source=llm. Where regex and the model disagree on a
figure, regex wins and the disagreement is written to the report.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dubizzle_assistant.config import get_settings
from dubizzle_assistant.services.llm import build_llm
from dubizzle_assistant.services.llm.base import LLMClient, LLMError, RateLimitedError
from dubizzle_assistant.text import contains_contact

LLM_FIELDS = (
    "price_aed",
    "monthly_aed",
    "mileage_km",
    "exterior_color",
    "interior_color",
    "body_type",
    "fuel_type",
    "transmission",
    "seats",
    "has_warranty",
)
FIGURES = ("price_aed", "monthly_aed", "mileage_km")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "listings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "price_aed": {
                        "type": "integer",
                        "description": "Cash total in AED stated in the text, or null",
                    },
                    "monthly_aed": {
                        "type": "integer",
                        "description": "Monthly instalment in AED stated in the text, or null",
                    },
                    "mileage_km": {
                        "type": "integer",
                        "description": "Odometer reading. Battery range, warranty caps and service intervals are not mileage.",
                    },
                    "exterior_color": {"type": "string"},
                    "interior_color": {"type": "string"},
                    "body_type": {
                        "type": "string",
                        "enum": [
                            "suv",
                            "sedan",
                            "coupe",
                            "hatchback",
                            "pickup",
                            "van",
                            "convertible",
                            "wagon",
                            "truck_chassis",
                        ],
                    },
                    "fuel_type": {
                        "type": "string",
                        "enum": ["petrol", "diesel", "electric", "hybrid"],
                    },
                    "transmission": {"type": "string", "enum": ["automatic", "manual"]},
                    "seats": {"type": "integer"},
                    "has_warranty": {"type": "boolean"},
                    "english_summary": {
                        "type": "string",
                        "description": "One or two neutral sentences about the car. No dealer names, no contact details, no marketing.",
                    },
                    "keywords_en": {
                        "type": "string",
                        "description": "Comma separated features and facts in English, including anything stated only in Arabic",
                    },
                },
                "required": ["id"],
            },
        }
    },
    "required": ["listings"],
}

PROMPT = (
    "You extract facts from used-car listings for a search index. For each listing return only what the text states. "
    "Use null for anything not stated. Prices are AED; a figure next to 'month', 'P.M' or 'instalment' is monthly_aed, not price_aed. "
    "Salary requirements, RTA fees, evaluation fees and condition-report fees are not prices. Battery range, warranty kilometre "
    "caps and service intervals are not mileage. Body type may come from your knowledge of the model. Translate Arabic facts "
    "into the English summary and keywords. Never include phone numbers, links, or dealer names."
)

Enricher = Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], list[dict[str, Any]], str]]


def _cache_key(rec: dict[str, Any]) -> str:
    return hashlib.sha256(
        (rec["id"] + "\n" + rec["description_clean"] + "\n" + rec["title"]).encode()
    ).hexdigest()


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _plausible(field: str, value: int) -> bool:
    if field == "price_aed":
        return 15_000 <= value <= 6_000_000
    if field == "monthly_aed":
        return 100 <= value <= 60_000
    return 0 <= value <= 600_000


def merge(rec: dict[str, Any], llm: dict[str, Any], disagreements: list[dict[str, Any]]) -> None:
    """Regex keeps figures it found. The model fills gaps and overrides only low-confidence words."""
    fields = rec["fields"]
    for f in LLM_FIELDS:
        v = llm.get(f)
        if v in (None, "", []):
            continue
        cur: dict[str, Any] = fields.get(f) or {
            "value": None,
            "source": "regex",
            "evidence": None,
            "confidence": 0.0,
        }
        confidence = float(cur.get("confidence") or 0.0)
        if f in FIGURES:
            n = _as_int(v)
            if n is None:
                continue
            if cur["value"] is not None:
                if _plausible(f, n) and n != int(cur["value"]):
                    disagreements.append(
                        {
                            "id": rec["id"],
                            "field": f,
                            "regex": cur["value"],
                            "llm": v,
                            "resolution": "regex kept (has evidence)",
                        }
                    )
                continue
            if _plausible(f, n):
                fields[f] = {"value": n, "source": "llm", "evidence": None, "confidence": 0.6}
            continue
        if isinstance(v, str):
            v = v.strip().lower()
        if cur["value"] in (None, False) or (confidence < 0.7 and v != cur["value"]):
            if cur["value"] not in (None, False) and v != cur["value"]:
                disagreements.append(
                    {
                        "id": rec["id"],
                        "field": f,
                        "regex": cur["value"],
                        "llm": v,
                        "resolution": "llm used (regex confidence low)",
                    }
                )
            fields[f] = {"value": v, "source": "llm", "evidence": None, "confidence": 0.6}
    summary = (llm.get("english_summary") or "").strip()
    if summary and not contains_contact(summary):
        rec["english_summary"] = summary
    kws = (llm.get("keywords_en") or "").strip()
    if kws:
        have = [k.strip() for k in rec["keywords_en"].split(",") if k.strip()]
        for k in kws.split(","):
            k = k.strip().lower()
            if k and k not in have and not contains_contact(k):
                have.append(k)
        rec["keywords_en"] = ", ".join(have)


def make_enricher(
    batch_size: int = 12, cache_path: Path | None = None, client: LLMClient | None = None
) -> Enricher:
    settings = get_settings()
    llm = client or build_llm(settings)
    if llm is None or (client is None and settings.llm_provider == "mock"):
        raise SystemExit(
            "LLM enrichment needs GEMINI_API_KEY and LLM_PROVIDER=litellm. The regex build works without it."
        )
    cache_file = cache_path or settings.data_dir / "enrichment_cache.json"
    cache: dict[str, Any] = (
        json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    )

    def _save_cache() -> None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8", newline="\n"
        )

    def enricher(
        records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        disagreements: list[dict[str, Any]] = []
        todo = [r for r in records if _cache_key(r) not in cache]
        batches = (len(todo) + batch_size - 1) // batch_size
        print(
            f"enriching {len(todo)} of {len(records)} listings in {batches} batches ({len(records) - len(todo)} cached)"
        )
        for i in range(0, len(todo), batch_size):
            batch = todo[i : i + batch_size]
            payload = [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "make": r["make"],
                    "model": r["model"],
                    "year": r["year"],
                    "text": r["description_clean"][:1500],
                }
                for r in batch
            ]
            for _attempt in range(3):
                try:
                    resp = llm.complete(
                        [
                            {"role": "system", "content": PROMPT},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        None,
                        reasoning="low",
                        response_schema=SCHEMA,
                        purpose="enrich",
                        temperature=0.1,
                    )
                    data = json.loads((resp.text or "{}").strip().strip("`").removeprefix("json"))
                    for item in data.get("listings", []):
                        rec = next(
                            (r for r in batch if r["id"] == str(item.get("id", "")).upper()), None
                        )
                        if rec is not None:
                            cache[_cache_key(rec)] = item
                    break
                except RateLimitedError as e:
                    wait = min(e.retry_after or 20, 60)
                    print(f"  rate limited, waiting {wait}s")
                    time.sleep(wait)
                except (LLMError, json.JSONDecodeError) as e:
                    print(f"  batch {i // batch_size + 1} failed: {e}")
                    break
            _save_cache()
            print(f"  batch {i // batch_size + 1}/{batches} done")
        for r in records:
            item = cache.get(_cache_key(r))
            if item:
                merge(r, item, disagreements)
        return records, disagreements, llm.model

    return enricher
