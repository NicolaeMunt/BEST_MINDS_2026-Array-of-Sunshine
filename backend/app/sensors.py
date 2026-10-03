"""Adapter over the sensors-alerts service: keeps its contract fields and adds what the frontend
needs on top (dew point per reading, drop over the last hour, mode, priority and reasons).
The readings for the chart and the alerts come from the database (see collector.py)."""
import re
from datetime import datetime, timedelta, timezone

from . import db
from . import sensors_client as client
from .frost import assess_frost, dew_point, drop_last_hour

ALERT_PRIORITY = {"CRITICAL": "high", "WARNING": "medium", "OK": "low"}
# (alert type, level) -> title; alerts without a type come from an older service and are frost alerts.
ALERT_TITLE = {
    ("FROST", "CRITICAL"): "Îngheț",
    ("FROST", "WARNING"): "Risc de îngheț",
    ("FROST", "OK"): "Pericol trecut",
    ("HUMIDITY_HIGH", "WARNING"): "Umiditate ridicată",
    ("HUMIDITY_LOW", "WARNING"): "Umiditate scăzută",
    ("HUMIDITY_HIGH", "OK"): "Umiditate revenită la normal",
    ("HUMIDITY_LOW", "OK"): "Umiditate revenită la normal",
}
# Chart resolution: (window up to this many minutes, seconds per point); 0 = the readings themselves.
SUMMARY_STEPS = [(120, 0), (2 * 24 * 60, 300), (14 * 24 * 60, 3600)]
# Replay readings carry the timestamps of the recorded night.
REPLAY_AGE = timedelta(minutes=10)

# Fallback for a sensors-alerts build that does not report "mode": what was switched through this API.
_modes = {}


def parse_ts(value):
    """Java Instant (up to 9 fractional digits, 'Z') -> aware datetime."""
    value = re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00")
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def set_mode(parcel_id, mode):
    _modes[parcel_id] = mode


def reset_modes():
    _modes.clear()


def _mode(parcel_id, latest):
    if latest.get("mode"):
        return latest["mode"]
    if datetime.now(timezone.utc) - parse_ts(latest["timestamp"]) > REPLAY_AGE:
        return "REPLAY"
    mode = _modes.get(parcel_id, "NORMAL")
    return "NORMAL" if mode == "REPLAY" else mode  # the replay has finished


def latest(parcel_id):
    """Contract fields (incl. crop, humidityLevel) + mode, dropLastHourC and
    frost {priority, title, message, reasons}; None if no readings."""
    reading = client.latest(parcel_id)
    if not reading:
        return None
    drop = drop_last_hour(reading, client.readings(parcel_id, 60), parse_ts)
    return {**reading, "mode": _mode(parcel_id, reading), "drop_last_hour_c": drop,
            "frost": assess_frost(reading, drop)}


def readings(parcel_id, minutes, max_points=300):
    """Stored readings of the last N minutes with the dew point, at most ~max_points for the chart.
    Up to two hours: the readings themselves, thinned out evenly. Longer: one point per 5 minutes,
    hour or day with the average, and the lowest and highest temperature of that stretch."""
    bucket = next((sec for limit, sec in SUMMARY_STEPS if minutes <= limit), 86400)
    with db.get_conn() as conn:
        rows = db.readings_summary(conn, parcel_id, minutes, bucket) if bucket else db.readings(conn, parcel_id, minutes)
    if not bucket:
        step = -(-len(rows) // max_points) or 1
        rows = rows[::step] + (rows[-1:] if (len(rows) - 1) % step else [])  # the newest reading always stays
    return [{"parcelId": r["parcel_id"], "timestamp": r["timestamp"], "temperatureC": round(r["temperature_c"], 1),
             "humidityPct": round(r["humidity_pct"], 1), "dewPointC": dew_point(r["temperature_c"], r["humidity_pct"]),
             "minTemperatureC": r["min_temperature_c"] if bucket else None,
             "maxTemperatureC": r["max_temperature_c"] if bucket else None}
            for r in rows]


def parcels():
    """Sensor locations known to sensors-alerts, each with its latest reading (None before the first one)."""
    return [{**p, "latest": latest(p["id"])} for p in client.parcels()]


def alerts(parcel_id=None, type_="ALL"):
    """Stored alerts, newest first, with priority and title."""
    with db.get_conn() as conn:
        rows = db.alerts(conn, parcel_id, type_)
    return [{"parcelId": a["parcel_id"], "parcelName": a["parcel_name"], "crop": a["crop"], "type": a["type"],
             "level": a["level"], "temperatureC": a["temperature_c"], "humidityPct": a["humidity_pct"],
             "dewPointC": a["dew_point_c"], "timestamp": a["timestamp"], "message": a["message"],
             "priority": ALERT_PRIORITY.get(a["level"], "low"),
             "title": ALERT_TITLE.get((a["type"], a["level"]), a["level"])}
            for a in rows]
