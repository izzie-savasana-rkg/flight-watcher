"""Decide whether an observed fare is alert-worthy."""


def evaluate(price: float, med: float | None, n_obs: int, watch: dict,
             settings: dict) -> dict | None:
    """Return a finding dict when the fare triggers, else None."""
    cfg = settings.get("anomaly", {})
    threshold = watch.get("drop_threshold_pct", cfg.get("drop_threshold_pct", 30))
    min_obs = cfg.get("min_observations", 8)

    max_price = watch.get("max_price")
    if max_price and price <= float(max_price):
        return {"reason": "max_price", "price": price, "cap": max_price}

    if med and n_obs >= min_obs:
        drop_pct = (med - price) / med * 100
        if drop_pct >= threshold:
            return {
                "reason": "relative_drop",
                "price": price,
                "median": round(med, 2),
                "drop_pct": round(drop_pct, 1),
            }
    return None
