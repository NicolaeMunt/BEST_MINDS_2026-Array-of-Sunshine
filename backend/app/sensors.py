"""Stores sensor readings, enriches them with dew point / frost level and raises alerts with cooldowns."""
import os
from datetime import datetime, timedelta, timezone

from . import db
from .frost import assess_frost, level_index

ALERT_COOLDOWN = timedelta(seconds=int(os.getenv("ALERT_COOLDOWN_SEC", 600)))
TREND_WINDOW = timedelta(minutes=30)


def utc_now():
    return datetime.now(timezone.utc)


def _trend_from_history(conn, parcel_id, reading):
    """°C/h over the last TREND_WINDOW of stored readings (used for real sensors)."""
    ts = datetime.fromisoformat(reading["timestamp"])
    history = db.readings_since(conn, parcel_id, (ts - TREND_WINDOW).isoformat(), reading["source"])
    if not history:
        return None
    first = history[0]
    hours = (ts - datetime.fromisoformat(first["timestamp"])).total_seconds() / 3600
    if hours < 5 / 60:
        return None
    return round((reading["temperature"] - first["temperature"]) / hours, 2)


def enrich(reading):
    """DB reading row -> API shape with dew point and frost level."""
    frost = assess_frost(reading)
    return {
        **reading,
        "dew_point": frost["dew_point"],
        "frost_level": frost["frost_level"],
        "predicted_temperature_1h": frost["predicted_temperature_1h"],
    }


def _maybe_alert(conn, parcel_id, frost, now):
    """One alert per level; repeats of the same/lower level are muted for ALERT_COOLDOWN, escalations always pass."""
    if frost["frost_level"] == "NONE":
        return None
    cooldown = db.get_cooldown(conn, parcel_id, "FROST")
    if cooldown:
        recent = now - datetime.fromisoformat(cooldown["last_at"]) < ALERT_COOLDOWN
        if recent and level_index(frost["frost_level"]) <= level_index(cooldown["last_level"]):
            return None
    return db.add_alert(conn, parcel_id, now.isoformat(), "FROST", frost["frost_level"], frost["priority"],
                        frost["title"], frost["message"], frost["reasons"])


def record_reading(conn, parcel_id, reading, compute_trend=True):
    """reading: timestamp (ISO, UTC), temperature, humidity, wind_speed, soil_temperature, trend, source."""
    reading = {**reading}
    if reading.get("trend") is None and compute_trend:
        reading["trend"] = _trend_from_history(conn, parcel_id, reading)
    db.add_reading(conn, parcel_id, reading)
    frost = assess_frost(reading)
    _maybe_alert(conn, parcel_id, frost, utc_now())
    return frost


def latest(conn, parcel):
    """Latest reading + dew point + frost level/priority/reasons, or None if the parcel has no readings."""
    reading = db.latest_reading(conn, parcel["id"])
    if not reading:
        return None
    frost = assess_frost(reading)
    return {**enrich(reading), "mode": parcel["mode"], "frost": frost}


def recent(conn, parcel_id, minutes):
    since = (utc_now() - timedelta(minutes=minutes)).isoformat()
    return [enrich(r) for r in db.readings_since(conn, parcel_id, since)]
