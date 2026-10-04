"""Copies the readings and alerts of the sensors-alerts service into the database, so they build up a
history and survive that service's restarts (it keeps only the last ones in memory). Also keeps the users'
fields registered there: that service forgets them when it restarts."""
import logging
import os
import threading
from datetime import datetime, timezone

from . import accounts, db, sensors_client
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

    def sync_fields(self):
        """Registers every user field sensors-alerts does not know, or knows by an old name or crop.
        Returns the parcels the service has, without deleted fields (their sensors run on until it restarts)."""
        known = {p["id"]: p for p in sensors_client.parcels()}
        fields = accounts.all_fields()
        for f in fields:
            p = known.get(f["id"])
            if not p or p.get("name") != f["name"] or p.get("crop") != f["crop"]:
                known[f["id"]] = sensors_client.register(f["id"], f["name"], f["crop"]) or {"id": f["id"]}
        ids = {f["id"] for f in fields}
        return [p for p in known.values() if not accounts.is_field_id(p["id"]) or p["id"] in ids]

    def collect(self):
        parcels = self.sync_fields()
        wanted = {p["id"] for p in parcels}
        for parcel in parcels:
            parcel_id = parcel["id"]
            first = parcel_id not in self._last
            if first:
                with db.get_conn() as conn:
                    self._last[parcel_id] = db.newest_timestamp(conn, parcel_id)
            rows = [(db.ts_text(parse_ts(r["timestamp"])), r["temperatureC"], r["humidityPct"])
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
                  for a in sensors_client.alerts() if a["parcelId"] in wanted]
        if alerts:
            with db.get_conn() as conn:
                db.add_alerts(conn, alerts)
