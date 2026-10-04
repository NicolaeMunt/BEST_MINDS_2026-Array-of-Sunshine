import os
import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import crops, db, imagery, sensors, sensors_client
from .collector import Collector
from .models import (AlertOut, CropIn, CropOptionOut, SowingIn, DemoOut, TemperatureStatOut, UserIn, UserOut, ImageryAtDateOut, ImageryFileIn, ImageryHistoryOut, ImageryImportOut,
                     ImageryStatusOut, ParcelOut, SensorLatestOut, SensorParcelOut, SensorReadingOut, WaterStatusOut)
from .sensors_client import SensorsConflict, SensorsUnavailable

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
    "humid": ("HUMID", "Redau accelerat o perioadă umedă reală din 2026, cu risc de boală pentru această cultură"),
    "dry": ("DRY", "Redau accelerat o perioadă reală de aer fierbinte și uscat din 2026"),
    "replay": ("REPLAY", "Redarea nopții reale de îngheț a pornit"),
    "normal": ("NORMAL", "Terenul a revenit la vremea normală"),
    "irrigate": (None, "Am udat terenul: umiditatea solului urcă spre capacitatea de câmp"),
}


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    imagery.load_seed()
    imagery.load_saved_output()
    collector = Collector()
    collector.start()
    app.state.updater = imagery.Updater()
    app.state.updater.start()
    yield
    app.state.updater.stop()
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

# Overlay and photo PNGs written by the satellite job; the results refer to them as /overlays/<file>.
app.mount("/overlays", StaticFiles(directory=imagery.OVERLAYS_DIR, check_dir=False), name="overlays")


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


STAT_WINDOWS = (60, 24 * 60, 7 * 24 * 60, 30 * 24 * 60)


@app.get("/sensors/parcels/{parcel_id}/stats", response_model=list[TemperatureStatOut])
def temperature_stats(parcel_id: str):
    """Lowest, mean and highest temperature and air humidity over the last hour, day, week and month (counted back from the newest
    reading, so a replay shows its own night)."""
    with db.get_conn() as conn:
        rows = db.temperature_stats(conn, parcel_id, STAT_WINDOWS)
    r1 = lambda v: None if v is None else round(v, 1)
    return [{"minutes": m, "min_c": r["lo"], "mean_c": r1(r["mean"]), "max_c": r["hi"], "min_humidity_pct": r1(r["h_lo"]),
             "mean_humidity_pct": r1(r["h_mean"]), "max_humidity_pct": r1(r["h_hi"]), "readings": r["n"] or 0}
            for m, r in rows]


@app.get("/sensors/parcels/{parcel_id}/water", response_model=WaterStatusOut)
def soil_water(parcel_id: str, day: date | None = Query(None, alias="date", description="YYYY-MM-DD; default today")):
    """Soil water balance of the parcel on that day (FAO-56) and day by day since 1 May: when to water and how much."""
    with db.get_conn() as conn:
        row = db.parcel(conn, parcel_id)
    status = sensors.water_status(parcel_id, row["crop"] if row else None, day, with_days=True)
    if not status:
        raise HTTPException(404, f"No water balance for parcel {parcel_id}")
    return status


@app.get("/alerts", response_model=list[AlertOut])
def recent_alerts(parcel_id: str | None = Query(None, alias="parcelId"),
                  type_: str = Query("ALL", alias="type", pattern="^(FROST|HUMIDITY|IRRIGATION|SOWING|ALL)$")):
    """Frost, humidity, watering and sowing alerts, newest first. Level OK is the all-clear."""
    return sensors.alerts(parcel_id, type_)


# ---------- demo (forwarded to sensors-alerts) ----------

@app.post("/demo/{kind}/{parcel_id}", response_model=DemoOut)
def demo(kind: str, parcel_id: str):
    """kind: frost | humid | dry | replay | normal (normal sends the all-clear messages) | irrigate (a watering
    the soil probe sees; the mode does not change)."""
    if kind not in DEMO_MESSAGES:
        raise HTTPException(404, f"Unknown demo scenario {kind}")
    try:
        answer = sensors_client.demo(kind, parcel_id)
    except SensorsConflict as e:  # no recorded spell for the crop, or a replay running
        raise HTTPException(409, str(e)) from e
    if answer is None:
        raise HTTPException(404, f"Parcel {parcel_id} unknown to the sensors service")
    mode, message = DEMO_MESSAGES[kind]
    if mode is None:  # irrigate keeps the parcel's mode
        mode = answer.get("mode", "NORMAL")
    else:
        sensors.set_mode(parcel_id, mode)
    return {"parcel_id": parcel_id, "mode": mode, "message": message}


@app.post("/demo/reset", response_model=DemoOut)
def demo_reset():
    sensors_client.demo_reset()
    sensors.reset_modes()
    return {"mode": "NORMAL", "message": "Toți senzorii au revenit la vremea normală"}


# ---------- the farmer's account ----------

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _user_out(row):
    return {"id": row["id"], "name": row["name"], "first_name": row["first_name"], "last_name": row["last_name"],
            "email": row["email"]}


@app.get("/users/me", response_model=UserOut)
def get_me():
    """The demo farmer (there is one user until there is a login)."""
    with db.get_conn() as conn:
        return _user_out(db.user(conn, imagery.DEMO_USER[0]))


