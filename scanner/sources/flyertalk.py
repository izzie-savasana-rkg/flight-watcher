"""Watch FlyerTalk forum RSS feeds and decode new threads with Claude."""

import requests
import feedparser

from ..alerts import alert, alert_key
from ..config import load_json, save_json
from ..detect import thread_decode

THREADS_FILE = "flyertalk.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _fetch_feed(url: str):
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _thread_id(entry) -> str:
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def scan(settings: dict, watches: list, dry_run: bool) -> dict:
    cfg = settings.get("flyertalk", {})
    if not cfg.get("enabled", True):
        return {"skipped": True}
    store = load_json(THREADS_FILE, {"threads": {}})
    seen = store["threads"]
    cooldown = settings.get("alerts", {}).get("cooldown_hours", 24)
    max_decodes = cfg.get("max_decodes_per_run", 20)

    stats = {"new_threads": 0, "decoded": 0, "alerts": 0, "feed_errors": 0}
    fresh = []
    for feed in cfg.get("feeds", []):
        try:
            parsed = _fetch_feed(feed["url"])
        except Exception as err:  # noqa: BLE001
            stats["feed_errors"] += 1
            print(f"  flyertalk feed {feed['name']} failed: {err}")
            continue
        for entry in parsed.entries:
            tid = _thread_id(entry)
            if not tid or tid in seen:
                continue
            fresh.append((feed["name"], tid, entry))

    stats["new_threads"] = len(fresh)
    for forum, tid, entry in fresh[:max_decodes]:
        title = entry.get("title", "")
        summary = entry.get("summary", "")[:4000]
        link = entry.get("link", "")
        decoded = thread_decode.decode(title, summary, forum,
                                       model=cfg.get("model", "claude-haiku-4-5"))
        stats["decoded"] += 1
        record = {
            "forum": forum,
            "title": title,
            "link": link,
            "decoded": decoded,
            "starred": False,
        }
        if decoded.get("is_deal"):
            starred = thread_decode.matches_watches(decoded, title + " " + summary,
                                                    watches, settings)
            record["starred"] = starred
            prefix = "⭐ " if starred else ""
            text = (f"{prefix}<b>FlyerTalk · {decoded.get('deal_type', 'deal')}</b>"
                    f" · {', '.join(decoded.get('routes') or ['route unclear'])}\n"
                    f"{decoded.get('summary', title)}\n{link}")
            key = alert_key("flyertalk", tid)
            if alert("flyertalk", key, text, cooldown, dry_run,
                     meta={"thread": tid, "starred": starred,
                           "deal_type": decoded.get("deal_type")}):
                stats["alerts"] += 1
        seen[tid] = record
        save_json(THREADS_FILE, store)

    # keep the newest 500 threads
    if len(seen) > 500:
        for key in list(seen)[: len(seen) - 500]:
            del seen[key]
        save_json(THREADS_FILE, store)
    return stats
