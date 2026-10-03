import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db, sensors, simulator
from .models import (AlertOut, DemoOut, FieldReport, ParcelIn, ParcelOut, SensorLatestOut, SensorReadingIn,
                     SensorReadingOut, VisionReport)
from .scoring import assess

# Comma-separated frontend origins; "*" allows any.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500",
).split(",")
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    task = asyncio.create_task(simulator.run()) if simulator.ENABLED else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Crop Monitor API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in CORS_ORIGINS],
                   allow_methods=["*"], allow_headers=["*"])

# Frontend served from the same origin: http://localhost:8000/app/AgroMonitorWeb.html
if FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/app/AgroMonitorWeb.html")


def _build(conn, parcel):
    return assess(parcel,
                  db.latest_report(conn, "vision", parcel["id"]),
                  db.latest_report(conn, "field", parcel["id"]),
                  sensors.latest(conn, parcel))


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
    with db.get_conn() as conn:
        return [_build(conn, p) for p in db.list_parcels(conn)]


@app.get("/parcels/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: int):
    with db.get_conn() as conn:
        return _build(conn, _require_parcel(conn, parcel_id))


@app.get("/sensors/parcels/{parcel_id}/latest", response_model=SensorLatestOut)
def latest_reading(parcel_id: int):
    """Latest reading + dew point + frost level (with priority and reasons)."""
    with db.get_conn() as conn:
        latest = sensors.latest(conn, _require_parcel(conn, parcel_id))
    if not latest:
        raise HTTPException(404, f"No readings for parcel {parcel_id}")
    return latest


@app.get("/sensors/parcels/{parcel_id}/readings", response_model=list[SensorReadingOut])
def recent_readings(parcel_id: int, minutes: int = Query(60, ge=1, le=24 * 60)):
    """Readings of the last N minutes, oldest first (for the chart)."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        return sensors.recent(conn, parcel_id, minutes)


@app.get("/alerts", response_model=list[AlertOut])
def recent_alerts(parcel_id: int | None = Query(None, alias="parcelId"), limit: int = Query(50, ge=1, le=500)):
    """Recent alerts, newest first."""
    with db.get_conn() as conn:
        return db.list_alerts(conn, parcel_id, limit)


# ---------- demo ----------

@app.post("/demo/frost/{parcel_id}", response_model=DemoOut)
def demo_frost(parcel_id: int):
    """Switch the parcel to FROST: temperature drops to -4°C over ~1 minute."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        db.set_mode(conn, parcel_id, "FROST")
        simulator.emit(conn, db.get_parcel(conn, parcel_id))
    return {"parcel_id": parcel_id, "mode": "FROST", "message": "Terenul a trecut în modul îngheț"}


@app.post("/demo/replay/{parcel_id}", response_model=DemoOut)
def demo_replay(parcel_id: int):
    """Play back a real frost night (15 min of the night per tick)."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        db.set_mode(conn, parcel_id, "REPLAY", 0)
        simulator.emit(conn, db.get_parcel(conn, parcel_id))
    return {"parcel_id": parcel_id, "mode": "REPLAY",
            "message": f"Redarea nopții {simulator.REPLAY_NIGHT}: {len(simulator.REPLAY)} pași. "
                       f"Sursa: {simulator.REPLAY_SOURCE}"}


@app.post("/demo/reset", response_model=DemoOut)
def demo_reset():
    """All parcels back to NORMAL, alerts and cooldowns cleared."""
    with db.get_conn() as conn:
        db.reset_demo(conn)
        for parcel in db.list_parcels(conn):
            reading = simulator.normal_reading()  # snap back to baseline instead of slowly warming up
            reading["timestamp"] = sensors.utc_now().isoformat()
            sensors.record_reading(conn, parcel["id"], reading, compute_trend=False)
    return {"mode": "NORMAL", "message": "Toate terenurile sunt în modul NORMAL, alertele au fost șterse"}


# ---------- integration (setup + other modules) ----------

@app.post("/parcels", response_model=ParcelOut, status_code=201)
def create_parcel(body: ParcelIn):
    with db.get_conn() as conn:
        data = body.model_dump()
        data["planted_at"] = data["planted_at"].isoformat() if data["planted_at"] else None
        return _build(conn, db.create_parcel(conn, **data))


@app.post("/sensors/parcels/{parcel_id}/readings", response_model=SensorReadingOut, status_code=201)
def add_reading(parcel_id: int, body: SensorReadingIn):
    """Real sensors (or another module's simulator) post readings here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        reading = {**body.model_dump(exclude={"timestamp"}), "timestamp": _utc_iso(body.timestamp),
                   "trend": None, "source": "sensor"}
        sensors.record_reading(conn, parcel_id, reading)
        return sensors.enrich(db.latest_reading(conn, parcel_id))


@app.post("/parcels/{parcel_id}/vision", status_code=201)
def add_vision_report(parcel_id: int, body: VisionReport):
    """Coder 1 (drone analysis) posts results here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        data = body.model_dump(mode="json", exclude={"captured_at"})
        db.add_report(conn, "vision", parcel_id, _utc_iso(body.captured_at), data)
    return {"ok": True}


@app.post("/parcels/{parcel_id}/field", status_code=201)
def add_field_report(parcel_id: int, body: FieldReport):
    """Coder 2 (soil / weather) posts results here."""
    with db.get_conn() as conn:
        _require_parcel(conn, parcel_id)
        data = body.model_dump(mode="json", exclude={"measured_at"})
        db.add_report(conn, "field", parcel_id, _utc_iso(body.measured_at), data)
    return {"ok": True}
