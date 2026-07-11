"""Per-route price history stored as JSON files under data/history/."""

from datetime import datetime, timedelta, timezone
from statistics import median

from .config import load_json, save_json

MAX_OBSERVATIONS = 4000


def history_file(watch_id: str, trip_type: str) -> str:
    return f"history/{watch_id}_{trip_type}.json"


def append_observation(watch_id: str, trip_type: str, obs: dict) -> None:
    name = history_file(watch_id, trip_type)
    data = load_json(name, {"observations": []})
    obs["observed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["observations"].append(obs)
    data["observations"] = data["observations"][-MAX_OBSERVATIONS:]
    save_json(name, data)


def rolling_median(watch_id: str, trip_type: str, window_days: int) -> tuple:
    """Return (median_price, n_observations) over the recent window."""
    data = load_json(history_file(watch_id, trip_type), {"observations": []})
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    prices = []
    for obs in data["observations"]:
        try:
            seen = datetime.fromisoformat(obs["observed_at"])
        except (KeyError, ValueError):
            continue
        if seen >= cutoff and obs.get("price"):
            prices.append(float(obs["price"]))
    if not prices:
        return None, 0
    return median(prices), len(prices)
