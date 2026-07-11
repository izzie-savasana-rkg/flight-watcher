import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ["FW_DATA_DIR"] = tempfile.mkdtemp()

from scanner.detect.anomaly import evaluate  # noqa: E402
from scanner.detect.feed_match import matches_watch  # noqa: E402
from scanner.detect.thread_decode import _keyword_fallback, matches_watches  # noqa: E402
from scanner.alerts import alert, alert_key  # noqa: E402
from scanner.config import load_json  # noqa: E402

SETTINGS = {
    "anomaly": {"drop_threshold_pct": 30, "min_observations": 8},
    "watch_keywords": {
        "LON": ["london", "lhr", "lgw"],
        "KUL": ["kuala lumpur", "malaysia", "kul"],
    },
}
WATCH = {"id": "lon-kul", "origin": "LON", "destination": "KUL",
         "max_price": None}


def test_anomaly_relative_drop_triggers():
    finding = evaluate(300, med=500, n_obs=20, watch=WATCH, settings=SETTINGS)
    assert finding and finding["reason"] == "relative_drop"
    assert finding["drop_pct"] == 40.0


def test_anomaly_needs_enough_history():
    assert evaluate(300, med=500, n_obs=3, watch=WATCH, settings=SETTINGS) is None


def test_anomaly_small_drop_ignored():
    assert evaluate(450, med=500, n_obs=20, watch=WATCH, settings=SETTINGS) is None


def test_anomaly_max_price_cap():
    watch = dict(WATCH, max_price=350)
    finding = evaluate(340, med=None, n_obs=0, watch=watch, settings=SETTINGS)
    assert finding and finding["reason"] == "max_price"


def test_feed_match_needs_both_ends():
    assert matches_watch("Cheap flights London to Kuala Lumpur", WATCH, SETTINGS)
    assert not matches_watch("Cheap flights London to Bangkok", WATCH, SETTINGS)
    assert not matches_watch("Kuala Lumpur hotel sale", WATCH, SETTINGS)


def test_feed_match_word_boundaries():
    # 'kul' must not match inside 'skulduggery'
    assert not matches_watch("london skulduggery special", WATCH, SETTINGS)


def test_keyword_fallback_flags_fare_language():
    assert _keyword_fallback("MNL-LHR rtn £1650 Business", "")["is_deal"]
    assert not _keyword_fallback("Trip report: my seat was broken", "")["is_deal"]


def test_thread_match_uses_iata_and_keywords():
    decoded = {"routes": ["LHR-SIN"], "regions": [], "summary": ""}
    assert matches_watches(decoded, "", [WATCH], SETTINGS)
    decoded = {"routes": [], "regions": [], "summary": "great fares to malaysia"}
    assert matches_watches(decoded, "", [WATCH], SETTINGS)
    decoded = {"routes": ["JFK-NRT"], "regions": ["US"], "summary": "US deal"}
    assert not matches_watches(decoded, "", [WATCH], SETTINGS)


def test_alert_dedupe_cooldown():
    key = alert_key("anomaly", "lon-kul", "return", 12)
    assert alert("anomaly", key, "first", cooldown_hours=24, dry_run=True)
    assert not alert("anomaly", key, "repeat", cooldown_hours=24, dry_run=True)
    data = load_json("alerts.json")
    assert len([e for e in data["log"] if e["text"] == "first"]) == 1
