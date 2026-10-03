# AgroMonitor

Crop monitoring for farmers: air sensors with per-crop frost and humidity alerts on Telegram,
satellite imagery of weak vegetation zones, and a web app that turns it all into prioritised actions.

## Start everything

Needs JDK 21+, Maven and Python 3.11+.

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

This builds and starts `sensors-alerts`, creates the backend's virtual environment and demo database,
starts the API, loads the satellite results and opens http://localhost:8000/. Each service runs in its
own window; close the windows to stop. `-Reseed` recreates the demo database, `-NoBrowser` skips the browser.

For Telegram alerts put the bot token in `sensors-alerts/.env` first (see `sensors-alerts/README.md`).

## How the parts connect

```
                       ┌────────────────────────────┐
 web app (frontend/) ─>│ Crop Monitor API  :8000    │──> sensors-alerts :8081 ──> Telegram
                       │ backend/, SQLite           │     simulator, frost + humidity rules
                       └────────────────────────────┘
                          ^                  ^
        imagery/push.py ──┘                  └── imagery/out/overlays/*.png (served at /overlays)
        (out/imagery.json)
```

| From → to | What flows | Where |
|---|---|---|
| Web app → API | Everything the page shows; the page only talks to the API | `frontend/AgroMonitorWeb.html` |
| API → sensors-alerts | Readings, frost and humidity levels, alerts, demo scenarios | `backend/app/sensors_client.py` |
| API → sensors-alerts | **Parcels**: every API parcel is registered there, so it gets a sensor and its crop's thresholds | `PUT /sensors/parcels/{id}` |
| Imagery → API | Analysed satellite scenes, newest shown per parcel; weak zones become an action | `imagery/push.py` → `POST /parcels/{id}/imagery` |
| sensors-alerts → Telegram | Frost and humidity alerts with crop-specific advice | `sensors-alerts/.env` |

### One parcel list

The API's database is the list of parcels. `sensors-alerts` starts with the parcels in its
`application.yml` and accepts more at runtime: the API registers a parcel when it is created and again
whenever the sensors service does not know it (for example after that service restarts). A parcel added
in the web app therefore gets a sensor within a few seconds.

Demo parcels (`backend/seed.py`): P1 orchard, P2 vineyard, P3 wheat, P4 corn, P5 sunflower.
**P4 is the real field analysed by the satellite pipeline** (`demo1` in `imagery/parcels.geojson`);
`imagery/push.py` maps `demo1` to `P4`.

### What the API adds on top of each module

- Sensor readings keep the sensors-alerts field names and gain `crop`, `humidityLevel` and `mode`
  from that service, plus the API's own frost priority and reasons.
- `GET /alerts` returns frost and humidity alerts (`type`: `FROST`, `HUMIDITY_HIGH`, `HUMIDITY_LOW`)
  with a title per type; `?type=FROST` or `?type=HUMIDITY` filters.
- `POST /demo/{frost|humid|dry|replay|normal}/{parcelId}` and `POST /demo/reset` drive the simulator.
- `GET /parcels` includes `imagery` (latest scene) and, when the scene has weak zones, an
  `inspect_weak_zone` action. Without a drone report the satellite NDVI is used for the health score.
- The disease action uses the live air sensor's humidity level for the crop when there is one.

## Folders

| Folder | What | Docs |
|---|---|---|
| `sensors-alerts/` | Java / Spring Boot: sensor simulator, per-crop rules, Telegram bot | `sensors-alerts/README.md` |
| `backend/` | Python / FastAPI: parcels, scoring, API for the web app | `backend/README.md` |
| `frontend/` | The web app (served by the API at `/app/`) | |
| `imagery/` | Sentinel-2 pipeline: weak vegetation zones and map overlays | `imagery/README.md` |

## Not wired yet

- Thresholds per crop live in two places: frost and air humidity in `sensors-alerts/application.yml`,
  soil moisture and NDVI in `backend/app/scoring.py`.
- The web app's map is a zone grid; the satellite photo and overlay are shown as an image in the
  "Starea culturii" card, not on a geographic map.
- Telegram only carries sensor alerts, not the API's other actions (irrigation, disease, harvest).
- Sensor readings and alerts are in memory and are lost when `sensors-alerts` restarts.
