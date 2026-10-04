"""SQLite storage: sensor readings and alerts with their timestamps, copied from the sensors-alerts
service (see collector.py); users with their sign-in data and sessions (see accounts.py) and parcels, the demo
ones from backend/data/parcels.geojson and the users' ones entered by an administrator from the official land
documents; the satellite results of every parcel and scene, with the scenes skipped for clouds and the runs of
the daily satellite job (see imagery.py)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parent.parent / "sensors.db"))

# Timestamps are text in one fixed UTC format (see ts_text), so comparing the text compares the time.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    parcel_id     TEXT NOT NULL,   -- sensor location, cadastral number, as in the sensors-alerts service
    timestamp     TEXT NOT NULL,   -- when the sensor measured
    temperature_c REAL NOT NULL,
    humidity_pct  REAL NOT NULL,
    received_at   TEXT NOT NULL,   -- when this API stored it; differs from timestamp for a replayed night
    precipitation_mm REAL,         -- rain since the previous reading; NULL when the sensor does not say
    soil_temperature_c REAL,       -- soil at ~5 cm; NULL without a soil probe
    soil_moisture_pct  REAL,       -- soil water at ~20 cm, % of the soil volume; NULL without a soil probe
    PRIMARY KEY (parcel_id, timestamp)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_readings_received ON sensor_readings(parcel_id, received_at);
CREATE TABLE IF NOT EXISTS sensor_alerts (
    parcel_id     TEXT NOT NULL,
    timestamp     TEXT NOT NULL,   -- when the alert was sent
    type          TEXT NOT NULL,   -- FROST | HUMIDITY_HIGH | HUMIDITY_LOW | IRRIGATION | SOWING
    level         TEXT NOT NULL,   -- WARNING | CRITICAL | OK (the all-clear)
    parcel_name   TEXT NOT NULL,
    crop          TEXT,
    temperature_c REAL NOT NULL,
    humidity_pct  REAL NOT NULL,
    dew_point_c   REAL NOT NULL,
    message       TEXT NOT NULL,   -- the text sent to the farmer
    received_at   TEXT NOT NULL,
    PRIMARY KEY (parcel_id, timestamp, type, level)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,   -- SHA-256 of the token the browser holds; the token itself is not stored
    user_id       INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
) WITHOUT ROWID;
"""
# Local days for the daily summary: Europe/Chisinau in summer. Good enough for a May-October season.
LOCAL_OFFSET_SEC = 3 * 3600
ALERT_COLUMNS = ("parcel_id", "timestamp", "type", "level", "parcel_name", "crop", "temperature_c",
                 "humidity_pct", "dew_point_c", "message", "received_at")


def ts_text(ts):
    """Aware datetime -> 2026-10-03T14:24:41.600Z"""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(IMAGERY_SCHEMA)
        # Databases created before these columns were added get them here.
        for table, columns in LATER_COLUMNS.items():
            have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        conn.executescript(INDEXES)


def add_readings(conn, parcel_id, readings, received_at):
    """readings: (timestamp text, temperature, humidity[, rain mm[, soil temperature, soil moisture]]). A reading
    stored before is replaced, so a night replayed twice is kept once and counts as the newest data again."""
    conn.executemany(
        "INSERT INTO sensor_readings (parcel_id, timestamp, temperature_c, humidity_pct, precipitation_mm, "
        "soil_temperature_c, soil_moisture_pct, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (parcel_id, timestamp) DO UPDATE SET "
        "temperature_c = excluded.temperature_c, humidity_pct = excluded.humidity_pct, "
        "precipitation_mm = excluded.precipitation_mm, soil_temperature_c = excluded.soil_temperature_c, "
        "soil_moisture_pct = excluded.soil_moisture_pct, received_at = excluded.received_at",
        [(parcel_id, *r[:3], *(list(r[3:6]) + [None] * (6 - len(r))), received_at) for r in readings],
    )


def daily_weather(conn, parcel_id, start, end):
    """One row per local day from start to end (dates, both included) that has readings: the lowest and highest
    temperature, the lowest humidity, the rain and how many readings there were."""
    first = ts_text(datetime(start.year, start.month, start.day, tzinfo=timezone.utc) - timedelta(seconds=LOCAL_OFFSET_SEC))
    last = ts_text(datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1, seconds=-LOCAL_OFFSET_SEC))
    return conn.execute(
        "SELECT date(timestamp, ?) AS day, MIN(temperature_c) AS t_min, MAX(temperature_c) AS t_max, "
        "MIN(humidity_pct) AS hum_min, COALESCE(SUM(precipitation_mm), 0) AS rain_mm, COUNT(*) AS readings "
        "FROM sensor_readings WHERE parcel_id = ? AND timestamp >= ? AND timestamp < ? GROUP BY 1 ORDER BY 1",
        (f"+{LOCAL_OFFSET_SEC} seconds", parcel_id, first, last),
    ).fetchall()


