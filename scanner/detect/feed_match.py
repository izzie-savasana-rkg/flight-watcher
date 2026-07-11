"""Match free-text deal items against watched origins/destinations."""

import re


def _terms_for(code: str, settings: dict) -> list[str]:
    keywords = settings.get("watch_keywords", {})
    return [t.lower() for t in keywords.get(code, [])] + [code.lower()]


def matches_watch(text: str, watch: dict, settings: dict) -> bool:
    """Both ends of the watched route must appear in the text."""
    haystack = text.lower()

    def found(code: str) -> bool:
        return any(re.search(rf"\b{re.escape(t)}\b", haystack)
                   for t in _terms_for(code, settings))

    return found(watch["origin"]) and found(watch["destination"])
