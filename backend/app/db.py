"""SQLite storage: sensor readings with their timestamps, copied from the sensors-alerts service
(see collector.py). Parcels and the drone, soil and satellite results are not stored here for now."""
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
"""


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
