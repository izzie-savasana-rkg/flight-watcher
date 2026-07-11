"""Entry point: python -m scanner [--dry-run] [--module all|prices|flyertalk|feeds|fueldump]"""

import argparse
import random
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

from . import history
from .alerts import alert, alert_key, send_telegram
from .config import load_json, load_settings, load_watches, save_json
from .detect import anomaly, fuel_dump
from .sources import google_flights

STATE_FILE = "state.json"
STATUS_FILE = "status.json"


def _load_dotenv() -> None:
    """Load a local .env (KEY=VALUE per line) without any dependency.

    Only used for local runs; on GitHub Actions the secrets are already in the
    environment, and already-set vars are never overwritten. No-op if absent.
    """
    import os
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _sample_depart_dates(window_days: int, count: int, step: int) -> list[date]:
    """Evenly spaced departure dates across the window, jittered per run so
    the whole window gets covered over successive runs."""
    today = date.today()
    first = today + timedelta(days=14)  # skip imminent departures
    span = max(window_days - 14, count * step)
    gap = span // count
    dates = []
    for i in range(count):
        jitter = random.randint(0, max(step - 1, 0))
        dates.append(first + timedelta(days=i * gap + jitter))
    return dates


def scan_prices(settings: dict, watches: list, dry_run: bool) -> dict:
    scan_cfg = settings.get("scan", {})
    currency = settings.get("currency", "GBP")
    cooldown = settings.get("alerts", {}).get("cooldown_hours", 24)

    combos = [(w, t) for w in watches for t in w.get("trip_types", ["return"])]
    if not combos:
        return {"observations": 0, "alerts": 0, "errors": 0}
    budget = scan_cfg.get("max_google_queries_per_run", 60)
    per_combo = max(2, min(8, budget // len(combos)))

    stats = {"observations": 0, "alerts": 0, "errors": 0}
    for watch, trip_type in combos:
        med, n_obs = history.rolling_median(
            watch["id"], trip_type,
            settings.get("anomaly", {}).get("median_window_days", 45))
        dates = _sample_depart_dates(
            watch.get("date_window_days", 180), per_combo,
            scan_cfg.get("depart_step_days", 7))
        best = None
        for depart in dates:
            ret = None
            if trip_type == "return":
                stay = random.choice(watch.get("stay_nights", [14]))
                ret = (depart + timedelta(days=stay)).isoformat()
            try:
                res = google_flights.search(
                    watch["origin"], watch["destination"], depart.isoformat(),
                    return_date=ret, seat=watch.get("cabin", "economy"),
                    currency=currency)
            except google_flights.BudgetExhausted:
                print("query budget exhausted, stopping price scan")
                return stats
            except Exception as err:  # noqa: BLE001
                stats["errors"] += 1
                print(f"  {watch['id']} {trip_type} {depart}: {err}")
                continue
            price = res["cheapest"]
            if price is None:
                continue
            history.append_observation(watch["id"], trip_type, {
                "depart": depart.isoformat(), "return": ret,
                "price": price, "currency": currency,
            })
            stats["observations"] += 1
            print(f"  {watch['id']} {trip_type} {depart} -> {price} {currency}")
            if best is None or price < best["price"]:
                best = {"price": price, "depart": depart.isoformat(),
                        "return": ret, "url": res["url"]}

        if best is None:
            continue
        finding = anomaly.evaluate(best["price"], med, n_obs, watch, settings)
        if finding:
            route = f"{watch['origin']}→{watch['destination']}"
            if finding["reason"] == "relative_drop":
                headline = (f"<b>{route}</b> {trip_type} £{best['price']:.0f} — "
                            f"{finding['drop_pct']}% below normal (median £{finding['median']:.0f})")
            else:
                headline = (f"<b>{route}</b> {trip_type} £{best['price']:.0f} — "
                            f"under your £{finding['cap']} cap")
            dates_txt = best["depart"] + (f" → {best['return']}" if best["return"] else "")
            text = f"{headline}\nDates: {dates_txt}\n{best['url']}"
            key = alert_key("anomaly", watch["id"], trip_type,
                            round(best["price"] / 25))
            if alert("anomaly", key, text, cooldown, dry_run,
                     meta={"watch": watch["id"], "trip": trip_type,
                           "price": best["price"]}):
                stats["alerts"] += 1
    return stats


def _heartbeat(status, failures, state, settings, dry_run) -> None:
    """Send an 'all clear' confirmation so a quiet day is never ambiguous.

    Throttled to once per min_interval_hours (default 20h ≈ once/day even on a
    6-hourly cron), so it doesn't spam every run. Bypasses the alert-dedupe
    cooldown entirely — it must fire on schedule regardless of deal alerts.
    """
    cfg = settings.get("heartbeat", {})
    if not cfg.get("enabled", True):
        return
    interval = cfg.get("min_interval_hours", 20)
    last = state.get("last_heartbeat")
    if last:
        try:
            if datetime.now(timezone.utc) - datetime.fromisoformat(last) < \
                    timedelta(hours=interval):
                return
        except ValueError:
            pass

    mods = status["modules"]
    lines = []
    p = mods.get("prices")
    if isinstance(p, dict) and not p.get("error"):
        lines.append(f"Prices: {p.get('observations', 0)} checked, "
                     f"{p.get('alerts', 0)} alert(s), {p.get('errors', 0)} error(s)")
    ft = mods.get("flyertalk")
    if isinstance(ft, dict) and not ft.get("error"):
        lines.append(f"FlyerTalk: {ft.get('new_threads', 0)} new, "
                     f"{ft.get('alerts', 0)} deal(s)")
    fe = mods.get("feeds")
    if isinstance(fe, dict) and not fe.get("error"):
        lines.append(f"Feeds: {fe.get('new_items', 0)} new, "
                     f"{fe.get('alerts', 0)} matched")
    fd = mods.get("fueldump")
    if isinstance(fd, dict) and not fd.get("error"):
        lines.append(f"Fuel-dump: {fd.get('probes', 0)} probed, "
                     f"{fd.get('alerts', 0)} hit(s)")

    zero_prices = (isinstance(p, dict) and p.get("observations", 0) == 0)
    healthy = not failures and not zero_prices
    header = ("✅ <b>Flight watcher ran OK</b>" if healthy
              else "⚠️ <b>Flight watcher ran with issues</b>")
    if failures:
        lines.append(f"Failed modules: {', '.join(failures)}")
    if zero_prices:
        lines.append("No successful price queries this run.")
    body = "\n".join(lines) or "Nothing to report."
    send_telegram(f"{header}\n{body}", dry_run=dry_run)
    state["last_heartbeat"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="scanner")
    parser.add_argument("--dry-run", action="store_true",
                        help="print alerts instead of sending to Telegram")
    parser.add_argument("--module", default="all",
                        choices=["all", "prices", "flyertalk", "feeds", "fueldump"])
    args = parser.parse_args(argv)

    _load_dotenv()
    settings = load_settings()
    watches = load_watches()
    scan_cfg = settings.get("scan", {})
    google_flights.configure_budget(
        scan_cfg.get("max_google_queries_per_run", 60),
        scan_cfg.get("min_delay_seconds", 2),
        scan_cfg.get("max_delay_seconds", 6))

    state = load_json(STATE_FILE, {"run_count": 0})
    state["run_count"] = state.get("run_count", 0) + 1

    status = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "modules": {}}
    failures = []

    def run_module(name, fn):
        try:
            status["modules"][name] = fn()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            failures.append(name)
            status["modules"][name] = {"error": True}

    if args.module in ("all", "prices"):
        run_module("prices", lambda: scan_prices(settings, watches, args.dry_run))

    if args.module in ("all", "flyertalk"):
        from .sources import flyertalk
        run_module("flyertalk",
                   lambda: flyertalk.scan(settings, watches, args.dry_run))

    if args.module in ("all", "feeds"):
        from .sources import deal_feeds
        run_module("feeds",
                   lambda: deal_feeds.scan(settings, watches, args.dry_run))

    fd_cfg = settings.get("fuel_dump", {})
    fd_due = state["run_count"] % max(fd_cfg.get("run_every_n_scans", 4), 1) == 0
    if args.module == "fueldump" or (args.module == "all" and
                                     fd_cfg.get("enabled") and fd_due):
        run_module("fueldump",
                   lambda: fuel_dump.scan(settings, watches, args.dry_run))

    prices_stats = status["modules"].get("prices", {})
    if (args.module in ("all", "prices") and watches
            and prices_stats.get("observations", 0) == 0):
        alert("health", alert_key("health", "no-prices"),
              "Scanner unhealthy: a full run produced zero successful Google "
              "Flights queries. fast-flights may be broken or blocked.",
              cooldown_hours=24, dry_run=args.dry_run)

    status["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status["google_queries_used"] = google_flights.queries_used()
    status["run_count"] = state["run_count"]

    # Confirmation heartbeat only on full scheduled runs, not single-module
    # manual dispatches (which would otherwise burn the daily slot on partial data).
    if args.module == "all":
        _heartbeat(status, failures, state, settings, args.dry_run)

    save_json(STATUS_FILE, status)
    save_json(STATE_FILE, state)
    print(f"done: {status['modules']} (queries used: {status['google_queries_used']})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
