"""SQLite storage: parcels + raw reports from the drone (vision) and field (soil/weather) modules."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parent.parent / "agro.db"))

# Each report kind maps to its own table; data is stored as JSON so the
# other modules can add fields without schema migrations.
REPORT_TABLES = {"vision": "vision_reports", "field": "field_reports"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    crop        TEXT NOT NULL,
    area_ha     REAL,
    planted_at  TEXT,
    lat         REAL,
    lon         REAL,
    boundary    TEXT,
    mode        TEXT NOT NULL DEFAULT 'NORMAL',
    replay_step INTEGER
);
CREATE TABLE IF NOT EXISTS vision_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    reported_at TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    reported_at TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sensor_readings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id        INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    timestamp        TEXT NOT NULL,
    temperature      REAL NOT NULL,
    humidity         REAL NOT NULL,
    wind_speed       REAL,
    soil_temperature REAL,
    trend            REAL,
    source           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id  INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL,
    level      TEXT NOT NULL,
    priority   TEXT NOT NULL,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    reasons    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_cooldowns (
    parcel_id  INTEGER NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    last_at    TEXT NOT NULL,
    last_level TEXT NOT NULL,
    PRIMARY KEY (parcel_id, type)
);
CREATE INDEX IF NOT EXISTS idx_readings_parcel ON sensor_readings(parcel_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_parcel ON alerts(parcel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_vision_parcel ON vision_reports(parcel_id, reported_at);
CREATE INDEX IF NOT EXISTS idx_field_parcel ON field_reports(parcel_id, reported_at);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # add columns introduced after the first version to an existing agro.db
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(parcels)")}
        if "mode" not in cols:
            conn.execute("ALTER TABLE parcels ADD COLUMN mode TEXT NOT NULL DEFAULT 'NORMAL'")
        if "replay_step" not in cols:
            conn.execute("ALTER TABLE parcels ADD COLUMN replay_step INTEGER")


def _parcel_row(row):
    parcel = dict(row)
    parcel["boundary"] = json.loads(parcel["boundary"]) if parcel["boundary"] else None
    return parcel


def create_parcel(conn, name, crop, area_ha=None, planted_at=None, lat=None, lon=None, boundary=None):
    cur = conn.execute(
        "INSERT INTO parcels (name, crop, area_ha, planted_at, lat, lon, boundary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, crop, area_ha, planted_at, lat, lon, json.dumps(boundary) if boundary else None),
    )
    return get_parcel(conn, cur.lastrowid)


def get_parcel(conn, parcel_id):
    row = conn.execute("SELECT * FROM parcels WHERE id = ?", (parcel_id,)).fetchone()
    return _parcel_row(row) if row else None


def list_parcels(conn):
    return [_parcel_row(r) for r in conn.execute("SELECT * FROM parcels ORDER BY id")]


def add_report(conn, kind, parcel_id, reported_at, data):
    conn.execute(
        f"INSERT INTO {REPORT_TABLES[kind]} (parcel_id, reported_at, data) VALUES (?, ?, ?)",
        (parcel_id, reported_at, json.dumps(data)),
    )


def latest_report(conn, kind, parcel_id):
    """Most recent report of the given kind, or None. Adds 'reported_at' to the data."""
    row = conn.execute(
        f"SELECT reported_at, data FROM {REPORT_TABLES[kind]} WHERE parcel_id = ? "
        "ORDER BY reported_at DESC, id DESC LIMIT 1",
        (parcel_id,),
    ).fetchone()
    if not row:
        return None
    return {**json.loads(row["data"]), "reported_at": row["reported_at"]}


def set_mode(conn, parcel_id, mode, replay_step=None):
    conn.execute("UPDATE parcels SET mode = ?, replay_step = ? WHERE id = ?", (mode, replay_step, parcel_id))


# ---------- sensors ----------

READING_COLUMNS = ("timestamp", "temperature", "humidity", "wind_speed", "soil_temperature", "trend", "source")


def add_reading(conn, parcel_id, reading):
    conn.execute(
        f"INSERT INTO sensor_readings (parcel_id, {', '.join(READING_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (parcel_id, *(reading.get(c) for c in READING_COLUMNS)),
    )


def latest_reading(conn, parcel_id):
    row = conn.execute(
        "SELECT * FROM sensor_readings WHERE parcel_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1", (parcel_id,)
    ).fetchone()
    return dict(row) if row else None


def readings_since(conn, parcel_id, since_iso, source=None):
    query = "SELECT * FROM sensor_readings WHERE parcel_id = ? AND timestamp >= ?"
    params = [parcel_id, since_iso]
    if source:
        query += " AND source = ?"
        params.append(source)
    return [dict(r) for r in conn.execute(query + " ORDER BY timestamp, id", params)]


# ---------- alerts ----------

def _alert_row(row):
    alert = dict(row)
    alert["reasons"] = json.loads(alert["reasons"])
    return alert


def add_alert(conn, parcel_id, created_at, type_, level, priority, title, message, reasons):
    cur = conn.execute(
        "INSERT INTO alerts (parcel_id, created_at, type, level, priority, title, message, reasons) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (parcel_id, created_at, type_, level, priority, title, message, json.dumps(reasons, ensure_ascii=False)),
    )
    conn.execute(
        "INSERT INTO alert_cooldowns (parcel_id, type, last_at, last_level) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(parcel_id, type) DO UPDATE SET last_at = excluded.last_at, last_level = excluded.last_level",
        (parcel_id, type_, created_at, level),
    )
    return cur.lastrowid


def get_cooldown(conn, parcel_id, type_):
    row = conn.execute(
        "SELECT last_at, last_level FROM alert_cooldowns WHERE parcel_id = ? AND type = ?", (parcel_id, type_)
    ).fetchone()
    return dict(row) if row else None


def list_alerts(conn, parcel_id=None, limit=50):
    if parcel_id is None:
        rows = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
    else:
        rows = conn.execute("SELECT * FROM alerts WHERE parcel_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                            (parcel_id, limit))
    return [_alert_row(r) for r in rows]


def reset_demo(conn):
    """All parcels back to NORMAL, alerts and cooldowns cleared."""
    conn.execute("UPDATE parcels SET mode = 'NORMAL', replay_step = NULL")
    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM alert_cooldowns")
