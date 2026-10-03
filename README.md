# AgroMonitor

Crop monitoring for farmers. For now the app shows the air sensors: per-crop frost and humidity alerts
on Telegram, the readings stored with their timestamps, and a web app that says in plain words what
each sensor means. The parcel view and the satellite analytics are being built separately.

## Start everything

Needs JDK 21+, Maven and Python 3.11+.

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

This builds and starts `sensors-alerts`, creates the backend's virtual environment, starts the API and
opens http://localhost:8000/. Each service runs in its own window; close the windows to stop.
`-NoBrowser` skips the browser.

For Telegram alerts put the bot token in `sensors-alerts/.env` first (see `sensors-alerts/README.md`).

## How the parts connect

```
                       ┌────────────────────────────┐
 web app (frontend/) ─>│ Crop Monitor API  :8000    │──> sensors-alerts :8081 ──> Telegram
                       │ backend/, SQLite           │     simulator, frost + humidity rules
                       └────────────────────────────┘
```

| From → to | What flows | Where |
|---|---|---|
| Web app → API | Everything the page shows; the page only talks to the API | `frontend/src/` |
| API → sensors-alerts | Sensor locations, latest reading, frost and humidity levels, alerts, demo scenarios | `backend/app/sensors_client.py` |
| sensors-alerts → API → SQLite | Every reading, copied every 5 s and stored with its timestamp | `backend/app/collector.py` |
| sensors-alerts → Telegram | Frost and humidity alerts with crop-specific advice | `sensors-alerts/.env` |

### Stored readings

`sensors-alerts` keeps only the last readings in memory. The API copies them into
`backend/sensors.db` (created on first start, not in git):

```sql
CREATE TABLE sensor_readings (
    parcel_id     TEXT NOT NULL,   -- sensor location, same IDs as sensors-alerts (P1, P2, ...)
    timestamp     TEXT NOT NULL,   -- when the sensor measured, UTC
    temperature_c REAL NOT NULL,
    humidity_pct  REAL NOT NULL,
    received_at   TEXT NOT NULL,   -- when the API stored it
    PRIMARY KEY (parcel_id, timestamp)
);
```

`GET /sensors/parcels/{id}/readings?minutes=N` serves the chart from this table, so the history survives
a restart of `sensors-alerts` and goes back further than its memory. The sensor locations themselves
(ID, name, crop) are configured in `sensors-alerts/src/main/resources/application.yml`.

### The web app

React without a build step: `frontend/index.html` loads React, ReactDOM and htm from `frontend/vendor/`
and the components from `frontend/src/` as plain ES modules, so it needs neither Node nor internet.
Components are written with htm templates (`html\`<div>...</div>\``) instead of JSX. The fonts
(Bricolage Grotesque and Commissioner, both SIL Open Font License) are in `frontend/vendor/fonts/`.

The left column lists the sensors, those that need attention first. The selected sensor's sheet says
what its readings mean right now (frost, air too humid or too dry, or all fine), shows the current
numbers, the temperature over time from the stored readings, and the alerts that were sent.

## Folders

| Folder | What | Docs |
|---|---|---|
| `sensors-alerts/` | Java / Spring Boot: sensor simulator, per-crop rules, Telegram bot | `sensors-alerts/README.md` |
| `backend/` | Python / FastAPI: stores the readings, API for the web app | `backend/README.md` |
| `frontend/` | The web app, in React (served by the API at `/app/`) | above |
| `imagery/` | Sentinel-2 pipeline: weak vegetation zones and map overlays | `imagery/README.md` |

## Not wired yet

- Parcels, the drone and soil reports and the priority score were removed from the API for now; they
  come back with the parcel view. `imagery/push.py` has no endpoint to post to until then.
- Alerts are still only in the memory of `sensors-alerts` and are lost when it restarts.
- `frontend/AgroMonitor.html` is the earlier static mobile prototype; it does not use the API.
