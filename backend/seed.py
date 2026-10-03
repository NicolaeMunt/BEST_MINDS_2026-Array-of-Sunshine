"""Creates the demo parcels with sample drone + field reports. IDs and names match the
sensors-alerts service config (app.parcels). Run: python seed.py  (recreates agro.db)"""
from datetime import datetime, timedelta, timezone

from app import db

STEP = 0.0015  # ~110 m between grid cells

PARCELS = [
    {
        "id": "P1", "name": "Livada Nord", "crop": "orchard", "area_ha": 8.2, "planted_at": "2019-04-10",
        "lat": 47.0612, "lon": 28.8015,
        "vision": {"ndvi_mean": 0.63, "water_stress_pct": 8, "disease": "scab", "disease_confidence": 0.71,
                   "disease_area_pct": 6, "pest_area_pct": 2, "weed_area_pct": 12, "ripeness": None},
        "ndvi": [[0.72, 0.70, 0.66, 0.68], [0.69, 0.55, 0.52, 0.66], [0.71, 0.58, 0.64, 0.70], [0.73, 0.71, 0.69, 0.67]],
        "issues": {(1, 1): "disease", (1, 2): "disease", (2, 1): "weed", (3, 3): "weed"},
        "field": {"soil_moisture_pct": 27, "air_temp_c": 17, "humidity_pct": 71,
                  "temp_max_forecast_c": 21, "rain_forecast_mm_48h": 4},
    },
    {
        "id": "P2", "name": "Via Sud", "crop": "vineyard", "area_ha": 5.6, "planted_at": "2016-05-02",
        "lat": 46.9581, "lon": 28.7804,
        "vision": {"ndvi_mean": 0.51, "water_stress_pct": 5, "disease": "powdery_mildew", "disease_confidence": 0.86,
                   "disease_area_pct": 14, "pest_area_pct": 0, "weed_area_pct": 3, "ripeness": 0.8},
        "ndvi": [[0.58, 0.55, 0.42, 0.40], [0.57, 0.49, 0.39, 0.44], [0.60, 0.56, 0.52, 0.55], [0.59, 0.58, 0.57, 0.56]],
        "issues": {(0, 2): "disease", (0, 3): "disease", (1, 2): "disease", (1, 3): "disease"},
        "field": {"soil_moisture_pct": 24, "air_temp_c": 18, "humidity_pct": 84,
                  "temp_max_forecast_c": 22, "rain_forecast_mm_48h": 12},
    },
    {
        "id": "P3", "name": "Câmpul Mare", "crop": "wheat", "area_ha": 12.5, "planted_at": "2026-03-20",
        "lat": 47.0245, "lon": 28.8322,
        "vision": {"ndvi_mean": 0.56, "water_stress_pct": 22, "disease": "rust", "disease_confidence": 0.82,
                   "disease_area_pct": 9, "pest_area_pct": 0, "weed_area_pct": 4, "ripeness": 0.55},
        "ndvi": [[0.68, 0.66, 0.61, 0.55], [0.64, 0.58, 0.41, 0.38], [0.62, 0.44, 0.36, 0.52], [0.66, 0.63, 0.57, 0.60]],
        "issues": {(1, 2): "disease", (1, 3): "disease", (2, 2): "disease", (2, 1): "water_stress", (0, 3): "water_stress"},
        "field": {"soil_moisture_pct": 18, "air_temp_c": 27, "humidity_pct": 64,
                  "temp_max_forecast_c": 31, "rain_forecast_mm_48h": 2},
    },
    {
        # The real field analysed by the satellite pipeline (imagery/parcels.geojson, parcel "demo1").
        # No drone report: its crop state comes from imagery/push.py.
        "id": "P4", "name": "Lanul de Porumb", "crop": "corn", "area_ha": 47.4, "planted_at": "2026-04-25",
        "lat": 47.4022, "lon": 28.8667,
        "boundary": [[28.860917, 47.4049], [28.8672, 47.407147], [28.872487, 47.401735], [28.868142, 47.397103]],
        "field": {"soil_moisture_pct": 33, "air_temp_c": 19, "humidity_pct": 62,
                  "temp_max_forecast_c": 24, "rain_forecast_mm_48h": 6},
    },
    {
        "id": "P5", "name": "Lotul de Floarea-soarelui", "crop": "sunflower", "area_ha": 9.8, "planted_at": "2026-04-18",
        "lat": 46.9902, "lon": 28.8611,
        "vision": {"ndvi_mean": 0.66, "water_stress_pct": 12, "disease": None, "disease_confidence": None,
                   "disease_area_pct": 0, "pest_area_pct": 6, "weed_area_pct": 5, "ripeness": 0.4},
        "ndvi": [[0.70, 0.68, 0.66, 0.69], [0.67, 0.64, 0.58, 0.65], [0.69, 0.66, 0.50, 0.63], [0.71, 0.70, 0.67, 0.68]],
        "issues": {(2, 2): "pest", (1, 2): "water_stress"},
        "field": {"soil_moisture_pct": 21, "air_temp_c": 20, "humidity_pct": 58,
                  "temp_max_forecast_c": 26, "rain_forecast_mm_48h": 3},
    },
]

if db.DB_PATH.exists():
    db.DB_PATH.unlink()
db.init_db()

now = datetime.now(timezone.utc)
with db.get_conn() as conn:
    for p in PARCELS:
        lat, lon = p["lat"], p["lon"]
        db.create_parcel(
            conn, id=p["id"], name=p["name"], crop=p["crop"], area_ha=p["area_ha"], planted_at=p["planted_at"],
            lat=lat, lon=lon,
            boundary=p.get("boundary") or [[lon - STEP / 2, lat + STEP / 2], [lon + 3.5 * STEP, lat + STEP / 2],
                                           [lon + 3.5 * STEP, lat - 3.5 * STEP], [lon - STEP / 2, lat - 3.5 * STEP]],
        )
        if "vision" in p:
            zones = [{"id": f"{r}-{c}", "lat": round(lat - r * STEP, 6), "lon": round(lon + c * STEP, 6),
                      "ndvi": p["ndvi"][r][c], "issue": p["issues"].get((r, c))}
                     for r in range(4) for c in range(4)]
            db.add_report(conn, "vision", p["id"], (now - timedelta(hours=3)).isoformat(), {**p["vision"], "zones": zones})
        db.add_report(conn, "field", p["id"], (now - timedelta(hours=1)).isoformat(), p["field"])

print(f"Seeded {', '.join(p['id'] for p in PARCELS)} into {db.DB_PATH}")
