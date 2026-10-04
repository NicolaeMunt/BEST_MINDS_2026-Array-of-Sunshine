"""When a parcel should be watered and how much. Two ways, the first that has data wins:

- the soil probe: the soil moisture at ~20 cm against the soil's limits (FAO-56). The crop suffers once the
  moisture falls below field capacity minus p x (field capacity - wilting point). A watering shows up as a rise
  in moisture without rain, so the advice follows what the farmer did.
- the soil water balance from the temperature and the rain (FAO-56, single crop coefficient): each day the crop
  uses Kc x ET0 (ET0 from the day's lowest and highest temperature, Hargreaves), the rain refills the soil, and
  the deficit can grow up to all the water the roots reach (TAW). The crop starts to suffer once the deficit
  passes the readily available water (RAW = p x TAW). It cannot see a watering: the field is taken as unwatered.
"""
import json
from datetime import date, datetime, time, timedelta

from . import crops, db

DEFAULT_LATITUDE = 47.4  # Orhei; used when the parcel has no polygon in the database
ADVICE_TIME = time(8, 0)  # balance advice is dated 08:00 local time on the day it applies to
SENSOR_FRESH = timedelta(days=2)  # older soil readings than this: back to the balance
SOIL_HYSTERESIS_PCT = 2.0  # out of stress only this far above the threshold, so a reading at the limit does not flicker
WATERING_WINDOW_H = 6  # a watering raises the moisture within this many hours
# Rain reaches the probe at ~20 cm with a delay: a rise counts as a watering only with (almost) no rain in the
# last two days.
RAIN_LOOKBACK_H = 48
WATERING_MAX_RAIN_MM = 2
SHOWN_WATERINGS = timedelta(days=14)
SOIL_SEASON_START = (4, 1)  # soil readings are looked at from 1 April (sowing); the balance starts on 1 May


def latitude(conn, parcel_id):
    row = db.parcel(conn, parcel_id)
    if not row or not row["geometry"]:  # a user's parcel has no polygon until it gets one
        return DEFAULT_LATITUDE
    ring = json.loads(row["geometry"])["coordinates"][0]
    return sum(lat for _, lat in ring) / len(ring)


def _limits(cfg):
    """Soil limits for the crop: total and readily available water in mm, and the moisture threshold in %."""
    fc, wp = crops.soil()
    root_mm = cfg["water"]["root-depth-m"] * 1000
    p = cfg["water"]["depletion-fraction"]
    return {"fc": fc, "wp": wp, "root_mm": root_mm, "taw": (fc - wp) / 100 * root_mm,
            "raw": p * (fc - wp) / 100 * root_mm, "threshold": fc - p * (fc - wp)}


def _day_end(day):
    return datetime.combine(day + timedelta(days=1), time(0), crops.LOCAL)


def _soil_series(conn, parcel_id, cfg, day):
    """Soil readings of the season up to the end of `day`, oldest first: [(time, local date, moisture, temperature,
    rain)]. Hourly means, except per minute in the last WATERING_WINDOW_H hours, so a watering (or a dry spell
    ending) shows at once instead of being averaged with the hour."""
    start = datetime.combine(date(day.year, *SOIL_SEASON_START), time(0), crops.LOCAL)
    end = _day_end(day)
    latest = db.latest_soil_time(conn, parcel_id, end)
    split = end
    if latest:
        split = min(end, datetime.fromisoformat(latest.replace("Z", "+00:00")).replace(minute=0, second=0, microsecond=0)
                    - timedelta(hours=WATERING_WINDOW_H))
    out = []
    for r in list(db.soil_hours(conn, parcel_id, start, split)) + list(db.soil_hours(conn, parcel_id, split, end, True)):
        hour = datetime.fromisoformat(r["hour"].replace("Z", "+00:00"))
        out.append((hour, hour.astimezone(crops.LOCAL).date(), r["soil_m"], r["soil_t"], r["rain_mm"]))
    return out


