"""The crop rules of sensors-alerts (app.crops in its application.yml), read here so the API and the sample
history use the same calendar and thresholds: each crop's phase on a day, its frost thresholds, the damp-air
disease rule, the dry-air window and the water-balance parameters. The rules themselves run in sensors-alerts;
history_alerts() repeats them for the hourly sample season, the same way (see AlertService there)."""
import math
import os
from datetime import date, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_FILE = Path(os.getenv("CROPS_FILE", Path(__file__).resolve().parents[2] / "sensors-alerts" / "src" / "main"
                             / "resources" / "application.yml"))
LOCAL = timezone(timedelta(hours=3))  # Europe/Chisinau in summer; the season runs May-October
FROST_CLEAR_MARGIN_C = 1  # app.frost.all-clear-margin-c


@lru_cache(maxsize=1)
def config():
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["app"]


def crop(key):
    """The crop's settings with kebab-case keys as in the YAML, or None for an unknown crop."""
    return config()["crops"].get((key or "").strip().lower())


def humidity_settings():
    return config().get("humidity", {})


def soil():
    """Field capacity and wilting point of the parcels' soil, % of the soil volume."""
    w = config().get("water", {})
    return float(w.get("field-capacity-pct", 27)), float(w.get("wilting-point-pct", 10))


def soil_water_mm_per_m():
    """Water the soil holds for plants per metre of roots: 1% of the volume over 1 m is 10 mm."""
    fc, wp = soil()
    return (fc - wp) * 10


def watering_rise_pct():
    return float(config().get("water", {}).get("watering-rise-pct", 3))


def _month_day(day):
    return f"{day.month:02d}-{day.day:02d}"


def phase(crop_cfg, day):
    """The phase on that day: before the first phase starts, last year's last phase still runs."""
    phases = (crop_cfg or {}).get("phases") or []
    if not phases:
        return {}
    md = _month_day(day)
    current = phases[-1]
    for p in phases:
        if str(p["from"]) <= md:
            current = p
    return current


def within(window, day):
    return bool(window) and str(window["from"]) <= _month_day(day) <= str(window["to"])


def frost_harms(ph):
    return ph.get("frost-warning-c") is not None and ph.get("frost-critical-c") is not None


def phase_out(crop_key, day):
    """What the API shows about the crop on that day: phase name, satellite season, frost thresholds, watched disease."""
    cfg = crop(crop_key)
    if not cfg:
        return None
    ph = phase(cfg, day)
    disease = cfg.get("disease")
    return {"phase": ph.get("name"), "season": ph.get("season", "growing"),
            "frost_warning_c": ph.get("frost-warning-c"), "frost_critical_c": ph.get("frost-critical-c"),
            "disease": disease["name"] if disease and within(disease, day) else None}


# ---------- the sensors-alerts rules over an hourly series (sample history) ----------

def _num(v):
    return f"{v:.1f}"


def _frost_text(title, cfg, ph, temp, hum, dew, level):
    advice = ph.get("frost-advice") or cfg.get("frost-advice", "")
    if level == "CRITICAL":
        return (f"❄️ ÎNGHEȚ – {title}\nTemperatura: {_num(temp)} °C (prag critic în faza „{ph['name']}”: "
                f"{_num(ph['frost-critical-c'])} °C)\n{advice}")
    return (f"⚠️ Risc de îngheț – {title}\nTemperatura: {_num(temp)} °C (faza „{ph['name']}”, prag critic "
            f"{_num(ph['frost-critical-c'])} °C)\nUmiditate: {hum:.0f}% · Punct de rouă: {_num(dew)} °C\n"
            f"{advice}")


