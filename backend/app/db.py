"""SQLite storage: parcels + raw reports from the drone (vision), field (soil/weather) and satellite
(imagery) modules.
Sensor readings and frost alerts live in the sensors-alerts service (see sensors_client.py)."""
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parent.parent / "agro.db"))

# Each report kind maps to its own table; data is stored as JSON so the
# other modules can add fields without schema migrations.
REPORT_TABLES = {"vision": "vision_reports", "field": "field_reports", "imagery": "imagery_reports"}

# Parcel IDs are strings ("P1", "P2", ...) and must match the sensors-alerts service config.
SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    crop        TEXT NOT NULL,
    area_ha     REAL,
    planted_at  TEXT,
    lat         REAL,
    lon         REAL,
    boundary    TEXT
);
CREATE TABLE IF NOT EXISTS vision_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   TEXT NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    reported_at TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   TEXT NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    reported_at TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imagery_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   TEXT NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    reported_at TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_imagery_parcel ON imagery_reports(parcel_id, reported_at);
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
        id_type = next(r["type"] for r in conn.execute("PRAGMA table_info(parcels)") if r["name"] == "id")
        if id_type.upper() != "TEXT":
            raise RuntimeError(f"{DB_PATH} has the old schema (numeric parcel IDs). Run: python seed.py")


def _parcel_row(row):
    parcel = dict(row)
    parcel["boundary"] = json.loads(parcel["boundary"]) if parcel["boundary"] else None
    return parcel


def _next_id(conn):
    numbers = [int(m.group(1)) for (pid,) in conn.execute("SELECT id FROM parcels")
               if (m := re.fullmatch(r"P(\d+)", pid))]
    return f"P{max(numbers, default=0) + 1}"


def create_parcel(conn, name, crop, area_ha=None, planted_at=None, lat=None, lon=None, boundary=None, id=None):
    parcel_id = id or _next_id(conn)
    conn.execute(
        "INSERT INTO parcels (id, name, crop, area_ha, planted_at, lat, lon, boundary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (parcel_id, name, crop, area_ha, planted_at, lat, lon, json.dumps(boundary) if boundary else None),
    )
    return get_parcel(conn, parcel_id)


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
