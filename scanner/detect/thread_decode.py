"""Decode cryptic FlyerTalk threads into structured deal data using Claude.

Uses claude-haiku-4-5 with a structured-output schema so the response is
guaranteed-valid JSON. Falls back to keyword matching when ANTHROPIC_API_KEY
is not set or the API call fails (the thread is still recorded).
"""

import json
import os
import re

SCHEMA = {
    "type": "object",
    "properties": {
        "is_deal": {
            "type": "boolean",
            "description": "True if the thread announces a bookable fare deal, "
                           "error fare, fuel dump method, or mileage run fare. "
                           "False for questions, trip reports, or chit-chat.",
        },
        "deal_type": {
            "type": "string",
            "enum": ["error_fare", "fuel_dump", "mileage_run", "sale",
                     "premium_deal", "other", "not_a_deal"],
        },
        "routes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Routes as ORIGIN-DEST IATA/metro pairs, e.g. "
                           "LON-SIN. Use region names if airports unclear.",
        },
        "regions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "World regions involved, e.g. Europe, SEA, US.",
        },
        "cabin": {"type": ["string", "null"]},
        "approx_price": {"type": ["string", "null"]},
        "urgency": {"type": "string", "enum": ["book_now", "days", "ongoing", "unknown"]},
        "summary": {
            "type": "string",
            "description": "One-sentence plain-English decode of the thread, "
                           "expanding forum shorthand.",
        },
    },
    "required": ["is_deal", "deal_type", "routes", "regions", "cabin",
                 "approx_price", "urgency", "summary"],
    "additionalProperties": False,
}

SYSTEM = (
    "You decode FlyerTalk forum threads about airfare deals. These use heavy "
    "community shorthand: 'ex-XXX' means departing from airport/city XXX, "
    "J=business, F=first, Y=economy, W/PE=premium economy, '3X'/strike = an "
    "extra fuel-dump segment, MR = mileage run, CPM = cents per mile, "
    "OTA = online travel agency, ITA = ITA Matrix. Classify whether the "
    "thread is an actionable deal and extract the essentials. Be literal — "
    "do not invent routes or prices that are not implied by the text."
)

DEAL_WORDS = re.compile(
    r"(error fare|mistake|fuel dump|3x|ex-[a-z]{3}|glitch|\$\d|£\d|€\d|"
    r"\bfare\b|\bdeal\b|premium|business class|first class)", re.I)


def _keyword_fallback(title: str, summary: str) -> dict:
    text = f"{title} {summary}"
    hit = bool(DEAL_WORDS.search(text))
    return {
        "is_deal": hit,
        "deal_type": "other" if hit else "not_a_deal",
        "routes": [],
        "regions": [],
        "cabin": None,
        "approx_price": None,
        "urgency": "unknown",
        "summary": title,
        "decoder": "keywords",
    }


def decode(title: str, summary: str, forum: str,
           model: str = "claude-haiku-4-5") -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _keyword_fallback(title, summary)
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=600,
            system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": (f"Forum: {forum}\nThread title: {title}\n\n"
                            f"First post:\n{summary[:3000]}"),
            }],
        )
        text = next(b.text for b in response.content if b.type == "text")
        decoded = json.loads(text)
        decoded["decoder"] = "claude"
        return decoded
    except Exception as err:  # noqa: BLE001
        print(f"  decode failed ({err}); falling back to keywords")
        return _keyword_fallback(title, summary)


def matches_watches(decoded: dict, raw_text: str, watches: list,
                    settings: dict) -> bool:
    """True when the decoded thread touches any watched origin/destination."""
    keywords = settings.get("watch_keywords", {})
    haystack = " ".join([
        raw_text,
        " ".join(decoded.get("routes") or []),
        " ".join(decoded.get("regions") or []),
        decoded.get("summary") or "",
    ]).lower()
    for watch in watches:
        for code in (watch["origin"], watch["destination"]):
            terms = keywords.get(code, []) + [code.lower()]
            if any(re.search(rf"\b{re.escape(t)}\b", haystack) for t in terms):
                return True
    return False
