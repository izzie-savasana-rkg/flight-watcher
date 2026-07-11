"""Telegram alerting with dedupe/cooldown and a dashboard-visible log."""

import hashlib
import os
from datetime import datetime, timedelta, timezone

import requests

from .config import load_json, save_json

ALERTS_FILE = "alerts.json"
LOG_LIMIT = 200

KIND_EMOJI = {
    "anomaly": "\U0001F4C9",      # chart down
    "flyertalk": "\U0001F5E3",    # speaking head
    "fuel_dump": "⛽",        # fuel pump
    "feed": "\U0001F4F0",         # newspaper
    "health": "\U0001F6A8",       # rotating light
}


def _now():
    return datetime.now(timezone.utc)


def alert_key(kind: str, *parts) -> str:
    raw = kind + "|" + "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def send_telegram(text: str, dry_run: bool = False) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if dry_run or not token or not chat_id:
        print(f"[dry-run alert] {text}")
        return dry_run  # missing credentials on a real run counts as failure
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"telegram send failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def alert(kind: str, key: str, text: str, cooldown_hours: int = 24,
          dry_run: bool = False, meta: dict | None = None) -> bool:
    """Send an alert unless the same key fired within the cooldown."""
    data = load_json(ALERTS_FILE, {"sent": {}, "log": []})
    last = data["sent"].get(key)
    if last:
        try:
            if _now() - datetime.fromisoformat(last) < timedelta(hours=cooldown_hours):
                return False
        except ValueError:
            pass

    emoji = KIND_EMOJI.get(kind, "")
    sent = send_telegram(f"{emoji} {text}".strip(), dry_run=dry_run)
    data["sent"][key] = _now().isoformat(timespec="seconds")
    data["log"].append({
        "at": _now().isoformat(timespec="seconds"),
        "kind": kind,
        "text": text,
        "meta": meta or {},
    })
    data["log"] = data["log"][-LOG_LIMIT:]
    # prune sent-keys older than 30 days so the file doesn't grow forever
    cutoff = _now() - timedelta(days=30)
    data["sent"] = {
        k: v for k, v in data["sent"].items()
        if datetime.fromisoformat(v) >= cutoff
    }
    save_json(ALERTS_FILE, data)
    return sent
