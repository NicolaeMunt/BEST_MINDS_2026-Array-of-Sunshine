# Agronomicon

Crop monitoring for farmers. The app shows the air sensors (frost, disease-risk and dry-air alerts on
Telegram that follow each crop's phase, the readings stored with their timestamps, when to water from the
soil water balance, a web app that says in plain words what each sensor means) and, for every parcel, what
the Sentinel-2 satellite saw since May: weak vegetation zones, the picture of the field and how it changed,
refreshed once a day, on a map of the fields.

## Start everything

Needs JDK 21+, Maven and Python 3.11+.

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

This builds and starts `sensors-alerts` (rebuilt when its code or crop rules changed), creates or updates
the virtual environments of the backend and of the satellite job (`imagery/.venv`, with rasterio), starts
the API and opens http://localhost:8000/. Each service runs in its own window; close the windows to stop.
`-NoBrowser` skips the browser.

A `backend/sensors.db` made before the real-weather sample season still holds the invented one: delete it
and `start.ps1` creates it again with the new season.

For Telegram alerts put the bot token in `sensors-alerts/.env` first (see `sensors-alerts/README.md`).

## How the parts connect

```
                       ┌────────────────────────────┐
 web app (frontend/) ─>│ Agronomicon API  :8000     │──> sensors-alerts :8081 ──> Telegram
                       │ backend/, SQLite           │     simulator, frost + humidity rules
                       └─────────────┬──────────────┘
                                     │ once a day: starts the job, then stores its results
                                     ▼
                       satellite job (imagery/) ──> Earth Search: Sentinel-2 scenes
```

| From → to | What flows | Where |
|---|---|---|
| Web app → API | Everything the page shows; the page only talks to the API | `frontend/src/` |
| API → sensors-alerts | Sensor locations, latest reading, frost and humidity levels, alerts, demo scenarios | `backend/app/sensors_client.py` |
| sensors-alerts → API → SQLite | Every reading and alert, copied every 5 s and stored with its timestamp | `backend/app/collector.py` |
| sensors-alerts → Telegram | Frost, disease-risk and dry-air alerts with advice for the crop's phase, and the API's irrigation alerts | `sensors-alerts/.env` |
| API → satellite job | The parcels (polygons) as `imagery/parcels.geojson`; the job runs as its own process | `backend/app/imagery.py` |
| satellite job → API → SQLite | `imagery/out/imagery.json`: one result per parcel and scene, and the scenes skipped for clouds | `backend/app/imagery.py` |
| API → web app | Parcels, the satellite result as of any day, the season history, the PNGs at `/overlays/` | `backend/app/main.py` |

### Stored readings

`sensors-alerts` keeps only the last readings in memory. The API copies them into
`backend/sensors.db` (created on first start, not in git):

```sql
CREATE TABLE sensor_readings (
    parcel_id     TEXT NOT NULL,   -- sensor location, the parcel's cadastral number, as in sensors-alerts
    timestamp     TEXT NOT NULL,   -- when the sensor measured, UTC
    temperature_c REAL NOT NULL,
    humidity_pct  REAL NOT NULL,
    received_at   TEXT NOT NULL,   -- when the API stored it
    PRIMARY KEY (parcel_id, timestamp)
);
```

`GET /sensors/parcels/{id}/readings?minutes=N` serves the chart from this table, so the history survives
a restart of `sensors-alerts` and goes back further than its memory. Windows over two hours come
summarised (one point per 5 minutes, hour or day, with the lowest and highest temperature). The sensor
locations themselves (ID, name, crop) are configured in `sensors-alerts/src/main/resources/application.yml`.

Alerts are stored the same way, in `sensor_alerts` (sensor, time sent, type, level, the readings at that
moment and the text sent to the farmer), and `GET /alerts` reads them from there.

### Crop rules

Every crop goes through phases on a fixed calendar (Orhei area), kept in one place: `app.crops` in
`sensors-alerts/src/main/resources/application.yml`. The sensors service, the API and the satellite job all
read it. Per phase it gives the frost thresholds (none when frost does no harm: not sown, harvested,
dormant), the disease the damp-air rule watches for (hours of damp air at its temperatures, e.g. apple scab,
downy mildew, head blight), the days when dry, hot air harms the crop, and the FAO-56 crop coefficient for
the water balance. The numbers come from extension services, FAO and the Moldovan weather service; the
sources and the reasons are in `imagery/LOGIC.md`, "Reguli pe culturi". When the farmer gives the sowing
date of a corn or sunflower field (profile page), that field's whole calendar moves by the days between the
calendar's sowing day and the farmer's.

### Soil, watering and sowing

Each sensor also has a soil probe: soil temperature at ~5 cm and soil moisture at ~20 cm.
`backend/app/water.py` says when to water: from the soil moisture against the soil's limits (FAO-56) when the
probe reports, which also sees a watering (moisture up without rain); otherwise from a soil water balance of
the temperature and the rain. `backend/app/sowing.py` says "poți semăna" when the soil at seed depth stays at
10 °C or more for three days (corn, sunflower). This advice is listed with the alerts and, once an hour (and
right after the soil moisture jumps), handed to sensors-alerts, which sends it to Telegram like its own.

### Sample season

So there is a history to show, `backend/data/` holds the season of the five demo parcels **from real
weather**, the same season the satellite saw: `sensor-history-sample.csv` (hourly temperature, humidity, rain,
soil temperature and soil moisture since 1 April, Open-Meteo reanalysis at each parcel, CC BY 4.0; not a sensor
in the field) and
`alert-history-sample.csv` (the alerts the crop rules raise on it: a damp first week of June with head
blight risk on the wheat, apple scab in May, downy mildew on the vine, a hot, dry August).

