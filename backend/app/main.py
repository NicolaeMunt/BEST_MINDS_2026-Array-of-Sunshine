import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import accounts, db, imagery, sensors, sensors_client
from .accounts import Invalid
from .collector import Collector
from .models import (AdminUserDetailOut, AdminUserOut, AlertOut, DemoOut, FieldIn, FieldOut, ImageryAtDateOut,
                     ImageryFileIn, ImageryHistoryOut, ImageryImportOut, ImageryStatusOut, LoginIn, ParcelOut,
                     PasswordIn, ProfileIn, RegisterIn, SensorLatestOut, SensorParcelOut, SensorReadingOut, SessionOut,
                     UserOut, WaterStatusOut)
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


@app.exception_handler(Invalid)
def invalid_input(request: Request, exc: Invalid):
    """{detail: first message, fields: {field: message}}: the page shows each message next to its field."""
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "fields": exc.fields})


# ---------- accounts ----------

def _token(authorization):
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def current_user(authorization: str | None = Header(None)):
    """The signed-in user, or None: most of the API works without an account (the demo sensors)."""
    return accounts.user_for_token(_token(authorization))


def signed_in(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "Intră în cont ca să continui.")
    return user


def admin(user=Depends(signed_in)):
    if user["role"] != "admin":
        raise HTTPException(403, "Doar administratorul poate face asta.")
    return user


def _visible(parcel_id, user):
    """A user field is answered only for its owner; for anyone else it does not exist."""
    if not accounts.can_see(parcel_id, user):
        raise HTTPException(404, f"Unknown parcel {parcel_id}")


def _register_sensor(field):
    """Starts the field's simulated sensor now; if sensors-alerts is down, the collector does it later."""
    try:
        sensors_client.register(field["id"], field["name"], field["crop"])
    except SensorsUnavailable:
        pass


@app.post("/auth/register", response_model=SessionOut, status_code=201)
def register(body: RegisterIn):
    """New account (name, email, phone, password of at least 8 characters), signed in straight away."""
    return accounts.register(body.name, body.email, body.phone, body.password)


@app.post("/auth/login", response_model=SessionOut)
def login(body: LoginIn):
    return accounts.login(body.email, body.password)


@app.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(None)):
    if _token(authorization):
        accounts.logout(_token(authorization))
    return Response(status_code=204)


@app.get("/me", response_model=UserOut)
def me(user=Depends(signed_in)):
    return user


@app.put("/me", response_model=UserOut)
def update_me(body: ProfileIn, user=Depends(signed_in)):
    """Name, email and phone; all three are required."""
    return accounts.update_profile(user["id"], body.name, body.email, body.phone)


@app.put("/me/password", status_code=204)
def change_password(body: PasswordIn, user=Depends(signed_in)):
    accounts.change_password(user["id"], body.current, body.new)
    return Response(status_code=204)


@app.get("/me/fields", response_model=list[FieldOut])
def my_fields(user=Depends(signed_in)):
    """The user's fields. Only an administrator adds, changes or deletes them (/admin/...)."""
    return accounts.fields(user["id"])


# ---------- administrators: the users and their fields from the official documents ----------

def _field_data(body):
    return {"name": body.name, "crop": body.crop, "area_ari": body.area_ari, "cadastral_number": body.cadastral_number,
            "location": body.location, "doc_type": body.doc_type, "doc_number": body.doc_number, "doc_date": body.doc_date,
            "coordinates": body.coordinates}


@app.get("/admin/users", response_model=list[AdminUserOut])
def admin_users(q: str = "", _=Depends(admin)):
    """Every account, newest first; q filters by name, email or phone."""
    return accounts.users(q)


@app.get("/admin/users/{user_id}", response_model=AdminUserDetailOut)
def admin_user(user_id: int, _=Depends(admin)):
    return {"user": accounts.user(user_id), "fields": accounts.fields(user_id)}


@app.post("/admin/users/{user_id}/fields", response_model=FieldOut, status_code=201)
def admin_add_field(user_id: int, body: FieldIn, request: Request, me=Depends(admin)):
    """A field from an official document into the user's profile, with its outline. It gets a simulated sensor
    with the crop's frost and humidity thresholds, and the satellite job runs for it right away."""
    field = accounts.add_field(me["id"], user_id, _field_data(body))
    _register_sensor(field)
    request.app.state.updater.queue()
    return field


@app.put("/admin/fields/{field_id}", response_model=FieldOut)
def admin_update_field(field_id: str, body: FieldIn, request: Request, _=Depends(admin)):
    """A new outline drops the old satellite results and cached scenes; the satellite job runs again."""
    field, outline_changed = accounts.update_field(field_id, _field_data(body))
    _register_sensor(field)
    if outline_changed:
        imagery.forget_parcel(field_id)
        request.app.state.updater.queue()
    return field


@app.delete("/admin/fields/{field_id}", status_code=204)
def admin_delete_field(field_id: str, _=Depends(admin)):
    accounts.delete_field(field_id)
    imagery.forget_parcel(field_id)
    return Response(status_code=204)


