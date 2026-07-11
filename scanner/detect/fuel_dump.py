"""Fuel-dump (3X) probing: price watched returns with vs. without each
candidate strike segment appended as a multi-city itinerary.

Strikes live in settings.json -> fuel_dump.strikes, e.g.
  {"from": "SIN", "to": "KUL", "days_after_return": 2, "note": "example"}
The tool checks candidates; discovering working strikes stays a human job
(FlyerTalk threads are the source — see the flyertalk module).
"""

from datetime import date, timedelta
import random

from ..alerts import alert, alert_key
from ..sources import google_flights


def scan(settings: dict, watches: list, dry_run: bool) -> dict:
    cfg = settings.get("fuel_dump", {})
    strikes = cfg.get("strikes", [])
    currency = settings.get("currency", "GBP")
    cooldown = settings.get("alerts", {}).get("cooldown_hours", 24)
    min_saving = cfg.get("min_saving", 50)
    stats = {"probes": 0, "alerts": 0, "errors": 0}
    if not strikes:
        return stats

    returns = [w for w in watches if "return" in w.get("trip_types", [])]
    for watch in returns:
        depart = date.today() + timedelta(days=random.randint(45, 90))
        stay = random.choice(watch.get("stay_nights", [14]))
        ret = depart + timedelta(days=stay)
        try:
            base = google_flights.search(
                watch["origin"], watch["destination"], depart.isoformat(),
                return_date=ret.isoformat(), seat=watch.get("cabin", "economy"),
                currency=currency)
        except google_flights.BudgetExhausted:
            return stats
        except Exception as err:  # noqa: BLE001
            stats["errors"] += 1
            print(f"  fueldump baseline {watch['id']} failed: {err}")
            continue
        baseline = base["cheapest"]
        if baseline is None:
            continue

        for strike in strikes:
            strike_date = ret + timedelta(days=strike.get("days_after_return", 2))
            segments = [
                {"date": depart.isoformat(), "from": watch["origin"],
                 "to": watch["destination"]},
                {"date": ret.isoformat(), "from": watch["destination"],
                 "to": watch["origin"]},
                {"date": strike_date.isoformat(), "from": strike["from"],
                 "to": strike["to"]},
            ]
            try:
                probe = google_flights.search_multi(
                    segments, seat=watch.get("cabin", "economy"),
                    currency=currency)
            except google_flights.BudgetExhausted:
                return stats
            except Exception as err:  # noqa: BLE001
                stats["errors"] += 1
                print(f"  fueldump probe {watch['id']}+{strike['from']}-"
                      f"{strike['to']} failed: {err}")
                continue
            stats["probes"] += 1
            dumped = probe["cheapest"]
            if dumped is None:
                continue
            saving = baseline - dumped
            print(f"  fueldump {watch['id']} + {strike['from']}-{strike['to']}: "
                  f"base {baseline:.0f} vs {dumped:.0f} ({saving:+.0f})")
            if saving >= min_saving:
                route = f"{watch['origin']}→{watch['destination']}"
                text = (f"<b>Possible fuel dump</b> on {route}: adding "
                        f"{strike['from']}→{strike['to']} drops the total to "
                        f"£{dumped:.0f} (vs £{baseline:.0f} baseline, saves "
                        f"£{saving:.0f}).\nDates: {depart} → {ret}, strike "
                        f"{strike_date}\nVerify before booking: {probe['url']}")
                key = alert_key("fuel_dump", watch["id"], strike["from"],
                                strike["to"], round(dumped / 25))
                if alert("fuel_dump", key, text, cooldown, dry_run,
                         meta={"watch": watch["id"], "strike": strike,
                               "saving": round(saving)}):
                    stats["alerts"] += 1
    return stats
