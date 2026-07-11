"""Secondary signal: public deal feeds (Secret Flying, Fly4Free)."""

import requests
import feedparser

from ..alerts import alert, alert_key
from ..config import load_json, save_json
from ..detect.feed_match import matches_watch

SEEN_FILE = "feeds_seen.json"
SEEN_LIMIT = 1000
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def scan(settings: dict, watches: list, dry_run: bool) -> dict:
    seen_store = load_json(SEEN_FILE, {"seen": []})
    seen = set(seen_store["seen"])
    cooldown = settings.get("alerts", {}).get("cooldown_hours", 24)
    stats = {"new_items": 0, "alerts": 0, "feed_errors": 0}

    for feed in settings.get("deal_feeds", []):
        try:
            resp = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=30)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as err:  # noqa: BLE001
            stats["feed_errors"] += 1
            print(f"  deal feed {feed['name']} failed: {err}")
            continue
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link", "")
            if not guid or guid in seen:
                continue
            seen.add(guid)
            stats["new_items"] += 1
            text = " ".join([entry.get("title", ""), entry.get("summary", "")])
            matched = [w for w in watches if matches_watch(text, w, settings)]
            if not matched:
                continue
            title = entry.get("title", "deal")
            link = entry.get("link", "")
            msg = f"[public] <b>{feed['name']}</b>: {title}\n{link}"
            key = alert_key("feed", guid)
            if alert("feed", key, msg, cooldown, dry_run,
                     meta={"feed": feed["name"],
                           "watches": [w["id"] for w in matched]}):
                stats["alerts"] += 1

    seen_store["seen"] = list(seen)[-SEEN_LIMIT:]
    save_json(SEEN_FILE, seen_store)
    return stats
