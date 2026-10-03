"""Demo sensor feed. Every TICK_SEC each parcel gets a reading according to its mode:
NORMAL - mild weather drifting around a baseline
FROST  - temperature falls to FROST_FLOOR (demo button)
REPLAY - a real frost night (data/frost_night.json, Open-Meteo ERA5) played back in 15-minute steps
Disable with SIMULATOR=0 when real sensors post to /sensors/parcels/{id}/readings.
"""
import asyncio
import json
import logging
import os
import random
from pathlib import Path

from . import db
from .sensors import record_reading, utc_now

log = logging.getLogger(__name__)

ENABLED = os.getenv("SIMULATOR", "1") != "0"
TICK_SEC = float(os.getenv("SENSOR_TICK_SEC", 3))

NORMAL = {"temperature": 14.0, "humidity": 60.0, "wind_speed": 3.0, "soil_temperature": 12.0}
FROST_START = 3.0         # demo jumps straight to a cold evening
FROST_FLOOR = -4.0
FROST_STEP = 0.4          # °C per tick
FROST_SIM_MINUTES = 5     # one tick represents 5 minutes of a night -> trend in °C/h
REPLAY_STEP_MINUTES = 15

_night = json.loads((Path(__file__).resolve().parent.parent / "data" / "frost_night.json").read_text(encoding="utf-8"))
REPLAY_SOURCE = _night["source"]
REPLAY_NIGHT = _night["night"]


def _interpolate(hourly, per_hour):
    keys = ("temperature", "humidity", "wind_speed", "soil_temperature")
    rows = [{"temperature": h["temperature"], "humidity": h["humidity"],
             "wind_speed": h["windSpeed"], "soil_temperature": h["soilTemperature"], "time": h["time"]} for h in hourly]
    steps = []
    for a, b in zip(rows, rows[1:]):
        for i in range(per_hour):
            f = i / per_hour
            steps.append({**{k: round(a[k] + (b[k] - a[k]) * f, 2) for k in keys}, "time": a["time"]})
    steps.append(rows[-1])
    for i, s in enumerate(steps):  # °C per hour of the original night
        prev = steps[max(0, i - per_hour)]
        s["trend"] = round((s["temperature"] - prev["temperature"]) * per_hour / max(1, min(i, per_hour)), 2) if i else None
    return steps


REPLAY = _interpolate(_night["hourly"], 60 // REPLAY_STEP_MINUTES)


def _jitter(value, amount):
    return round(value + random.uniform(-amount, amount), 2)


def normal_reading(last=None):
    base = {k: (last[k] if last and last.get(k) is not None else v) for k, v in NORMAL.items()}
    drift = {k: base[k] + (NORMAL[k] - base[k]) * 0.3 for k in NORMAL}
    return {"temperature": _jitter(drift["temperature"], 0.2), "humidity": _jitter(drift["humidity"], 1.5),
            "wind_speed": max(0, _jitter(drift["wind_speed"], 0.4)),
            "soil_temperature": _jitter(drift["soil_temperature"], 0.1), "trend": None, "source": "simulated"}


def frost_reading(last):
    t = min(last["temperature"] if last else FROST_START, FROST_START)
    t = max(FROST_FLOOR, t - FROST_STEP)
    falling = t > FROST_FLOOR
    return {"temperature": _jitter(t, 0.05), "humidity": min(95, (last or {}).get("humidity", 80) + 2),
            "wind_speed": 0.6, "soil_temperature": max(-1.0, (last or {}).get("soil_temperature", 2) - 0.2),
            "trend": -FROST_STEP * 60 / FROST_SIM_MINUTES if falling else 0.0, "source": "simulated"}


def replay_reading(step):
    s = REPLAY[step]
    return {k: s[k] for k in ("temperature", "humidity", "wind_speed", "soil_temperature", "trend")} | \
        {"source": f"replay:{s['time']}"}


def emit(conn, parcel):
    """Writes the next reading for the parcel according to its mode (and advances the replay)."""
    last = db.latest_reading(conn, parcel["id"])
    mode = parcel["mode"]
    if mode == "REPLAY":
        step = parcel["replay_step"] or 0
        if step < len(REPLAY):
            reading = replay_reading(step)
            db.set_mode(conn, parcel["id"], "REPLAY", step + 1)
        else:
            db.set_mode(conn, parcel["id"], "NORMAL")
            reading = normal_reading(last)
    elif mode == "FROST":
        reading = frost_reading(last)
    else:
        reading = normal_reading(last)
    reading["timestamp"] = utc_now().isoformat()
    return record_reading(conn, parcel["id"], reading, compute_trend=False)


def tick():
    with db.get_conn() as conn:
        for parcel in db.list_parcels(conn):
            emit(conn, parcel)


async def run():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            log.exception("simulator tick failed")
        await asyncio.sleep(TICK_SEC)
