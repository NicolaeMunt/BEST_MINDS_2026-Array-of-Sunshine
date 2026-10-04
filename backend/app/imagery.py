"""Satellite imagery for the API: the parcels the satellite job works on, the daily run of the job and its
results.

The job is imagery/fetch.py followed by imagery/analyze.py, run as a separate process with its own Python
(imagery/.venv, which has rasterio and GDAL): this module writes the parcels of the database to
imagery/parcels.geojson, starts the job, then stores imagery/out/imagery.json in the database. It runs once a
day in the evening, at start-up when the last good run is older than a day, and when asked to
(POST /imagery/refresh). The PNGs stay in imagery/out/overlays; the API serves them at /overlays/.
"""
import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import crops, db

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parent.parent.parent
IMAGERY_DIR = REPO_DIR / "imagery"
IMAGERY_PY = IMAGERY_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PARCELS_SEED = REPO_DIR / "backend" / "data" / "parcels.geojson"  # developers add parcels here
PARCELS_EXPORT = IMAGERY_DIR / "parcels.geojson"                  # what the job reads, written before each run
OUTPUT = IMAGERY_DIR / "out" / "imagery.json"
OVERLAYS_DIR = IMAGERY_DIR / "out" / "overlays"

DEMO_USER = (1, "Fermier demo")
LOCAL = timezone(timedelta(seconds=db.LOCAL_OFFSET_SEC))  # Europe/Chisinau in summer
# Sentinel-2 passes over Moldova around noon and the scene is in the catalogue a few hours later.
RUN_AT = time.fromisoformat(os.getenv("IMAGERY_RUN_AT", "21:00"))
AUTO = os.getenv("IMAGERY_AUTO", "1") != "0"  # 0: only POST /imagery/refresh starts a run
STALE_AFTER = timedelta(hours=24)
SEASON_START = os.getenv("IMAGERY_SEASON_START") or f"{date.today().year}-05-01"
JOB_TIMEOUT_SEC = 60 * 60


def _now():
    return db.ts_text(datetime.now(timezone.utc))


def _parse(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def today():
    return datetime.now(LOCAL).date()


# ---------- parcels ----------

def load_seed():
    """Users and parcels of backend/data/parcels.geojson into the database; a parcel stored before is updated."""
    created = _now()
    rows = []
    for f in json.loads(PARCELS_SEED.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        rows.append({"id": p["parcel_id"], "user_id": p.get("user_id", DEMO_USER[0]), "name": p["name"],
                     "crop": p.get("crop"), "crop_confirmed": int(bool(p.get("crop_confirmed"))),
                     "ids_fictive": int(bool(p.get("ids_fictive"))), "lpis_parcel": p.get("lpis_parcel"),
                     "geometry": json.dumps(f["geometry"]), "note": p.get("note"), "created_at": created})
    with db.get_conn() as conn:
        db.upsert_user(conn, *DEMO_USER, created)
        db.upsert_parcels(conn, rows)
    return len(rows)


def parcel_out(row):
    return {"parcel_id": row["id"], "user_id": row["user_id"], "name": row["name"], "crop": row["crop"],
            "crop_confirmed": bool(row["crop_confirmed"]), "ids_fictive": bool(row["ids_fictive"]),
            "lpis_parcel": row["lpis_parcel"], "geometry": json.loads(row["geometry"]) if row["geometry"] else None,
            "note": row["note"]}


def export_parcels():
    """The parcels that have a polygon, written as the GeoJSON the satellite job reads."""
    with db.get_conn() as conn:
        rows = [row for row in db.parcels(conn) if row["geometry"]]
    features = [{"type": "Feature", "geometry": json.loads(row["geometry"]),
                 "properties": {"parcel_id": row["id"], "name": row["name"], "crop": row["crop"],
                                "crop_confirmed": bool(row["crop_confirmed"])}} for row in rows]
    PARCELS_EXPORT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False,
                                         indent=1), encoding="utf-8")
    return len(features)


# ---------- the satellite job ----------

