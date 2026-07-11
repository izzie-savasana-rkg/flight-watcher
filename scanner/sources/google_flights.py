"""Google Flights prices via fast-flights' protobuf URL, with:

- an EU/UK cookie-consent bypass (SOCS=CAI) that the stock fetcher lacks
- a tolerant parser that skips "price unavailable" rows instead of crashing
- retry with exponential backoff + jitter, and a per-run query budget
"""

import json
import random
import time

from fast_flights import FlightQuery, create_query
from fast_flights.exceptions import FlightsNotFound
from primp import Client
from selectolax.lexbor import LexborHTMLParser

FLIGHTS_URL = "https://www.google.com/travel/flights"
CONSENT_COOKIES = {"SOCS": "CAI", "CONSENT": "PENDING+987"}

_budget = {"remaining": 60, "min_delay": 2.0, "max_delay": 6.0, "used": 0}


class BudgetExhausted(Exception):
    pass


def configure_budget(max_queries: int, min_delay: float, max_delay: float) -> None:
    _budget.update(remaining=max_queries, min_delay=min_delay, max_delay=max_delay, used=0)


def queries_used() -> int:
    return _budget["used"]


def _new_client() -> Client:
    client = Client(
        impersonate="chrome_145",
        impersonate_os="macos",
        referer=True,
        cookie_store=True,
    )
    client.set_cookies("https://www.google.com", CONSENT_COOKIES)
    return client


def _tolerant_parse(html: str) -> list[dict]:
    """Extract priced itineraries; skip rows the upstream parser chokes on."""
    tree = LexborHTMLParser(html)
    script = tree.css_first(r"script.ds\:1")
    if script is None:
        title = tree.css_first("title")
        raise RuntimeError(
            f"unexpected page (title={title.text() if title else '?'}) — "
            "possibly consent wall or rate limiting"
        )
    js = script.text()
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found")
    payload = json.loads(data)

    out = []
    groups = payload[3] or []
    for group in groups[:2]:  # [0] best flights, [1] other flights
        if not isinstance(group, list) or not group:
            continue
        for entry in group:
            try:
                flight = entry[0]
                price = entry[1][0][1]
                if not price:
                    continue
                legs = flight[2] or []
                out.append({
                    "price": float(price),
                    "airlines": flight[1] or [],
                    "stops": max(len(legs) - 1, 0),
                    "first_departure": legs[0][20] if legs else None,
                })
            except (IndexError, TypeError, KeyError):
                continue
    return out


def _throttle() -> None:
    if _budget["remaining"] <= 0:
        raise BudgetExhausted("google flights query budget for this run is used up")
    _budget["remaining"] -= 1
    _budget["used"] += 1
    time.sleep(random.uniform(_budget["min_delay"], _budget["max_delay"]))


def _run_query(query, retries: int = 3) -> list[dict]:
    _throttle()
    last_err = None
    for attempt in range(retries):
        try:
            client = _new_client()
            res = client.get(FLIGHTS_URL, params=query.params())
            if res.status_code != 200:
                raise RuntimeError(f"http {res.status_code}")
            return _tolerant_parse(res.text)
        except FlightsNotFound:
            return []
        except Exception as err:  # noqa: BLE001 - retried, then surfaced
            last_err = err
            time.sleep((2 ** attempt) * 2 + random.uniform(0, 2))
    raise RuntimeError(f"google flights query failed after {retries} tries: {last_err}")


def _build_query(segments: list[dict], trip: str, seat: str, currency: str):
    return create_query(
        flights=[
            FlightQuery(
                date=s["date"],
                from_airport=s["from"],
                to_airport=s["to"],
                max_stops=s.get("max_stops"),
            )
            for s in segments
        ],
        trip=trip,
        seat=seat,
        currency=currency,
    )


def search(origin: str, destination: str, depart_date: str,
           return_date: str | None = None, seat: str = "economy",
           currency: str = "GBP") -> dict:
    """Price a one-way or return itinerary. Returns {cheapest, results, url}."""
    segments = [{"date": depart_date, "from": origin, "to": destination}]
    trip = "one-way"
    if return_date:
        segments.append({"date": return_date, "from": destination, "to": origin})
        trip = "round-trip"
    query = _build_query(segments, trip, seat, currency)
    results = _run_query(query)
    cheapest = min((r["price"] for r in results), default=None)
    return {"cheapest": cheapest, "results": results, "url": query.url()}


def search_multi(segments: list[dict], seat: str = "economy",
                 currency: str = "GBP") -> dict:
    """Price a multi-city itinerary (used by fuel-dump probes).

    segments: [{"date": "YYYY-MM-DD", "from": "XXX", "to": "YYY"}, ...]
    """
    query = _build_query(segments, "multi-city", seat, currency)
    results = _run_query(query)
    cheapest = min((r["price"] for r in results), default=None)
    return {"cheapest": cheapest, "results": results, "url": query.url()}