def soil_hours(conn, parcel_id, start, end, by_minute=False):
    """One row per clock hour (UTC) from start to end (aware datetimes) with soil readings: the start of the hour,
    its mean soil temperature and moisture and its rain, oldest first. by_minute: one row per minute with the
    minute's last soil reading (SQLite takes the bare columns from the row of MAX), so a quick change is not
    averaged away."""
    if by_minute:
        key, soil = "substr(timestamp, 1, 16) || ':00.000Z'", "soil_temperature_c AS soil_t, soil_moisture_pct AS soil_m, MAX(timestamp)"
    else:
        key, soil = "substr(timestamp, 1, 13) || ':00:00.000Z'", "AVG(soil_temperature_c) AS soil_t, AVG(soil_moisture_pct) AS soil_m"
    return conn.execute(
        f"SELECT {key} AS hour, {soil}, COALESCE(SUM(precipitation_mm), 0) AS rain_mm FROM sensor_readings "
        "WHERE parcel_id = ? AND timestamp >= ? AND timestamp < ? AND soil_moisture_pct IS NOT NULL "
        "GROUP BY 1 ORDER BY 1",
        (parcel_id, ts_text(start), ts_text(end)),
    ).fetchall()


def latest_soil_time(conn, parcel_id, end):
    """Timestamp of the newest reading with soil data before `end` (aware datetime), or None."""
    row = conn.execute("SELECT MAX(timestamp) AS t FROM sensor_readings WHERE parcel_id = ? AND timestamp < ? "
                       "AND soil_moisture_pct IS NOT NULL", (parcel_id, ts_text(end))).fetchone()
    return row["t"]


def newest_timestamp(conn, parcel_id):
    """Timestamp of the reading stored last, or None. Not the latest timestamp: a replay carries old ones."""
    row = conn.execute(
        "SELECT timestamp FROM sensor_readings WHERE parcel_id = ? ORDER BY received_at DESC, timestamp DESC LIMIT 1",
        (parcel_id,),
    ).fetchone()
    return row["timestamp"] if row else None


def readings(conn, parcel_id, minutes):
    """Readings of the last N minutes, counted back from the newest reading, oldest first."""
    newest = newest_timestamp(conn, parcel_id)
    if not newest:
        return []
    start = ts_text(datetime.fromisoformat(newest.replace("Z", "+00:00")) - timedelta(minutes=minutes))
    return conn.execute(
        "SELECT parcel_id, timestamp, temperature_c, humidity_pct FROM sensor_readings "
        "WHERE parcel_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
        (parcel_id, start, newest),
    ).fetchall()


def readings_summary(conn, parcel_id, minutes, bucket_sec):
    """The same window as readings(), one row per bucket_sec of time: the first timestamp, the average
    temperature and humidity, the lowest and highest temperature. Day-long buckets follow local days."""
    newest = newest_timestamp(conn, parcel_id)
    if not newest:
        return []
    start = ts_text(datetime.fromisoformat(newest.replace("Z", "+00:00")) - timedelta(minutes=minutes))
    return conn.execute(
        "SELECT parcel_id, MIN(timestamp) AS timestamp, AVG(temperature_c) AS temperature_c, "
        "AVG(humidity_pct) AS humidity_pct, MIN(temperature_c) AS min_temperature_c, "
        "MAX(temperature_c) AS max_temperature_c FROM sensor_readings "
        "WHERE parcel_id = ? AND timestamp BETWEEN ? AND ? "
        "GROUP BY (CAST(strftime('%s', timestamp) AS INTEGER) + ?) / ? ORDER BY 2",
        (parcel_id, start, newest, LOCAL_OFFSET_SEC if bucket_sec >= 86400 else 0, bucket_sec),
    ).fetchall()


def alert_stored(conn, parcel_id, timestamp, type_, level):
    return conn.execute("SELECT 1 FROM sensor_alerts WHERE parcel_id = ? AND timestamp = ? AND type = ? AND level = ?",
                        (parcel_id, timestamp, type_, level)).fetchone() is not None


