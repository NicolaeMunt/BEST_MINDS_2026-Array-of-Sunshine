# Agronomicon

Crop monitoring for farmers. The app shows the air sensors (frost, disease-risk and dry-air alerts on
Telegram that follow each crop's phase, the readings stored with their timestamps, when to water from the
soil water balance, a web app that says in plain words what each sensor means) and, for every parcel, what
the Sentinel-2 satellite saw since May: weak vegetation zones, the picture of the field and how it changed,
refreshed once a day, on a map of the fields. Farmers create an account;
an administrator enters their parcels from the official land documents.

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
| API → sensors-alerts | Each user parcel, registered by its cadastral number so it gets a simulated sensor | `backend/app/collector.py` |

### Accounts, administrators and parcels

Anyone can open the web app and see the demo parcels (those of `backend/data/parcels.geojson`, owned by
"Fermier demo", who cannot sign in). A farmer creates an account (`#/register`: name, email, phone,
password); email and phone are required, at sign-up and in the profile (`#/profile`). The farmer cannot add
parcels: the profile only shows them.

A user's parcels are entered by an **administrator** on `#/admin`: the list of all users (search by name,
email or phone), and for the chosen one their parcels and a form that copies the official document: type of
document (title, extract from the real estate register, sale, donation, inheritance, lease), its number and
date, the cadastral number, village and district, the area in ares (shown in hectares too), the crop, whose
thresholds the alerts use, and the parcel's outline: clicked corner by corner on a map with a satellite photo
background (corners can be dragged, a right click removes one) or pasted as `lat, lon` lines from the document.
The page compares the outline's area with the document's. The administrator can also change or delete a parcel.

An account becomes an administrator from the command line, after it has been registered in the web app:

```powershell
cd backend
.venv\Scripts\python.exe make_admin.py ion@exemplu.md            # administrator
.venv\Scripts\python.exe make_admin.py ion@exemplu.md --remove   # ordinary user again
```

- A user's parcel is a row of `parcels` like the demo ones: its ID is the cadastral number (one parcel per
  number, it cannot be changed afterwards), with the document's data in extra columns and the outline in
  `geometry`. It is on the map in the side column and the satellite job analyses it like the demo parcels: the
  API starts a run as soon as a parcel is added or gets a new outline (a new outline drops its old results and
  cached scenes). The job reads one Sentinel-2 tile (35TPN, around Orhei); a parcel outside it is on the map
  but gets no pictures, and the form says so.
- The satellite job writes into `imagery/out/` (kept in git for the demo parcels): with user parcels its
  results and pictures appear there too and should not be committed.
- It is registered in sensors-alerts (`PUT /sensors/parcels/{cadastral number}`), which starts a simulated
  sensor with that crop's thresholds. sensors-alerts keeps such parcels in memory only, so the collector
  registers them again within 5 s after it restarts.
- A user sees their own parcels and the demo ones, in every endpoint (sensors, alerts, `/parcels`, satellite,
  water); other users' parcels answer `404`.
- Passwords are stored as scrypt hashes (Python standard library). Signing in gives a token that the page keeps
  in `localStorage` and sends as `Authorization: Bearer`; it lasts 30 days.
- A deleted parcel loses its stored readings and alerts. Its simulated sensor runs on until sensors-alerts
  restarts (that service cannot forget a parcel); the API hides it and stops storing it.
- Alerts for user parcels go to the same Telegram chats as the demo ones: sensors-alerts does not know which
  chat belongs to which user yet.

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
sources and the reasons are in `imagery/LOGIC.md`, "Reguli pe culturi".

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

The page asks the API for new data once an hour; the **Actualizează** button asks right away. While a presentation
scenario runs it follows the sensor every 3 s, and while the server is down it retries every 5 s. The fields list
and each block of the sheet fold open and shut (`src/Fold.js`), and the page remembers which ones are folded.

Written for farmers: large type, plain words, no jargon. The left column lists the fields (one sensor
each), those with a problem first. The selected field opens with one coloured block that says what is
happening and what to do (frost, disease risk, hot and dry air, time to water, or all fine), then the
temperature and humidity now with the crop's phase, then the water in the soil, then the temperature over
time (now, a day, a week or since April) with every alert marked on it and listed underneath, one line each.
Under the numbers, "Ce vede satelitul": the field on a map (Leaflet, in `frontend/vendor/`) with the
Sentinel-2 picture, the weak zones in red, the main zone and the sensor, a sentence in plain words (what was
seen, how old the picture is, what is normal for the crop's phase), a "Du-mă acolo" link for navigation, and
the season's passes (clear or cloudy) to pick any day; `?day=2026-07-20` in the address opens that day. A small
map in the side column shows all the fields in their status colour. The map background (OpenStreetMap) needs the
internet; without it the satellite picture stays. The demo menu can replay a real frost night and real damp or
hot, dry spells of 2026, and water a field.

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