def rain_before(series, i):
    """Rain in the RAIN_LOOKBACK_H hours up to and including series[i]."""
    hour, total = series[i][0], 0.0
    for s in reversed(series[:i + 1]):
        if hour - s[0] >= timedelta(hours=RAIN_LOOKBACK_H):
            break
        total += s[4]
    return total


def waterings(series, rise_pct):
    """Hours at which the soil moisture rose at least rise_pct within WATERING_WINDOW_H hours with less than
    WATERING_MAX_RAIN_MM of rain in the last RAIN_LOOKBACK_H hours: a watering.
    [(hour, moisture before, moisture after)]; one per 6 hours."""
    found, first = [], 0
    for i, (hour, _, moisture, _, _) in enumerate(series):
        while hour - series[first][0] > timedelta(hours=WATERING_WINDOW_H):
            first += 1
        if first >= i:
            continue
        low = min(s[2] for s in series[first:i])
        if moisture - low >= rise_pct and rain_before(series, i) < WATERING_MAX_RAIN_MM:
            if found and hour - found[-1][0] <= timedelta(hours=WATERING_WINDOW_H):
                found[-1] = (found[-1][0], found[-1][1], round(moisture, 1))
            else:
                found.append((hour, round(low, 1), round(moisture, 1)))
    return found


def season(conn, parcel_id, crop_key, day):
    """The daily balance from 1 May to `day`, or None for a crop without water parameters (or before May)."""
    cfg = crops.crop(crop_key)
    if not cfg or not cfg.get("water") or day < crops.season_start(day):
        return None
    lim = _limits(cfg)
    taw, raw = lim["taw"], lim["raw"]
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
    """Whether to water on `day` and how much, from the soil probe if it reported in the last two days, else from
    the balance; None for a crop without water parameters."""
    cfg = crops.crop(crop_key)
    if not cfg or not cfg.get("water"):
        return None
    s = season(conn, parcel_id, crop_key, day)
    series = _soil_series(conn, parcel_id, cfg, day)
    if series and _day_end(day) - series[-1][0] <= SENSOR_FRESH:
        lim = _limits(cfg)
        hour, _, moisture, _, _ = series[-1]
        ph = crops.phase(cfg, day)
        has_crop = ph.get("kc") is not None
        irrigate = has_crop and moisture <= lim["threshold"]
        recent = [w for w in waterings(series, crops.watering_rise_pct()) if w[0] >= _day_end(day) - SHOWN_WATERINGS]
        out = {"date": day, "phase": ph.get("name"), "has_crop": has_crop, "source": "sensor",
               "soil_moisture_pct": round(moisture, 1), "threshold_pct": round(lim["threshold"], 1),
               "field_capacity_pct": lim["fc"],
               "deficit_mm": round(max(0.0, lim["fc"] - moisture) / 100 * lim["root_mm"], 1),
               "readily_available_mm": round(lim["raw"]), "total_available_mm": round(lim["taw"]),
               "irrigate": irrigate,
               "amount_mm": round((lim["threshold"] - moisture) / 100 * lim["root_mm"], 1) if irrigate else 0.0,
               "waterings": [{"time": h, "from_pct": a, "to_pct": b} for h, a, b in reversed(recent)]}
    elif s:
        last = s["days"][-1]
        irrigate = _needs_water(s, last)
        out = {"date": day, "phase": last["phase"], "has_crop": last["kc"] is not None, "source": "balance",
               "deficit_mm": last["deficit_mm"], "readily_available_mm": s["readily_available_mm"],
               "total_available_mm": s["total_available_mm"], "irrigate": irrigate,
               # Enough to bring the deficit back under the stress limit; filling the soil would take the whole deficit.
               "amount_mm": round(last["deficit_mm"] - s["readily_available_mm"], 1) if irrigate else 0.0,
               "waterings": []}
    else:
        return None
    if with_days and s:
        out["days"] = [{k: v for k, v in d.items() if k not in ("t_max", "hum_min")} for d in s["days"]]
    return out