def add_alerts(conn, alerts):
    """alerts: dicts with ALERT_COLUMNS as keys. An alert stored before is left as it is."""
    conn.executemany(
        f"INSERT OR IGNORE INTO sensor_alerts ({', '.join(ALERT_COLUMNS)}) "
        f"VALUES ({', '.join(':' + c for c in ALERT_COLUMNS)})", alerts)


ALERT_KINDS = {"FROST": "type = 'FROST'", "HUMIDITY": "type IN ('HUMIDITY_HIGH', 'HUMIDITY_LOW')",
               "IRRIGATION": "type = 'IRRIGATION'", "SOWING": "type = 'SOWING'"}


def alerts(conn, parcel_id=None, kind="ALL", limit=1000):
    """Stored alerts, newest first. kind: FROST | HUMIDITY | IRRIGATION | ALL."""
    where, params = [], []
    if parcel_id:
        where.append("parcel_id = ?")
        params.append(parcel_id)
    if kind != "ALL":
        where.append(ALERT_KINDS[kind])
    return conn.execute(
        f"SELECT {', '.join(ALERT_COLUMNS)} FROM sensor_alerts "
        f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY timestamp DESC LIMIT ?",
        (*params, limit),
    ).fetchall()


# ---------- users, parcels and satellite results ----------

IMAGERY_SCHEMA = """
-- A user who can sign in has an email, a phone and a password. The owner of the demo parcels ("Fermier demo",
-- see imagery.DEMO_USER) has none of them and cannot sign in.
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    email          TEXT COLLATE NOCASE,          -- stored in lower case; unique (idx_users_email)
    phone          TEXT,                         -- digits with an optional leading +, e.g. +37369123456
    password_hash  TEXT,                         -- scrypt$<salt hex>$<hash hex>
    role           TEXT NOT NULL DEFAULT 'user', -- user | admin (make_admin.py)
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parcels (
    id              TEXT PRIMARY KEY,           -- cadastral number (fictive in the demo), as in sensors-alerts
    user_id         INTEGER NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    crop            TEXT,                       -- crop key of sensors-alerts: wheat, corn, sunflower, orchard, vineyard
    crop_confirmed  INTEGER NOT NULL DEFAULT 0, -- 0 = assumed from the satellite season curve
    ids_fictive     INTEGER NOT NULL DEFAULT 0, -- 1 = the cadastral number is made up for the demo
    lpis_parcel     TEXT,                       -- agricultural parcel in LPIS, once that system exists
    geometry        TEXT,                       -- GeoJSON Polygon in [lon, lat]; NULL = no satellite analysis
    note            TEXT,
    created_at      TEXT NOT NULL,
    -- A user's parcel, entered by an administrator, as written in the official document (NULL for the demo ones):
    area_ari        REAL,                       -- area in ares (1 ha = 100 ari)
    location        TEXT,                       -- village and district
    doc_type        TEXT,                       -- key of accounts.DOC_TYPES
    doc_number      TEXT,
    doc_date        TEXT,                       -- YYYY-MM-DD
    added_by        INTEGER                     -- the administrator who entered it
);
CREATE TABLE IF NOT EXISTS imagery_results (
    parcel_id        TEXT NOT NULL REFERENCES parcels(id),
    scene_date       TEXT NOT NULL,             -- the day the satellite took the picture, 2026-06-28
    scene_id         TEXT NOT NULL,             -- S2C_35TPN_20260628_0_L2A
    ndvi_median      REAL NOT NULL,
    ndmi_median      REAL,
    affected_pct     REAL NOT NULL,
    affected_sector  TEXT CHECK (affected_sector IN ('N','NE','E','SE','S','SW','W','NW','C','scattered')),
    zone_count       INTEGER NOT NULL,
    zone_lon         REAL,                      -- zone_center; NULL without a zone or when scattered
    zone_lat         REAL,
    zone_confirmed   INTEGER,                   -- 1 / 0; NULL = cannot tell
    valid_pct        REAL NOT NULL,
    prev_scene_date  TEXT,
    median_change    REAL,
    ndmi_change      REAL,
    declined_pct     REAL,
    overlay_path     TEXT NOT NULL,
    photo_path       TEXT NOT NULL,
    bounds_south     REAL NOT NULL,
    bounds_west      REAL NOT NULL,
    bounds_north     REAL NOT NULL,
    bounds_east      REAL NOT NULL,
    rules_version    TEXT NOT NULL,             -- fingerprint of the analysis code that produced the row
    received_at      TEXT NOT NULL,
    PRIMARY KEY (parcel_id, scene_date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS imagery_warnings (
    parcel_id   TEXT NOT NULL,
    scene_date  TEXT NOT NULL,
    code        TEXT NOT NULL CHECK (code IN ('low_pixel_count','low_vegetation','possible_cloud',
                                              'whole_field_drop','stale_previous')),
    text        TEXT NOT NULL,
    PRIMARY KEY (parcel_id, scene_date, code)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS imagery_skipped (
    parcel_id      TEXT NOT NULL REFERENCES parcels(id),
    scene_date     TEXT NOT NULL,
    scene_id       TEXT NOT NULL,
    valid_pct      REAL NOT NULL,
    reason         TEXT NOT NULL,
    rules_version  TEXT NOT NULL,
    received_at    TEXT NOT NULL,
    PRIMARY KEY (parcel_id, scene_date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS imagery_runs (
    started_at    TEXT PRIMARY KEY,
    finished_at   TEXT,
    status        TEXT NOT NULL,                -- running | ok | failed
    new_scenes    INTEGER,                      -- (parcel, date) pairs not in the database before the run
    newest_scene  TEXT,                         -- newest scene date in the database after the run
    error         TEXT
) WITHOUT ROWID;
"""
PARCEL_COLUMNS = ("id", "user_id", "name", "crop", "crop_confirmed", "ids_fictive", "lpis_parcel", "geometry", "note",
                  "created_at")