def history_alerts(parcel, readings, dew_point):
    """The alerts sensors-alerts would have sent for hourly readings [(aware datetime, temp, humidity), ...]
    of one parcel ({'id', 'name', 'crop'}): the same episodes as its AlertService, without the 'falling fast'
    frost warning and the cooldown, which need finer readings than one per hour.
    Returns [parcel_id, name, crop, type, level, datetime, temp, hum, dew point, message]."""
    cfg = crop(parcel["crop"])
    if not cfg:
        return []
    hum_cfg = humidity_settings()
    dry_max, dry_min_t = hum_cfg.get("dry-max-pct", 30), hum_cfg.get("dry-min-temp-c", 25)
    hold = timedelta(hours=hum_cfg.get("hold-hours", 24))
    disease, dry = cfg.get("disease"), cfg.get("dry")
    title = f"{parcel['name']} ({cfg['name']})"
    alerts, frost, humidity = [], "OK", None
    by_hour = {ts.replace(minute=0, second=0, microsecond=0): (temp, hum) for ts, temp, hum in readings}
    # (hour, damp hours, within hours) when a disease condition was last met; when the air was last dry and hot.
    last_damp, last_dry = None, None

    def add(ts, temp, hum, kind, level, text):
        alerts.append([parcel["id"], parcel["name"], parcel["crop"], kind, level, ts, temp, hum, dew_point(temp, hum), text])

    for ts, temp, hum in readings:
        day = ts.astimezone(LOCAL).date()
        ph = phase(cfg, day)
        dew = dew_point(temp, hum)

        # Frost: the phase's thresholds on that day; none when frost does no harm then.
        if frost_harms(ph):
            level = "CRITICAL" if temp <= ph["frost-critical-c"] else "WARNING" if temp <= ph["frost-warning-c"] else "OK"
        else:
            level = "OK"
        if (level, frost) in {("WARNING", "OK"), ("CRITICAL", "OK"), ("CRITICAL", "WARNING")}:
            frost = level
            add(ts, temp, hum, "FROST", level, _frost_text(title, cfg, ph, temp, hum, dew, level))
        elif level == "OK" and frost != "OK" and (not frost_harms(ph) or temp > ph["frost-warning-c"] + FROST_CLEAR_MARGIN_C):
            frost = "OK"
            add(ts, temp, hum, "FROST", "OK", f"✅ Pericol trecut – {title}\nTemperatura: {_num(temp)} °C")

        # Damp air: enough damp hours for one of the disease's conditions, inside its window. The risk holds for
        # hold-hours after the conditions were last met.
        state, damp_hours, within_hours = None, 0, 0
        hour = ts.replace(minute=0, second=0, microsecond=0)
        if disease:
            for c in disease["conditions"]:
                damp = 0
                for i in range(c["within-hours"]):
                    h = by_hour.get(hour - timedelta(hours=i))
                    if h and h[1] >= disease["min-humidity-pct"] and c["min-temp-c"] <= h[0] <= c["max-temp-c"]:
                        damp += 1
                if damp >= c["hours"]:
                    last_damp = (hour, damp, c["within-hours"])
                    break
            if within(disease, day) and last_damp and hour - last_damp[0] <= hold:
                state, damp_hours, within_hours = "HUMIDITY_HIGH", last_damp[1], last_damp[2]
        # Dry, hot air inside the dry window, holding the same way.
        if hum <= dry_max and temp >= dry_min_t:
            last_dry = ts
        if state is None and dry and within(dry, day) and last_dry is not None and ts - last_dry <= hold:
            state = "HUMIDITY_LOW"

        if humidity and humidity != state:
            what = f"Riscul de {disease['name']} a trecut" if humidity == "HUMIDITY_HIGH" else "A trecut perioada de aer fierbinte și uscat"
            add(ts, temp, hum, humidity, "OK", f"✅ {what} – {title}\nUmiditate: {hum:.0f}% · Temperatura: {_num(temp)} °C")
            humidity = None
        if humidity is None and state:
            humidity = state
            if state == "HUMIDITY_HIGH":
                text = (f"🍄 Risc de {disease['name']} – {title}\nAer umed ({disease['min-humidity-pct']:.0f}% sau mai mult) "
                        f"{damp_hours} din ultimele {within_hours} ore · acum {hum:.0f}%, {_num(temp)} °C\n{disease['advice']}")
            else:
                text = f"🌵 Aer fierbinte și uscat – {title}\nUmiditate: {hum:.0f}% · Temperatura: {_num(temp)} °C\n{dry['advice']}"
            add(ts, temp, hum, state, "WARNING", text)
    return alerts


# ---------- reference evapotranspiration (FAO-56) ----------

def extraterrestrial_radiation_mm(day, latitude_deg):
    """Ra of FAO-56 eq. 21 (with eq. 23-25), as millimetres of evaporated water per day (x 0.408)."""
    j = day.timetuple().tm_yday
    phi = math.radians(latitude_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    decl = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl))))
    ra = 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.sin(ws))
    return 0.408 * ra


def et0_hargreaves(day, latitude_deg, t_min, t_max):
    """Reference evapotranspiration, mm/day, FAO-56 eq. 52: needs only the day's lowest and highest temperature."""
    t_mean = (t_min + t_max) / 2
    return 0.0023 * (t_mean + 17.8) * math.sqrt(max(0.0, t_max - t_min)) * extraterrestrial_radiation_mm(day, latitude_deg)


def season_start(day):
    """The water balance starts on 1 May with the soil full after the spring rains."""
    return date(day.year, 5, 1)