# ---------- frontend ----------

@app.get("/sensors/parcels", response_model=list[SensorParcelOut])
def sensor_parcels(user=Depends(current_user)):
    """The signed-in user's own fields, then the demo sensors (from sensors-alerts), each with its latest reading."""
    return sensors.parcels(user)


@app.get("/sensors/parcels/{parcel_id}/latest", response_model=SensorLatestOut)
def latest_reading(parcel_id: str, user=Depends(current_user)):
    """Latest reading + dew point + frost level (from sensors-alerts) + priority and reasons."""
    _visible(parcel_id, user)
    latest = sensors.latest(parcel_id)
    if not latest:
        raise HTTPException(404, f"No readings for parcel {parcel_id}")
    return latest


@app.get("/sensors/parcels/{parcel_id}/readings", response_model=list[SensorReadingOut])
def stored_readings(parcel_id: str, minutes: int = Query(60, ge=1, le=366 * 24 * 60), user=Depends(current_user)):
    """Stored readings of the last N minutes (counted back from the newest reading), oldest first.
    Windows over two hours come summarised: one point per 5 minutes, hour or day, with min and max."""
    _visible(parcel_id, user)
    return sensors.readings(parcel_id, minutes)


@app.get("/sensors/parcels/{parcel_id}/water", response_model=WaterStatusOut)
def soil_water(parcel_id: str, day: date | None = Query(None, alias="date", description="YYYY-MM-DD; default today"),
               user=Depends(current_user)):
    """Soil water balance of the parcel on that day (FAO-56) and day by day since 1 May: when to water and how much."""
    _visible(parcel_id, user)
    with db.get_conn() as conn:
        row = db.parcel(conn, parcel_id)
    status = sensors.water_status(parcel_id, row["crop"] if row else None, day, with_days=True)
    if not status:
        raise HTTPException(404, f"No water balance for parcel {parcel_id}")
    return status


@app.get("/alerts", response_model=list[AlertOut])
def recent_alerts(parcel_id: str | None = Query(None, alias="parcelId"),
                  type_: str = Query("ALL", alias="type", pattern="^(FROST|HUMIDITY|IRRIGATION|SOWING|ALL)$"),
                  user=Depends(current_user)):
    """Frost, humidity, watering and sowing alerts, newest first. Level OK is the all-clear. Without parcelId:
    those of the demo parcels and of the signed-in user's parcels."""
    if parcel_id:
        _visible(parcel_id, user)
        return sensors.alerts(parcel_id, type_)
    visible = {row["id"] for row, _ in accounts.visible_parcels(user)}
    return [a for a in sensors.alerts(None, type_) if a["parcelId"] in visible]


# ---------- demo (forwarded to sensors-alerts) ----------

@app.post("/demo/{kind}/{parcel_id}", response_model=DemoOut)
def demo(kind: str, parcel_id: str, user=Depends(current_user)):
    """kind: frost | humid | dry | replay | normal (normal sends the all-clear messages) | irrigate (a watering
    the soil probe sees; the mode does not change)."""
    if kind not in DEMO_MESSAGES:
        raise HTTPException(404, f"Unknown demo scenario {kind}")
    _visible(parcel_id, user)
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


# ---------- parcels and satellite imagery ----------

def _require_parcel(parcel_id, user):
    """The parcel, if this user may see it (demo parcels: everyone; a user's parcel: its owner)."""
    with db.get_conn() as conn:
        row = db.parcel(conn, parcel_id)
    if not row or not accounts.can_see(parcel_id, user):
        raise HTTPException(404, f"Parcel {parcel_id} not found")
    return row


@app.get("/parcels", response_model=list[ParcelOut])
def list_parcels(user=Depends(current_user)):
    """The demo parcels (backend/data/parcels.geojson) and the signed-in user's ones, with their cadastral number,
    crop and polygon (a user's parcel has none until it gets one)."""
    return [imagery.parcel_out(row) for row, _ in accounts.visible_parcels(user)]


@app.get("/parcels/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: str, user=Depends(current_user)):
    return imagery.parcel_out(_require_parcel(parcel_id, user))


@app.get("/parcels/{parcel_id}/imagery", response_model=ImageryAtDateOut)
def imagery_at_date(parcel_id: str, day: date | None = Query(None, alias="date",
                                                             description="YYYY-MM-DD; default today"),
                    user=Depends(current_user)):
    """The satellite picture of the parcel as it was on that day: the newest scene taken on the day or before it,
    how many days old it is, and the scenes skipped for clouds since."""
    _require_parcel(parcel_id, user)
    return imagery.at_date(parcel_id, day or imagery.today())


@app.get("/parcels/{parcel_id}/imagery/history", response_model=ImageryHistoryOut)
def imagery_history(parcel_id: str, start: date | None = Query(None, alias="from", description="default: season start"),
                    end: date | None = Query(None, alias="to", description="default: today"),
                    user=Depends(current_user)):
    """Every analysed scene and every scene skipped for clouds, oldest first: the season chart and the timeline."""
    _require_parcel(parcel_id, user)
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
