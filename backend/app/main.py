import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db, sensors, sensors_client
from .models import (AlertOut, DemoOut, FieldReport, ImageryOut, ParcelIn, ParcelOut, SensorLatestOut,
                     SensorReadingOut, VisionReport)
from .scoring import assess
from .sensors_client import SensorsUnavailable

# Comma-separated frontend origins; "*" allows any.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500",
).split(",")
REPO_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_DIR / "frontend"
# Overlay and photo PNGs written by imagery/analyze.py; imagery.json refers to them as /overlays/<file>.
OVERLAYS_DIR = Path(os.getenv("OVERLAYS_DIR", REPO_DIR / "imagery" / "out" / "overlays"))
DEMO_MESSAGES = {
    "frost": ("FROST", "Terenul a trecut în modul îngheț"),
    "humid": ("HUMID", "Terenul a trecut în modul aer umed și cald"),
    "dry": ("DRY", "Terenul a trecut în modul aer uscat și fierbinte"),
    "replay": ("REPLAY", "Redarea nopții de îngheț a pornit"),
    "normal": ("NORMAL", "Terenul a revenit la vremea normală"),
}


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="Crop Monitor API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in CORS_ORIGINS],
                   allow_methods=["*"], allow_headers=["*"])

# Frontend served from the same origin: http://localhost:8000/app/AgroMonitorWeb.html
if FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/app/AgroMonitorWeb.html")

if OVERLAYS_DIR.is_dir():
    app.mount("/overlays", StaticFiles(directory=OVERLAYS_DIR), name="overlays")


@app.exception_handler(SensorsUnavailable)
def sensors_unavailable(request: Request, exc: SensorsUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _build(conn, parcel, sensors_up=True):
    """sensors_up=False skips the call when the service already failed during this request."""
    latest, status = None, "unavailable"
    if sensors_up:
        try:
            latest = sensors.latest(parcel["id"])
            if latest is None:
                # Unknown to sensors-alerts (created here, or that service restarted): give it a sensor.
                sensors_client.register_parcel(parcel)
            status = "ok" if latest else "no_readings"
        except SensorsUnavailable:
            pass
    return assess(parcel,
                  db.latest_report(conn, "vision", parcel["id"]),
                  db.latest_report(conn, "field", parcel["id"]),
                  latest, status, imagery=db.latest_report(conn, "imagery", parcel["id"]))


def _require_parcel(conn, parcel_id):
    parcel = db.get_parcel(conn, parcel_id)
    if not parcel:
        raise HTTPException(404, f"Parcel {parcel_id} not found")
    return parcel


def _utc_iso(ts):
    ts = ts or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


# ---------- frontend ----------

@app.get("/parcels", response_model=list[ParcelOut])
def list_parcels():
    result = []
    with db.get_conn() as conn:
        for parcel in db.list_parcels(conn):
            sensors_up = not result or result[-1]["sensors_status"] != "unavailable"
            result.append(_build(conn, parcel, sensors_up))
    return result


@app.get("/parcels/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: str):
    with db.get_conn() as conn:
        return _build(conn, _require_parcel(conn, parcel_id))


@app.get("/sensors/parcels/{parcel_id}/latest", response_model=SensorLatestOut)
def latest_reading(parcel_id: str):
    """Latest reading + dew point + frost level (from sensors-alerts) + priority and reasons."""
    latest = sensors.latest(parcel_id)
    if not latest:
        raise HTTPException(404, f"No readings for parcel {parcel_id}")
    return latest


@app.get("/sensors/parcels/{parcel_id}/readings", response_model=list[SensorReadingOut])
def recent_readings(parcel_id: str, minutes: int = Query(60, ge=1, le=24 * 60)):
    """Readings of the last N minutes (counted back from the newest reading), oldest first."""
    return sensors.readings(parcel_id, minutes)


@app.get("/alerts", response_model=list[AlertOut])
def recent_alerts(parcel_id: str | None = Query(None, alias="parcelId"),
                  type_: str = Query("ALL", alias="type", pattern="^(FROST|HUMIDITY|ALL)$")):
    """Recent frost and humidity alerts from sensors-alerts, newest first. Level OK is the all-clear."""
    return sensors.alerts(parcel_id, type_)


# ---------- demo (forwarded to sensors-alerts) ----------

@app.post("/demo/{kind}/{parcel_id}", response_model=DemoOut)
def demo(kind: str, parcel_id: str):
    """kind: frost | humid | dry | replay | normal (normal sends the all-clear messages)."""
    if kind not in DEMO_MESSAGES:
        raise HTTPException(404, f"Unknown demo scenario {kind}")
    if sensors_client.demo(kind, parcel_id) is None:
        raise HTTPException(404, f"Parcel {parcel_id} unknown to the sensors service")
    mode, message = DEMO_MESSAGES[kind]
    sensors.set_mode(parcel_id, mode)
    return {"parcel_id": parcel_id, "mode": mode, "message": message}


@app.post("/demo/reset", response_model=DemoOut)
def demo_reset():
    sensors_client.demo_reset()
    sensors.reset_modes()
    return {"mode": "NORMAL", "message": "Toate terenurile sunt în modul NORMAL, alertele au fost șterse"}


# ---------- integration (setup + other modules) ----------

@app.post("/parcels", response_model=ParcelOut, status_code=201)
def create_parcel(body: ParcelIn):
    with db.get_conn() as conn:
        if body.id and db.get_parcel(conn, body.id):
            raise HTTPException(409, f"Parcel {body.id} already exists")
        data = body.model_dump()
        data["planted_at"] = data["planted_at"].isoformat() if data["planted_at"] else None
        parcel = db.create_parcel(conn, **data)
        try:
            sensors_client.register_parcel(parcel)
        except SensorsUnavailable:
            pass  # _build registers it again once the service is back
        return _build(conn, parcel)


@app.post("/parcels/{parcel_id}/vision", status_code=201)
def add_vision_report(parcel_id: str, body: VisionReport):
    """Drone analysis posts results here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        data = body.model_dump(mode="json", exclude={"captured_at"})
        db.add_report(conn, "vision", parcel_id, _utc_iso(body.captured_at), data)
    return {"ok": True}


@app.post("/parcels/{parcel_id}/imagery", status_code=201)
def add_imagery_report(parcel_id: str, body: ImageryOut):
    """The satellite pipeline (imagery/push.py) posts one analysed scene here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        data = body.model_dump(mode="json")
        db.add_report(conn, "imagery", parcel_id, _utc_iso(datetime.combine(body.scene_date, datetime.min.time())), data)
    return {"ok": True}


@app.post("/parcels/{parcel_id}/field", status_code=201)
def add_field_report(parcel_id: str, body: FieldReport):
    """Soil / weather module posts results here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        data = body.model_dump(mode="json", exclude={"measured_at"})
        db.add_report(conn, "field", parcel_id, _utc_iso(body.measured_at), data)
    return {"ok": True}
