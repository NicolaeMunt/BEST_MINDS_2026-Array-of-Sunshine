"""Soil water balance of a parcel, from its stored sensor readings (FAO-56, single crop coefficient): how much
water the crop has taken from the soil since 1 May, how much the rain gave back, and when it is time to water.

Each day: the crop uses Kc x ET0 (ET0 from the day's lowest and highest temperature, Hargreaves), the rain
refills the soil, and the deficit can grow up to all the water the roots reach (TAW). The crop starts to
suffer once the deficit passes the readily available water (RAW = p x TAW): then it should be watered.
The farmer's own watering is not known, so the balance assumes a field that is not irrigated."""
import json
from datetime import datetime, time, timedelta

from . import crops, db

DEFAULT_LATITUDE = 47.4  # Orhei; used when the parcel has no polygon in the database
ADVICE_TIME = time(8, 0)  # the irrigation advice is dated 08:00 local time on the day it applies to


def latitude(conn, parcel_id):
    row = db.parcel(conn, parcel_id)
    if not row:
        return DEFAULT_LATITUDE
    ring = json.loads(row["geometry"])["coordinates"][0]
    return sum(lat for _, lat in ring) / len(ring)


def season(conn, parcel_id, crop_key, day):
    """The daily balance from 1 May to `day`, or None for a crop without water parameters (or before May)."""
    cfg = crops.crop(crop_key)
    if not cfg or not cfg.get("water") or day < crops.season_start(day):
        return None
    taw = crops.soil_water_mm_per_m() * cfg["water"]["root-depth-m"]
    raw = cfg["water"]["depletion-fraction"] * taw
    start = crops.season_start(day)
    lat = latitude(conn, parcel_id)
    weather = {row["day"]: row for row in db.daily_weather(conn, parcel_id, start, day)}
    deficit, days = 0.0, []
    d = start
    while d <= day:
        ph = crops.phase(cfg, d)
        kc = ph.get("kc")
        w = weather.get(d.isoformat())
        rain = w["rain_mm"] if w else 0.0
        et0 = crops.et0_hargreaves(d, lat, w["t_min"], w["t_max"]) if w else 0.0
        etc = kc * et0 if kc else 0.0
        deficit = min(taw, max(0.0, deficit - rain + etc))
        days.append({"date": d, "phase": ph.get("name"), "kc": kc, "et0_mm": round(et0, 1), "etc_mm": round(etc, 1),
                     "rain_mm": round(rain, 1), "deficit_mm": round(deficit, 1), "measured": w is not None,
                     "t_max": w["t_max"] if w else None, "hum_min": w["hum_min"] if w else None})
        d += timedelta(days=1)
    return {"total_available_mm": round(taw), "readily_available_mm": round(raw), "days": days}


def _needs_water(s, d):
    return d["kc"] is not None and d["deficit_mm"] >= s["readily_available_mm"]


def status(conn, parcel_id, crop_key, day, with_days=False):
    """The balance on `day`: deficit, the limits, whether to water and how much; None without a balance."""
    s = season(conn, parcel_id, crop_key, day)
    if not s:
        return None
    last = s["days"][-1]
    irrigate = _needs_water(s, last)
    out = {"date": day, "phase": last["phase"], "has_crop": last["kc"] is not None, "deficit_mm": last["deficit_mm"],
           "readily_available_mm": s["readily_available_mm"], "total_available_mm": s["total_available_mm"],
           "irrigate": irrigate,
           # Enough to bring the deficit back under the stress limit; filling the soil would take the whole deficit.
           "amount_mm": round(last["deficit_mm"] - s["readily_available_mm"], 1) if irrigate else 0.0}
    if with_days:
        out["days"] = [{k: v for k, v in d.items() if k not in ("t_max", "hum_min")} for d in s["days"]]
    return out


def alerts(conn, parcel, day, dew_point):
    """Irrigation alerts of the season up to `day`, newest first: WARNING on the day the deficit passes the
    readily available water, OK when the rain brings it back below. parcel: {'id', 'name', 'crop'}."""
    s = season(conn, parcel["id"], parcel["crop"], day)
    if not s:
        return []
    cfg = crops.crop(parcel["crop"])
    title = f"{parcel['name']} ({cfg['name']})"
    out, on = [], False
    for d in s["days"]:
        if d["kc"] is None:  # no crop (not sown yet, harvested): an open episode just ends, nothing to tell
            on = False
            continue
        needs = _needs_water(s, d)
        if needs == on:
            continue
        on = needs
        stamp = datetime.combine(d["date"], ADVICE_TIME, crops.LOCAL)
        if needs:
            text = (f"💧 E timpul să udați – {title}\nÎn sol lipsesc {d['deficit_mm']:.0f} mm de apă; cultura "
                    f"suferă când lipsesc peste {s['readily_available_mm']} mm.\nUdați dacă se poate: fiecare 10 mm "
                    f"înseamnă 100 m³ la hectar.")
        else:
            text = f"✅ Ploaia a refăcut apa din sol – {title}\nÎn sol mai lipsesc {d['deficit_mm']:.0f} mm de apă."
        t_max = d["t_max"] if d["t_max"] is not None else 0.0
        hum = d["hum_min"] if d["hum_min"] is not None else 0.0
        out.append({"parcelId": parcel["id"], "parcelName": parcel["name"], "crop": parcel["crop"], "type": "IRRIGATION",
                    "level": "WARNING" if needs else "OK", "temperatureC": round(t_max, 1), "humidityPct": round(hum),
                    "dewPointC": dew_point(t_max, hum) if d["t_max"] is not None else 0.0,
                    "timestamp": db.ts_text(stamp), "message": text, "deficitMm": d["deficit_mm"]})
    return out[::-1]
