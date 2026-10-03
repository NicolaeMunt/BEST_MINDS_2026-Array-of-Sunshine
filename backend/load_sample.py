"""Loads the sample history (data/sensor-history-sample.csv and data/alert-history-sample.csv, written
by make_sample.py) into the database, so the app has a season to show. Safe to run again: readings are
replaced, alerts already stored are kept.

    python load_sample.py
"""
import csv

from app import db
from make_sample import ALERTS_FILE, READINGS_FILE


def rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(line for line in f if not line.startswith("#"))


def stamp(text):
    """2026-05-01T00:00:00Z -> the fixed format of the database."""
    return text.replace("Z", ".000Z")


def main():
    db.init_db()
    readings = [(r["parcelId"], stamp(r["timestamp"]), float(r["temperatureC"]), float(r["humidityPct"]))
                for r in rows(READINGS_FILE)]
    alerts = [{"parcel_id": a["parcelId"], "timestamp": stamp(a["timestamp"]), "type": a["type"], "level": a["level"],
               "parcel_name": a["parcelName"], "crop": a["crop"], "temperature_c": float(a["temperatureC"]),
               "humidity_pct": float(a["humidityPct"]), "dew_point_c": float(a["dewPointC"]), "message": a["message"],
               "received_at": stamp(a["timestamp"])} for a in rows(ALERTS_FILE)]
    with db.get_conn() as conn:
        # Each reading is stored as if it had arrived when it was measured, so live readings stay the newest.
        for parcel_id, ts, temperature, humidity in readings:
            db.add_readings(conn, parcel_id, [(ts, temperature, humidity)], ts)
        db.add_alerts(conn, alerts)
    print(f"Loaded {len(readings)} readings and {len(alerts)} alerts into {db.DB_PATH}")


if __name__ == "__main__":
    main()