RESULT_COLUMNS = ("parcel_id", "scene_date", "scene_id", "ndvi_median", "ndmi_median", "affected_pct",
                  "affected_sector", "zone_count", "zone_lon", "zone_lat", "zone_confirmed", "valid_pct",
                  "prev_scene_date", "median_change", "ndmi_change", "declined_pct", "overlay_path", "photo_path",
                  "bounds_south", "bounds_west", "bounds_north", "bounds_east", "rules_version", "received_at")
SKIPPED_COLUMNS = ("parcel_id", "scene_date", "scene_id", "valid_pct", "reason", "rules_version", "received_at")
RUN_COLUMNS = ("started_at", "finished_at", "status", "new_scenes", "newest_scene", "error")
# Columns added after a table was first created: init_db adds them to an older database.
LATER_COLUMNS = {
    "sensor_readings": {"precipitation_mm": "REAL", "soil_temperature_c": "REAL", "soil_moisture_pct": "REAL"},
    "users": {"email": "TEXT", "phone": "TEXT", "password_hash": "TEXT", "role": "TEXT NOT NULL DEFAULT 'user'"},
    "parcels": {"area_ari": "REAL", "location": "TEXT", "doc_type": "TEXT", "doc_number": "TEXT", "doc_date": "TEXT",
                "added_by": "INTEGER"},
}
INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_parcels_user ON parcels(user_id);
"""


def _insert(table, columns):
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"


def upsert_user(conn, user_id, name, created_at):
    conn.execute("INSERT INTO users (id, name, created_at) VALUES (?, ?, ?) "
                 "ON CONFLICT (id) DO UPDATE SET name = excluded.name", (user_id, name, created_at))


def upsert_parcels(conn, rows):
    """rows: dicts with PARCEL_COLUMNS as keys. A parcel stored before takes the new values but keeps created_at."""
    updates = ", ".join(f"{c} = excluded.{c}" for c in PARCEL_COLUMNS if c not in ("id", "created_at"))
    conn.executemany(f"{_insert('parcels', PARCEL_COLUMNS)} ON CONFLICT (id) DO UPDATE SET {updates}", rows)


def parcels(conn):
    return conn.execute(f"SELECT {', '.join(PARCEL_COLUMNS)} FROM parcels ORDER BY id").fetchall()


def parcel(conn, parcel_id):
    return conn.execute(f"SELECT {', '.join(PARCEL_COLUMNS)} FROM parcels WHERE id = ?", (parcel_id,)).fetchone()


def import_imagery(conn, results, skipped, rules_version, received_at):
    """Stores one output of the satellite job (imagery/out/imagery.json). Every (parcel, date) in it replaces
    whatever was stored for that pair, as a result or as a skipped scene: when the rules change, a date can move
    from one list to the other. Returns how many (parcel, date) pairs were not in the database before."""
    keys = [(r["parcel_id"], r["scene_date"]) for r in results] + [(s["parcel_id"], s["scene_date"]) for s in skipped]
    known = set(map(tuple, conn.execute("SELECT parcel_id, scene_date FROM imagery_results UNION "
                                        "SELECT parcel_id, scene_date FROM imagery_skipped").fetchall()))
    for table in ("imagery_results", "imagery_warnings", "imagery_skipped"):
        conn.executemany(f"DELETE FROM {table} WHERE parcel_id = ? AND scene_date = ?", keys)
    rows = []
    for r in results:
        lon, lat = r.get("zone_center") or (None, None)
        south, west, north, east = r["overlay_bounds"]
        confirmed = r.get("zone_confirmed")
        rows.append({**{c: r.get(c) for c in RESULT_COLUMNS}, "zone_lon": lon, "zone_lat": lat,
                     "zone_confirmed": None if confirmed is None else int(confirmed), "bounds_south": south,
                     "bounds_west": west, "bounds_north": north, "bounds_east": east, "rules_version": rules_version,
                     "received_at": received_at})
    conn.executemany(_insert("imagery_results", RESULT_COLUMNS), rows)
    conn.executemany("INSERT INTO imagery_warnings (parcel_id, scene_date, code, text) VALUES (?, ?, ?, ?)",
                     [(r["parcel_id"], r["scene_date"], w["code"], w["text"]) for r in results for w in r["warnings"]])
    conn.executemany(_insert("imagery_skipped", SKIPPED_COLUMNS),
                     [{**{c: s.get(c) for c in SKIPPED_COLUMNS}, "rules_version": rules_version,
                       "received_at": received_at} for s in skipped])
    return len(set(keys) - known)


def imagery_at(conn, parcel_id, day):
    """The parcel's newest result taken on `day` or before it, or None."""
    return conn.execute(f"SELECT {', '.join(RESULT_COLUMNS)} FROM imagery_results "
                        "WHERE parcel_id = ? AND scene_date <= ? ORDER BY scene_date DESC LIMIT 1",
                        (parcel_id, day)).fetchone()


