"""Copies the readings and alerts of the sensors-alerts service into the database, so they build up a
history and survive that service's restarts (it keeps only the last ones in memory)."""
import logging
import os
import threading
from datetime import datetime, timezone

from . import db, sensors_client
from .sensors import parse_ts
from .sensors_client import SensorsUnavailable

log = logging.getLogger(__name__)

POLL_SEC = float(os.getenv("COLLECT_INTERVAL_SEC", 5))
RECENT_MIN = 3          # asked for on every round; readings arrive every few seconds
BACKFILL_MIN = 24 * 60  # first round of a parcel: everything the service still has


class Collector(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="sensor-collector")
        self._stopped = threading.Event()
        self._last = {}  # parcel ID -> timestamp of the reading stored last

    def stop(self):
        self._stopped.set()

    def run(self):
        while not self._stopped.is_set():
            try:
                self.collect()
            except SensorsUnavailable:
                pass  # the service is down: try again on the next round
            except Exception:
                log.exception("Collecting sensor readings failed")
            self._stopped.wait(POLL_SEC)

    def collect(self):
        for parcel in sensors_client.parcels():
            parcel_id = parcel["id"]
            first = parcel_id not in self._last
            if first:
                with db.get_conn() as conn:
                    self._last[parcel_id] = db.newest_timestamp(conn, parcel_id)
            rows = [(db.ts_text(parse_ts(r["timestamp"])), r["temperatureC"], r["humidityPct"], r.get("precipitationMm"))
                    for r in sensors_client.readings(parcel_id, BACKFILL_MIN if first else RECENT_MIN)]
            # Only what came after the reading stored last; if that one is gone (mode switch, restart), everything.
            stamps = [row[0] for row in rows]
            if self._last[parcel_id] in stamps:
                rows = rows[stamps.index(self._last[parcel_id]) + 1:]
            if rows:
                with db.get_conn() as conn:
                    db.add_readings(conn, parcel_id, rows, db.ts_text(datetime.now(timezone.utc)))
                self._last[parcel_id] = rows[-1][0]

        # Alerts: the service returns the last ones it holds; those stored before are skipped by their key.
        now = db.ts_text(datetime.now(timezone.utc))
        alerts = [{"parcel_id": a["parcelId"], "timestamp": db.ts_text(parse_ts(a["timestamp"])),
                   "type": a.get("type") or "FROST", "level": a["level"], "parcel_name": a["parcelName"],
                   "crop": a.get("crop"), "temperature_c": a["temperatureC"], "humidity_pct": a["humidityPct"],
                   "dew_point_c": a["dewPointC"], "message": a["message"], "received_at": now}
                  for a in sensors_client.alerts()]
        if alerts:
            with db.get_conn() as conn:
                db.add_alerts(conn, alerts)
