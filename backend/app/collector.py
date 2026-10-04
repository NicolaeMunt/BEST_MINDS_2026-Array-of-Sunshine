"""Copies the readings and alerts of the sensors-alerts service into the database, so they build up a
history and survive that service's restarts (it keeps only the last ones in memory). Also keeps the users'
parcels registered there: that service forgets them when it restarts. Sends the watering and sowing advice."""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from . import accounts, crops, db, sensors_client, sowing, water
from .frost import dew_point
from .sensors import parse_ts
from .sensors_client import SensorsUnavailable

log = logging.getLogger(__name__)

POLL_SEC = float(os.getenv("COLLECT_INTERVAL_SEC", 5))
RECENT_MIN = 3          # asked for on every round; readings arrive every few seconds
BACKFILL_MIN = 24 * 60  # first round of a parcel: everything the service still has
# Watering and sowing advice change slowly: once an hour is enough (and at start-up, and right after the soil
# moisture jumps).
ADVICE_CHECK_SEC = float(os.getenv("ADVICE_CHECK_SEC", 3600))


class Collector(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="sensor-collector")
        self._stopped = threading.Event()
        self._last = {}  # parcel ID -> timestamp of the reading stored last
        self._advice_checked = 0.0
        self._moisture_now = {}      # parcel ID -> soil moisture of the reading stored last
        self._moisture_checked = {}  # parcel ID -> soil moisture at the last advice check

    def stop(self):
        self._stopped.set()

    def run(self):
        while not self._stopped.is_set():
            try:
                self.collect()
                if time.monotonic() - self._advice_checked >= ADVICE_CHECK_SEC:
                    self._advice_checked = time.monotonic()
                    self.send_advice()
            except SensorsUnavailable:
                pass  # the service is down: try again on the next round
            except Exception:
                log.exception("Collecting sensor readings failed")
            self._stopped.wait(POLL_SEC)

    def sync_parcels(self):
        """Registers every user parcel sensors-alerts does not know, or knows by an old name or crop. Returns the
        parcels the service has that are in the database: a deleted parcel's sensor runs on until the service
        restarts, and is left out."""
        known = {p["id"]: p for p in sensors_client.parcels()}
        for f in accounts.account_parcels():
            p = known.get(f["id"])
            if not p or p.get("name") != f["name"] or p.get("crop") != f["crop"]:
                known[f["id"]] = sensors_client.register(f["id"], f["name"], f["crop"]) or {"id": f["id"]}
        with db.get_conn() as conn:
            stored = {row["id"] for row in db.parcels(conn)}
        return [p for p in known.values() if p["id"] in stored]

    def collect(self):
        parcels = self.sync_parcels()
        wanted = {p["id"] for p in parcels}
        for parcel in parcels:
            parcel_id = parcel["id"]
            first = parcel_id not in self._last
            if first:
                with db.get_conn() as conn:
                    self._last[parcel_id] = db.newest_timestamp(conn, parcel_id)
            rows = [(db.ts_text(parse_ts(r["timestamp"])), r["temperatureC"], r["humidityPct"], r.get("precipitationMm"),
                     r.get("soilTemperatureC"), r.get("soilMoisturePct"))
                    for r in sensors_client.readings(parcel_id, BACKFILL_MIN if first else RECENT_MIN)]
            # Only what came after the reading stored last; if that one is gone (mode switch, restart), everything.
            stamps = [row[0] for row in rows]
            if self._last[parcel_id] in stamps:
                rows = rows[stamps.index(self._last[parcel_id]) + 1:]
            if rows:
                with db.get_conn() as conn:
                    db.add_readings(conn, parcel_id, rows, db.ts_text(datetime.now(timezone.utc)))
                self._last[parcel_id] = rows[-1][0]
                # A change in soil moisture since the last advice check (a watering, the end of a replay) is
                # checked right away instead of within the hour.
                moisture = [r[5] for r in rows if r[5] is not None]
                if moisture:
                    self._moisture_now[parcel_id] = moisture[-1]
                    checked = self._moisture_checked.setdefault(parcel_id, moisture[-1])
                    if abs(moisture[-1] - checked) >= crops.watering_rise_pct():
                        self._advice_checked = 0.0

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

    def send_advice(self):
        """Watering and sowing advice of today and yesterday that was not sent yet goes to sensors-alerts, which
        sends it to Telegram; it hands it back with its alerts, so it ends up stored and is not sent twice. Older
        advice (the season history) is only shown in the app."""
        today = datetime.now(crops.LOCAL).date()
        self._moisture_checked.update(self._moisture_now)
        with db.get_conn() as conn:
            fresh = []
            for p in db.parcels(conn):
                parcel = {"id": p["id"], "name": p["name"], "crop": p["crop"]}
                for a in water.alerts(conn, parcel, today, dew_point) + sowing.alerts(conn, parcel, today):
                    day = datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00")).astimezone(crops.LOCAL).date()
                    if day >= today - timedelta(days=1) and not db.alert_stored(conn, a["parcelId"], a["timestamp"],
                                                                                 a["type"], a["level"]):
                        fresh.append(a)
        for a in fresh:
            sensors_client.send_advice(a["parcelId"], {k: a[k] for k in (
                "type", "timestamp", "level", "temperatureC", "humidityPct", "dewPointC", "message")})
            log.info("%s advice sent for %s (%s)", a["type"], a["parcelId"], a["level"])