def run_job():
    """fetch.py (the only network step: scenes since the season start not on disk yet), then analyze.py."""
    if not IMAGERY_PY.exists():
        raise RuntimeError(f"{IMAGERY_PY} not found: create the satellite environment first (start.ps1 does it)")
    env = {**os.environ, "PARCELS_FILE": str(PARCELS_EXPORT), "PYTHONIOENCODING": "utf-8"}
    for args in (["fetch.py", "--parcels", str(PARCELS_EXPORT), "--from", SEASON_START], ["analyze.py"]):
        proc = subprocess.run([str(IMAGERY_PY), *args], cwd=IMAGERY_DIR, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=JOB_TIMEOUT_SEC)
        if proc.returncode != 0:
            raise RuntimeError(f"{args[0]} failed: {(proc.stderr or proc.stdout)[-1500:]}")
        lines = proc.stdout.strip().splitlines()
        log.info("%s: %s", args[0], lines[-1] if lines else "done")


def forget_parcel(parcel_id):
    """Drops a parcel's satellite results and its cached scenes: after a new outline, the cached windows may not
    cover the field any more, and the next run downloads and analyses it again."""
    with db.get_conn() as conn:
        for table in ("imagery_results", "imagery_warnings", "imagery_skipped"):
            conn.execute(f"DELETE FROM {table} WHERE parcel_id = ?", (parcel_id,))
    cache = IMAGERY_DIR / "cache" / parcel_id
    if cache.is_dir() and cache.parent == IMAGERY_DIR / "cache":
        shutil.rmtree(cache, ignore_errors=True)


def import_data(data):
    """Stores one output of the satellite job; returns how many (parcel, date) pairs are new."""
    with db.get_conn() as conn:
        return db.import_imagery(conn, data["results"], data["skipped"], data["rules_version"], _now())


def load_saved_output():
    """At start-up: a database without satellite results gets the last job output kept in the repository
    (imagery/out/imagery.json), so the map works offline before the first daily run."""
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM imagery_results LIMIT 1").fetchone():
            return 0
    if not OUTPUT.exists():
        return 0
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if unknown_parcels(data):
        return 0
    new = import_data(data)
    log.info("Loaded %d saved satellite scene dates from %s", new, OUTPUT)
    return new


def unknown_parcels(data):
    """Parcel IDs in a job output that the database does not know."""
    ids = {r["parcel_id"] for r in data["results"]} | {s["parcel_id"] for s in data["skipped"]}
    with db.get_conn() as conn:
        known = {row["id"] for row in db.parcels(conn)}
    return sorted(ids - known)


def next_daily_run(now):
    run = datetime.combine(now.date(), RUN_AT, tzinfo=now.tzinfo)
    return run if run > now else run + timedelta(days=1)


class Updater(threading.Thread):
    """Runs the satellite job once a day at RUN_AT, at start-up when the last good run is older than
    STALE_AFTER, and whenever trigger() is called; never two runs at once."""

    def __init__(self):
        super().__init__(daemon=True, name="imagery-updater")
        self._stopped = threading.Event()
        self._wake = threading.Event()
        self._busy = threading.Lock()
        self.next_run_at = None

    @property
    def running(self):
        return self._busy.locked()

    def stop(self):
        self._stopped.set()
        self._wake.set()

    def trigger(self):
        """Asks for a run now; False when one is already running."""
        if self.running:
            return False
        self._wake.set()
        return True

    def queue(self):
        """A run now, or right after the one running (a parcel was added or got a new outline meanwhile)."""
        self._wake.set()

    def run(self):
        if AUTO and self._stale():
            self.run_once()
        while not self._stopped.is_set():
            self.next_run_at = next_daily_run(datetime.now(LOCAL)) if AUTO else None
            timeout = (self.next_run_at - datetime.now(LOCAL)).total_seconds() if AUTO else None
            self._wake.wait(timeout)
            if self._stopped.is_set():
                break
            self._wake.clear()
            self.run_once()

    def _stale(self):
        with db.get_conn() as conn:
            last = db.last_run(conn, "ok")
        return not last or datetime.now(timezone.utc) - _parse(last["finished_at"]) > STALE_AFTER

    def run_once(self):
        if not self._busy.acquire(blocking=False):
            return
        started = _now()
        try:
            with db.get_conn() as conn:
                db.start_run(conn, started)
            export_parcels()
            run_job()
            new = import_data(json.loads(OUTPUT.read_text(encoding="utf-8")))
            with db.get_conn() as conn:
                db.finish_run(conn, started, _now(), "ok", new_scenes=new)
            log.info("Satellite run finished: %d new scene dates", new)
        except Exception as e:
            log.exception("Satellite run failed")
            with db.get_conn() as conn:
                db.finish_run(conn, started, _now(), "failed", error=str(e)[:2000])
        finally:
            self._busy.release()


