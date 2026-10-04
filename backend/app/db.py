"""SQLite storage: sensor readings and alerts with their timestamps, copied from the sensors-alerts
service (see collector.py), and the accounts with their fields, entered by an administrator from the
official land documents (see accounts.py).
The drone, soil and satellite results are not stored here for now."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).resolve().parent.parent / "sensors.db"))

# Timestamps are text in one fixed UTC format (see ts_text), so comparing the text compares the time.
SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    parcel_id     TEXT NOT NULL,   -- sensor location, same IDs as the sensors-alerts service (P1, P2, ...)
    timestamp     TEXT NOT NULL,   -- when the sensor measured
    temperature_c REAL NOT NULL,
    humidity_pct  REAL NOT NULL,
    received_at   TEXT NOT NULL,   -- when this API stored it; differs from timestamp for a replayed night
    PRIMARY KEY (parcel_id, timestamp)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_readings_received ON sensor_readings(parcel_id, received_at);
CREATE TABLE IF NOT EXISTS sensor_alerts (
    parcel_id     TEXT NOT NULL,
    timestamp     TEXT NOT NULL,   -- when the alert was sent
    type          TEXT NOT NULL,   -- FROST | HUMIDITY_HIGH | HUMIDITY_LOW
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
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone         TEXT NOT NULL,   -- digits with an optional leading +, e.g. +37369123456
    password_hash TEXT NOT NULL,   -- scrypt$<salt hex>$<hash hex>
    role          TEXT NOT NULL DEFAULT 'user',   -- user | admin (make_admin.py)
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,   -- SHA-256 of the token the browser holds; the token itself is not stored
    user_id       INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
) WITHOUT ROWID;
-- A user's field, entered by an administrator from an official document. Its parcel ID in sensors-alerts is
-- 'F' || num (F1, F2, ...); AUTOINCREMENT never reuses a number, so a new field never inherits the readings
-- of a deleted one.
CREATE TABLE IF NOT EXISTS fields (
    num              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,   -- the owner
    name             TEXT NOT NULL,
    crop             TEXT NOT NULL,      -- crop key, as in sensors-alerts app.crops
    area_ari         REAL,               -- area written in the document, in ares (1 ha = 100 ari)
    cadastral_number TEXT,               -- e.g. 0100415.123, one field per number
    location         TEXT,               -- village and district
    doc_type         TEXT,               -- key of accounts.DOC_TYPES
    doc_number       TEXT,
    doc_date         TEXT,               -- YYYY-MM-DD
    added_by         INTEGER,            -- the administrator who entered it
    created_at       TEXT NOT NULL
);
"""
# Columns added after a table was first created: init_db adds them to an older database.
LATER_COLUMNS = {
    "users": {"role": "TEXT NOT NULL DEFAULT 'user'"},
    "fields": {"area_ari": "REAL", "cadastral_number": "TEXT", "location": "TEXT", "doc_type": "TEXT",
               "doc_number": "TEXT", "doc_date": "TEXT", "added_by": "INTEGER"},
}
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fields_user ON fields(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fields_cadastral ON fields(cadastral_number);
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
        for table, columns in LATER_COLUMNS.items():
            have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        conn.executescript(INDEXES)


def add_readings(conn, parcel_id, readings, received_at):
    """readings: (timestamp text, temperature, humidity). A reading stored before is replaced, so a night
    replayed twice is kept once and counts as the newest data again."""
    conn.executemany(
        "INSERT INTO sensor_readings (parcel_id, timestamp, temperature_c, humidity_pct, received_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (parcel_id, timestamp) DO UPDATE SET "
        "temperature_c = excluded.temperature_c, humidity_pct = excluded.humidity_pct, received_at = excluded.received_at",
        [(parcel_id, ts, temperature, humidity, received_at) for ts, temperature, humidity in readings],
    )


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


def add_alerts(conn, alerts):
    """alerts: dicts with ALERT_COLUMNS as keys. An alert stored before is left as it is."""
    conn.executemany(
        f"INSERT OR IGNORE INTO sensor_alerts ({', '.join(ALERT_COLUMNS)}) "
        f"VALUES ({', '.join(':' + c for c in ALERT_COLUMNS)})", alerts)


def alerts(conn, parcel_id=None, kind="ALL", limit=1000):
    """Stored alerts, newest first. kind: FROST | HUMIDITY | ALL."""
    where, params = [], []
    if parcel_id:
        where.append("parcel_id = ?")
        params.append(parcel_id)
    if kind != "ALL":
        where.append("type = 'FROST'" if kind == "FROST" else "type <> 'FROST'")
    return conn.execute(
        f"SELECT {', '.join(ALERT_COLUMNS)} FROM sensor_alerts "
        f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY timestamp DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
