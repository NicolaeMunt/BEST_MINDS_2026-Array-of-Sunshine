import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db, sensors, sensors_client
from .collector import Collector
from .models import AlertOut, DemoOut, SensorLatestOut, SensorParcelOut, SensorReadingOut
from .sensors_client import SensorsUnavailable

# Comma-separated frontend origins; "*" allows any.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500",
).split(",")
REPO_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_DIR / "frontend"
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
    collector = Collector()
    collector.start()
    yield
    collector.stop()


app = FastAPI(title="Agronomicon API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in CORS_ORIGINS],
                   allow_methods=["*"], allow_headers=["*"])

# Frontend served from the same origin: http://localhost:8000/app/
if FRONTEND_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/app/")


@app.exception_handler(SensorsUnavailable)
def sensors_unavailable(request: Request, exc: SensorsUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------- frontend ----------

@app.get("/sensors/parcels", response_model=list[SensorParcelOut])
def sensor_parcels():
    """Sensor locations (from sensors-alerts), each with its latest reading."""
    return sensors.parcels()


@app.get("/sensors/parcels/{parcel_id}/latest", response_model=SensorLatestOut)
def latest_reading(parcel_id: str):
    """Latest reading + dew point + frost level (from sensors-alerts) + priority and reasons."""
    latest = sensors.latest(parcel_id)
    if not latest:
        raise HTTPException(404, f"No readings for parcel {parcel_id}")
    return latest


@app.get("/sensors/parcels/{parcel_id}/readings", response_model=list[SensorReadingOut])
def stored_readings(parcel_id: str, minutes: int = Query(60, ge=1, le=366 * 24 * 60)):
    """Stored readings of the last N minutes (counted back from the newest reading), oldest first.
    Windows over two hours come summarised: one point per 5 minutes, hour or day, with min and max."""
    return sensors.readings(parcel_id, minutes)


@app.get("/alerts", response_model=list[AlertOut])
def recent_alerts(parcel_id: str | None = Query(None, alias="parcelId"),
                  type_: str = Query("ALL", alias="type", pattern="^(FROST|HUMIDITY|ALL)$")):
    """Stored frost and humidity alerts, newest first. Level OK is the all-clear."""
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
    return {"mode": "NORMAL", "message": "Toți senzorii au revenit la vremea normală"}