```powershell
cd backend
.venv\Scripts\python.exe load_sample.py   # into sensors.db; start.ps1 does this for a new database
.venv\Scripts\python.exe make_sample.py   # downloads the weather and rewrites the files, up to yesterday
```

### The web app

React without a build step: `frontend/index.html` loads React, ReactDOM and htm from `frontend/vendor/`
and the components from `frontend/src/` as plain ES modules, so it needs neither Node nor internet.
Components are written with htm templates (`html\`<div>...</div>\``) instead of JSX. The fonts
(Bricolage Grotesque and Commissioner, both SIL Open Font License) are in `frontend/vendor/fonts/`.

Written for farmers: large type, plain words, no jargon. A bar on top has the logo (back to the main page)
and the farmer's card (to the profile). Under it, the fields as a row of cards in their status colour, those
with a problem first. The chosen field opens with one coloured block that says what is happening and what to
do (frost, disease risk, hot and dry air, time to water, or all fine), with the temperature now and the crop's
phase; then the air and the soil in two cards, what the satellite sees, the water in the soil, and the
temperature (lowest, mean and highest over the last hour, day, week and month, and a chart). On the right,
"Alerte": every field's alerts of the last 7 days, filtered by high (red) or medium (yellow) risk; a click opens
the field. The profile page (`#/cont`) holds the farmer's name and e-mail and, for each field, its crop and
sowing date, with a map of all fields.
Under the numbers, "Ce vede satelitul": the field on a map (Leaflet, in `frontend/vendor/`) with the
Sentinel-2 picture, the weak zones in red, the main zone and the sensor, a sentence in plain words (what was
seen, how old the picture is, what is normal for the crop's phase), a "Du-mă acolo" link for navigation, and
the clear pictures before and after to step through the season, or any day picked; `?day=2026-07-20` in the
address opens that day. The map background (OpenStreetMap) needs the internet; without it the satellite picture
stays. With `?demo=1` a "Prezentare" panel appears under the alerts: replay a real frost night and real damp or
hot, dry spells of 2026, or water a field.

## Parcels and satellite results

**Parcels.** Each parcel is identified by its **cadastral number**; the five demo parcels near Orhei have
**fictive** numbers (`idsFictive: true`). Developers add parcels in `backend/data/parcels.geojson` (polygon
in lon/lat, name, crop); the API loads that file into the database at start-up. The same IDs are used by
`sensors-alerts` (`application.yml`), so sensors and satellite talk about the same field.

| Cadastral number (fictive) | Name | Crop (assumed from the satellite season curve) |
|---|---|---|
| `6401307.101` | Lotul de Floarea-soarelui | sunflower |
| `6401307.102` | Câmpul Mare | wheat |
| `6401204.045` | Via Nord | vineyard |
| `6401512.033` | Lanul de Porumb | corn |
| `6401512.058` | Livada Sud | orchard |

**Daily run.** A thread in the API starts the satellite job every evening at 21:00 (Sentinel-2 passes over
Moldova around noon), at start-up when the last good run is older than a day, and on
`POST /imagery/refresh`. The job downloads only the new scenes since 1 May, analyses every parcel and the API
stores the output; a parcel added later gets its whole season on the next run. The job runs with its own
Python (`imagery/.venv`), so the API needs neither rasterio nor GDAL.

**Tables** (same `backend/sensors.db`): `users`, `parcels`, `imagery_results` (one row per parcel and scene,
key `(parcel_id, scene_date)`), `imagery_warnings` (fixed codes), `imagery_skipped` (scenes with clouds over
the parcel) and `imagery_runs` (every run of the job). The PNGs are files in `imagery/out/overlays`, served
at `/overlays/`; the database keeps only their paths. Field meanings: `imagery/README.md`; why each rule is
what it is: `imagery/LOGIC.md`.

| Method | Path | What |
|---|---|---|
| GET | `/parcels`, `/parcels/{id}` | Parcels with cadastral number, crop and polygon |
| GET | `/parcels/{id}/imagery?date=2026-07-15` | The newest scene taken on that day or before (with the crop's phase that day), how old it is, and the scenes skipped for clouds since |
| GET | `/parcels/{id}/imagery/history?from=&to=` | Every result and skipped scene of the season, oldest first |
| GET | `/overlays/{file}` | Overlay (weak zones) and photo PNGs; `overlayBounds` = [S, W, N, E] |
| POST | `/imagery/refresh` | Run the satellite job now (202; 409 if running) |
| GET | `/imagery/status` | Last run, last good run, next daily run |
| POST | `/imagery/import` | Store an `imagery/out/imagery.json` by hand (`imagery/push.py`); repeating it changes nothing |

## Folders

| Folder | What | Docs |
|---|---|---|
| `sensors-alerts/` | Java / Spring Boot: sensor simulator, per-crop rules, Telegram bot | `sensors-alerts/README.md` |
| `backend/` | Python / FastAPI: stores the readings, API for the web app | `backend/README.md` |
| `frontend/` | The web app, in React (served by the API at `/app/`) | above |
| `imagery/` | Sentinel-2 pipeline: weak vegetation zones and map overlays | `imagery/README.md` |

## Not wired yet

- The drone and soil reports and the priority score were removed from the API for now.
- The crop calendar is fixed by date; an early or late year can be 1-2 weeks off. Telling the phase from
  the satellite curve (e.g. "harvested") would fix that for the field crops.
- Without a soil probe, the water balance does not know when the farmer watered.
- The soil limits are those of a silt loam for every parcel; a sandy or clay field would need its own.
- `frontend/AgroMonitor.html` is the earlier static mobile prototype; it does not use the API.