def _alert(parcel, needs, stamp, text, t_max, hum, dew_point, deficit):
    return {"parcelId": parcel["id"], "parcelName": parcel["name"], "crop": parcel["crop"], "type": "IRRIGATION",
            "level": "WARNING" if needs else "OK", "temperatureC": round(t_max or 0.0, 1), "humidityPct": round(hum or 0),
            "dewPointC": dew_point(t_max, hum) if t_max is not None and hum is not None else 0.0,
            "timestamp": db.ts_text(stamp), "message": text, "deficitMm": deficit}


def alerts(conn, parcel, day, dew_point):
    """Watering alerts of the season up to `day`, newest first: WARNING when the crop starts to suffer for water,
    OK when rain or a watering brings the soil back. From the soil probe where it reported, else from the balance.
    parcel: {'id', 'name', 'crop'}."""
    cfg = crops.crop(parcel["crop"])
    if not cfg or not cfg.get("water"):
        return []
    title = f"{parcel['name']} ({cfg['name']})"
    series = _soil_series(conn, parcel["id"], cfg, day)
    if series:
        return _sensor_alerts(parcel, cfg, title, series, dew_point)
    s = season(conn, parcel["id"], parcel["crop"], day)
    if not s:
        return []
    out, on = [], False
    for d in s["days"]:
        if d["kc"] is None:  # no crop (not sown yet, harvested): an open episode just ends, nothing to tell
            on = False
            continue
        needs = _needs_water(s, d)
        if needs == on:
            continue
        on = needs
        if needs:
            text = (f"💧 E timpul să udați – {title}\nÎn sol lipsesc {d['deficit_mm']:.0f} mm de apă; cultura "
                    f"suferă când lipsesc peste {s['readily_available_mm']} mm.\nUdați dacă se poate: fiecare 10 mm "
                    f"înseamnă 100 m³ la hectar.")
        else:
            text = f"✅ Ploaia a refăcut apa din sol – {title}\nÎn sol mai lipsesc {d['deficit_mm']:.0f} mm de apă."
        out.append(_alert(parcel, needs, datetime.combine(d["date"], ADVICE_TIME, crops.LOCAL), text, d["t_max"],
                          d["hum_min"], dew_point, d["deficit_mm"]))
    return out[::-1]


def _sensor_alerts(parcel, cfg, title, series, dew_point):
    lim = _limits(cfg)
    out, on = [], False
    for i, (hour, local_day, moisture, _, _) in enumerate(series):
        if crops.phase(cfg, local_day).get("kc") is None:
            on = False
            continue
        needs = moisture <= lim["threshold"] if not on else moisture <= lim["threshold"] + SOIL_HYSTERESIS_PCT
        if needs == on:
            continue
        on = needs
        deficit = round(max(0.0, lim["fc"] - moisture) / 100 * lim["root_mm"], 1)
        if needs:
            amount = (lim["threshold"] - moisture) / 100 * lim["root_mm"]
            text = (f"💧 E timpul să udați – {title}\nUmiditatea solului a scăzut la {moisture:.1f}%; cultura suferă "
                    f"sub {lim['threshold']:.1f}%.\nCa să iasă din stres: cel puțin {max(amount, 1):.0f} mm "
                    f"(≈ {max(amount, 1) * 10:.0f} m³/ha).")
        else:
            what = "Ploaia a refăcut apa din sol" if rain_before(series, i) >= WATERING_MAX_RAIN_MM else "S-a udat"
            text = f"✅ {what} – {title}\nUmiditatea solului: {moisture:.1f}% (cultura suferă sub {lim['threshold']:.1f}%)."
        out.append(_alert(parcel, needs, hour, text, None, None, dew_point, deficit))
    return out[::-1]
