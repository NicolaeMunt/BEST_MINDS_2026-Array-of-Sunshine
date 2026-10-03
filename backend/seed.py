"""Creates one demo wheat parcel with sample drone + field reports and an hour of sensor history,
so the frontend has data before the other modules are integrated. Run: python seed.py  (recreates agro.db)"""
from datetime import datetime, timedelta, timezone

from app import db, sensors, simulator

LAT, LON = 47.0245, 28.8322
STEP = 0.0015  # ~110 m between grid cells

if db.DB_PATH.exists():
    db.DB_PATH.unlink()
db.init_db()

now = datetime.now(timezone.utc)
ndvi_grid = [
    [0.68, 0.66, 0.61, 0.55],
    [0.64, 0.58, 0.41, 0.38],
    [0.62, 0.44, 0.36, 0.52],
    [0.66, 0.63, 0.57, 0.60],
]
issues = {(1, 2): "disease", (1, 3): "disease", (2, 2): "disease", (2, 1): "water_stress", (0, 3): "water_stress"}
zones = [
    {"id": f"{r}-{c}", "lat": round(LAT - r * STEP, 6), "lon": round(LON + c * STEP, 6),
     "ndvi": ndvi_grid[r][c], "issue": issues.get((r, c))}
    for r in range(4) for c in range(4)
]

with db.get_conn() as conn:
    parcel = db.create_parcel(
        conn, name="Terenul meu", crop="wheat", area_ha=12.5, planted_at="2026-03-20", lat=LAT, lon=LON,
        boundary=[[LON - STEP / 2, LAT + STEP / 2], [LON + 3.5 * STEP, LAT + STEP / 2],
                  [LON + 3.5 * STEP, LAT - 3.5 * STEP], [LON - STEP / 2, LAT - 3.5 * STEP]],
    )
    db.add_report(conn, "vision", parcel["id"], (now - timedelta(hours=3)).isoformat(), {
        "ndvi_mean": 0.56, "water_stress_pct": 22, "disease": "rust", "disease_confidence": 0.82,
        "disease_area_pct": 9, "pest_area_pct": 0, "weed_area_pct": 4, "ripeness": 0.55, "zones": zones,
    })
    db.add_report(conn, "field", parcel["id"], (now - timedelta(hours=1)).isoformat(), {
        "soil_moisture_pct": 18, "air_temp_c": 27, "humidity_pct": 64,
        "temp_max_forecast_c": 31, "rain_forecast_mm_48h": 2,
    })
    last = None
    for i in range(120, 0, -1):  # one hour of NORMAL readings, every 30 s
        last = {**simulator.normal_reading(last), "timestamp": (now - timedelta(seconds=30 * i)).isoformat()}
        sensors.record_reading(conn, parcel["id"], last, compute_trend=False)

print(f"Seeded parcel #{parcel['id']} into {db.DB_PATH}")