def imagery_results(conn, parcel_id, start, end):
    return conn.execute(f"SELECT {', '.join(RESULT_COLUMNS)} FROM imagery_results "
                        "WHERE parcel_id = ? AND scene_date BETWEEN ? AND ? ORDER BY scene_date",
                        (parcel_id, start, end)).fetchall()


def imagery_skipped(conn, parcel_id, after, until):
    """Scenes skipped for clouds, taken after the day `after` and on `until` or before it, oldest first."""
    return conn.execute(f"SELECT {', '.join(SKIPPED_COLUMNS)} FROM imagery_skipped "
                        "WHERE parcel_id = ? AND scene_date > ? AND scene_date <= ? ORDER BY scene_date",
                        (parcel_id, after, until)).fetchall()


def imagery_warnings(conn, parcel_id, dates):
    """{scene date: [(code, text), ...]} for the given scene dates of a parcel."""
    if not dates:
        return {}
    rows = conn.execute(f"SELECT scene_date, code, text FROM imagery_warnings WHERE parcel_id = ? "
                        f"AND scene_date IN ({', '.join('?' * len(dates))}) ORDER BY scene_date, code",
                        (parcel_id, *dates)).fetchall()
    out = {}
    for row in rows:
        out.setdefault(row["scene_date"], []).append((row["code"], row["text"]))
    return out


def start_run(conn, started_at):
    conn.execute("INSERT INTO imagery_runs (started_at, status) VALUES (?, 'running')", (started_at,))


def finish_run(conn, started_at, finished_at, status, new_scenes=None, error=None):
    newest = conn.execute("SELECT MAX(scene_date) AS d FROM (SELECT scene_date FROM imagery_results "
                          "UNION ALL SELECT scene_date FROM imagery_skipped)").fetchone()["d"]
    conn.execute("UPDATE imagery_runs SET finished_at = ?, status = ?, new_scenes = ?, newest_scene = ?, error = ? "
                 "WHERE started_at = ?", (finished_at, status, new_scenes, newest, error, started_at))


def last_run(conn, status=None):
    """The newest run of the satellite job, or the newest one with the given status; None if there is none."""
    return conn.execute(f"SELECT {', '.join(RUN_COLUMNS)} FROM imagery_runs "
                        f"{'WHERE status = ?' if status else ''} ORDER BY started_at DESC LIMIT 1",
                        (status,) if status else ()).fetchone()