def status(updater):
    with db.get_conn() as conn:
        last, last_ok = db.last_run(conn), db.last_run(conn, "ok")
    return {"running": updater.running, "last_run": dict(last) if last else None,
            "last_good_run": dict(last_ok) if last_ok else None, "next_run_at": updater.next_run_at}


# ---------- results for the frontend ----------

def result_out(row, warnings, crop=None):
    """One stored result for the API, with the crop's phase on the scene's day (from the crop calendar)."""
    out = {k: row[k] for k in ("scene_date", "scene_id", "ndvi_median", "ndmi_median", "affected_pct",
                               "affected_sector", "zone_count", "valid_pct", "prev_scene_date", "median_change",
                               "ndmi_change", "declined_pct", "overlay_path", "photo_path", "rules_version")}
    out["zone_center"] = [row["zone_lon"], row["zone_lat"]] if row["zone_lon"] is not None else None
    out["zone_confirmed"] = None if row["zone_confirmed"] is None else bool(row["zone_confirmed"])
    out["overlay_bounds"] = [row["bounds_south"], row["bounds_west"], row["bounds_north"], row["bounds_east"]]
    out["warnings"] = [{"code": code, "text": text} for code, text in warnings]
    phase = crops.phase_out(crop, date.fromisoformat(row["scene_date"])) if crop else None
    out["phase"], out["season"] = (phase["phase"], phase["season"]) if phase else (None, None)
    return out


def skipped_out(row):
    return {k: row[k] for k in ("scene_date", "scene_id", "valid_pct", "reason")}


def at_date(parcel_id, day):
    """The parcel's newest result taken on `day` or before it, how old it is on `day`, and the scenes skipped
    for clouds between that result and `day`."""
    with db.get_conn() as conn:
        row = db.imagery_at(conn, parcel_id, day.isoformat())
        skipped = db.imagery_skipped(conn, parcel_id, row["scene_date"] if row else "", day.isoformat())
        warnings = db.imagery_warnings(conn, parcel_id, [row["scene_date"]]) if row else {}
        crop = (db.parcel(conn, parcel_id) or {"crop": None})["crop"]
    return {"parcel_id": parcel_id, "day": day,
            "result": result_out(row, warnings.get(row["scene_date"], []), crop) if row else None,
            "days_old": (day - date.fromisoformat(row["scene_date"])).days if row else None,
            "skipped_since": [skipped_out(s) for s in skipped]}


def history(parcel_id, start, end):
    """Every result and every skipped scene of the parcel between two days, oldest first."""
    with db.get_conn() as conn:
        rows = db.imagery_results(conn, parcel_id, start.isoformat(), end.isoformat())
        warnings = db.imagery_warnings(conn, parcel_id, [row["scene_date"] for row in rows])
        skipped = db.imagery_skipped(conn, parcel_id, (start - timedelta(days=1)).isoformat(), end.isoformat())
        crop = (db.parcel(conn, parcel_id) or {"crop": None})["crop"]
    return {"parcel_id": parcel_id, "start": start, "end": end,
            "results": [result_out(row, warnings.get(row["scene_date"], []), crop) for row in rows],
            "skipped": [skipped_out(s) for s in skipped]}
