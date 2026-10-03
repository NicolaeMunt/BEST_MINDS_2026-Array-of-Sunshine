"""SQLite storage: sensor readings and alerts with their timestamps, copied from the sensors-alerts
service (see collector.py). Parcels and the drone, soil and satellite results are not stored here for now."""
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