@app.put("/users/me", response_model=UserOut)
def update_me(body: UserIn):
    first, last, email = body.first_name.strip(), body.last_name.strip(), body.email.strip()
    if email and not EMAIL.match(email):
        raise HTTPException(422, "Adresa de e-mail nu pare corectă")
    with db.get_conn() as conn:
        db.update_user(conn, imagery.DEMO_USER[0], first, last, email)
        return _user_out(db.user(conn, imagery.DEMO_USER[0]))


SOWN_CROPS = {"wheat", "barley", "corn", "sunflower"}


@app.get("/crops", response_model=list[CropOptionOut])
def crop_options():
    """The crops the rules know, with their Romanian names."""
    # Orchards and vineyards are planted once; wheat, corn and sunflower are sown every year.
    return [{"key": key, "name": cfg["name"], "sown": key in SOWN_CROPS} for key, cfg in crops.config()["crops"].items()]


@app.put("/parcels/{parcel_id}/crop", response_model=ParcelOut)
def set_parcel_crop(parcel_id: str, body: CropIn):
    """The farmer says what grows on the parcel: the rules of sensors-alerts follow it at once; the satellite
    advice follows from the next daily run."""
    row = _require_parcel(parcel_id)
    if not crops.crop(body.crop):
        raise HTTPException(422, f"Unknown crop {body.crop}")
    with db.get_conn() as conn:
        db.set_crop(conn, parcel_id, body.crop)
        row = db.parcel(conn, parcel_id)
    try:
        sensors_client.register_parcel(parcel_id, row["name"], body.crop, row["sowing_date"])
    except SensorsUnavailable:
        pass  # the collector registers it when the service is back
    return imagery.parcel_out(row)


@app.put("/parcels/{parcel_id}/sowing", response_model=ParcelOut)
def set_parcel_sowing(parcel_id: str, body: SowingIn):
    """When the farmer sowed: for corn and sunflower the crop calendar (frost thresholds, disease and dry windows,
    watering, what is normal on the satellite) moves with it; for wheat it is kept and shown."""
    row = _require_parcel(parcel_id)
    with db.get_conn() as conn:
        db.set_sowing_date(conn, parcel_id, body.sowing_date.isoformat() if body.sowing_date else None)
        row = db.parcel(conn, parcel_id)
    try:
        sensors_client.register_parcel(parcel_id, row["name"], row["crop"], row["sowing_date"])
    except SensorsUnavailable:
        pass
    return imagery.parcel_out(row)


# ---------- parcels and satellite imagery ----------

def _require_parcel(parcel_id):
    with db.get_conn() as conn:
        row = db.parcel(conn, parcel_id)
    if not row:
        raise HTTPException(404, f"Parcel {parcel_id} not found")
    return row


@app.get("/parcels", response_model=list[ParcelOut])
def list_parcels():
    """Parcels with their cadastral number, crop and polygon (developers add them in backend/data/parcels.geojson)."""
    with db.get_conn() as conn:
        return [imagery.parcel_out(row) for row in db.parcels(conn)]


@app.get("/parcels/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: str):
    return imagery.parcel_out(_require_parcel(parcel_id))


@app.get("/parcels/{parcel_id}/imagery", response_model=ImageryAtDateOut)
def imagery_at_date(parcel_id: str, day: date | None = Query(None, alias="date",
                                                             description="YYYY-MM-DD; default today")):
    """The satellite picture of the parcel as it was on that day: the newest scene taken on the day or before it,
    how many days old it is, and the scenes skipped for clouds since."""
    _require_parcel(parcel_id)
    return imagery.at_date(parcel_id, day or imagery.today())


@app.get("/parcels/{parcel_id}/imagery/history", response_model=ImageryHistoryOut)
def imagery_history(parcel_id: str, start: date | None = Query(None, alias="from", description="default: season start"),
                    end: date | None = Query(None, alias="to", description="default: today")):
    """Every analysed scene and every scene skipped for clouds, oldest first: the season chart and the timeline."""
    _require_parcel(parcel_id)
    return imagery.history(parcel_id, start or date.fromisoformat(imagery.SEASON_START), end or imagery.today())


@app.post("/imagery/import", response_model=ImageryImportOut)
def imagery_import(body: ImageryFileIn):
    """Stores an imagery/out/imagery.json (imagery/push.py sends it). Sending the same file again changes nothing."""
    data = body.model_dump(mode="json")
    unknown = imagery.unknown_parcels(data)
    if unknown:
        raise HTTPException(422, f"Unknown parcels: {', '.join(unknown)}")
    return {"new_scenes": imagery.import_data(data)}


@app.post("/imagery/refresh", response_model=ImageryStatusOut, status_code=202)
def imagery_refresh(request: Request):
    """Starts the satellite job now (new scenes since the last run, analysis, database); 409 if it is running."""
    updater = request.app.state.updater
    if not updater.trigger():
        raise HTTPException(409, "The satellite job is already running")
    return imagery.status(updater)


@app.get("/imagery/status", response_model=ImageryStatusOut)
def imagery_status(request: Request):
    """Whether the satellite job is running, how its last runs went and when the next daily run is."""
    return imagery.status(request.app.state.updater)
