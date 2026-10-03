"""Writes the sample history: invented hourly sensor readings from 1 May until yesterday and the alerts
they would have raised, for the five demo sensors. The numbers are made up (not measurements): a
Moldovan season with a late frost in May, rainy spells, two heat waves and the first autumn frost.

    python make_sample.py        # rewrites data/sensor-history-sample.csv and data/alert-history-sample.csv
    python load_sample.py        # puts them into the database

The same seed gives the same weather; only the end date moves with the day it is run.
"""
import csv
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.frost import dew_point

DATA = Path(__file__).resolve().parent / "data"
READINGS_FILE = DATA / "sensor-history-sample.csv"
ALERTS_FILE = DATA / "alert-history-sample.csv"
LOCAL = timezone(timedelta(hours=3))  # Europe/Chisinau in summer
SEED = 2026

# Same IDs, names and crops as app.parcels in sensors-alerts/src/main/resources/application.yml.
# temp/hum: how this spot differs from the others (an orchard in a hollow is colder and damper).
SENSORS = [
    {"id": "P1", "name": "Livada Nord", "crop": "orchard", "temp": -0.5, "hum": 2},
    {"id": "P2", "name": "Via Sud", "crop": "vineyard", "temp": 0.4, "hum": -2},
    {"id": "P3", "name": "Câmpul Mare", "crop": "wheat", "temp": 0.0, "hum": 0},
    {"id": "P4", "name": "Lanul de Porumb", "crop": "corn", "temp": 0.2, "hum": 1},
    {"id": "P5", "name": "Lotul de Floarea-soarelui", "crop": "sunflower", "temp": -0.1, "hum": -1},
]
# Thresholds and advice copied from app.crops in the same application.yml.
CROPS = {
    "wheat": {"name": "grâu", "frost_warning": 0, "frost_critical": -3, "hum_low": 30, "hum_high": 85,
              "frost_advice": "Grâul rezistă la înghețuri ușoare. Verificați lanul dimineața.",
              "humid_advice": "Risc de rugină, septorioză și fuzarioză. Verificați lanul și pregătiți tratamentul fungicid.",
              "dry_advice": "Risc de șiștăvire a boabelor. Irigați dacă este posibil."},
    "corn": {"name": "porumb", "frost_warning": 3, "frost_critical": 0, "hum_low": 35, "hum_high": 85,
             "frost_advice": "Plantele tinere de porumb sunt sensibile la îngheț. Pregătiți măsurile de protecție.",
             "humid_advice": "Risc de fuzarioză și helmintosporioză. Verificați frunzele și știuleții.",
             "dry_advice": "Risc de polenizare slabă. Irigați dacă este posibil."},
    "sunflower": {"name": "floarea-soarelui", "frost_warning": 1, "frost_critical": -3, "hum_low": 25, "hum_high": 80,
                  "frost_advice": "Plantele tinere suportă înghețuri scurte. Verificați cultura dimineața.",
                  "humid_advice": "Risc de putregai alb și putregai cenușiu. Verificați tulpinile și calatidiile.",
                  "dry_advice": "Risc de stres hidric. Urmăriți umiditatea solului."},
    "orchard": {"name": "livadă", "frost_warning": 2, "frost_critical": -1, "hum_low": 35, "hum_high": 85,
                "frost_advice": "Florile și mugurii sunt în pericol. Pregătiți aspersiunea sau fumigația.",
                "humid_advice": "Risc de rapăn și monilioză. Pregătiți tratamentul fungicid.",
                "dry_advice": "Risc de stres hidric și cădere a fructelor. Irigați livada."},
    "vineyard": {"name": "viță-de-vie", "frost_warning": 2, "frost_critical": -1, "hum_low": 30, "hum_high": 80,
                 "frost_advice": "Lăstarii tineri sunt în pericol. Pregătiți fumigația sau aspersiunea.",
                 "humid_advice": "Risc de mană și putregai cenușiu. Pregătiți tratamentul fungicid.",
                 "dry_advice": "Risc de stres hidric și arsuri pe frunze. Irigați plantațiile tinere."},
}
DISEASE_MIN_TEMP_C = 10    # app.humidity.disease-min-temp-c
HUMIDITY_CLEAR_MARGIN = 5  # app.humidity.clear-margin-pct
FROST_CLEAR_MARGIN_C = 1   # app.frost.all-clear-margin-c

# The story of the season: (first day, last day, temperature shift in °C, humidity shift in %).
SPELLS = [
    (date(2026, 5, 5), date(2026, 5, 7), -8.5, 4),     # late frost
    (date(2026, 6, 10), date(2026, 6, 13), -3, 24),    # rain
    (date(2026, 7, 15), date(2026, 7, 18), 7, -20),    # heat wave
    (date(2026, 8, 9), date(2026, 8, 11), 6, -19),     # heat wave
    (date(2026, 8, 24), date(2026, 8, 26), -3, 24),    # rain
    (date(2026, 9, 16), date(2026, 9, 18), -2, 23),    # rain
    (date(2026, 9, 30), date(2026, 10, 2), -10.5, 3),  # first autumn frost
]


def weather(start, end):
    """Hourly (local time, temperature, humidity) of the region, before the per-sensor differences."""
    rnd = random.Random(SEED)
    days = (end - start).days + 1
    # Weather that lasts a few days: each day keeps most of yesterday's departure from the seasonal normal.
    drift, value = [], 0.0
    for _ in range(days + 1):
        value = 0.7 * value + rnd.gauss(0, 1.6)
        drift.append(value)
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        normal = 10.5 + 11.5 * math.cos(2 * math.pi * (day.timetuple().tm_yday - 203) / 365)
        shift_t = sum(s[2] for s in SPELLS if s[0] <= day <= s[1])
        shift_h = sum(s[3] for s in SPELLS if s[0] <= day <= s[1])
        for hour in range(24):
            slow = drift[d] + (drift[d + 1] - drift[d]) * hour / 24
            cycle = math.cos(2 * math.pi * (hour - 15) / 24)  # warmest at 15:00, coldest at 03:00
            temp = normal + slow + shift_t + 6.5 * cycle + rnd.gauss(0, 0.3)
            swing = 4 if shift_h > 15 else 14  # on rainy days the air stays damp at noon too
            hum = 58 - swing * cycle - 1.5 * slow + shift_h + rnd.gauss(0, 1.5)
            rows.append((datetime(day.year, day.month, day.day, hour, tzinfo=LOCAL), temp, hum))
    return rows


def frost_level(temp, crop):
    return "CRITICAL" if temp <= crop["frost_critical"] else "WARNING" if temp <= crop["frost_warning"] else "OK"


def alerts_for(sensor, readings):
    """The alerts sensors-alerts would have sent for these readings (same episodes as its AlertService,
    without the 'falling fast' warning and the cooldown, which need finer readings)."""
    crop = CROPS[sensor["crop"]]
    title = f"{sensor['name']} ({crop['name']})"
    frost, humidity, alerts = "OK", None, []

    def add(ts, temp, hum, kind, level, text):
        alerts.append([sensor["id"], sensor["name"], sensor["crop"], kind, level, ts, temp, hum, dew_point(temp, hum), text])

    for ts, temp, hum in readings:
        level = frost_level(temp, crop)
        if (level, frost) in {("WARNING", "OK"), ("CRITICAL", "OK"), ("CRITICAL", "WARNING")}:
            frost = level
            add(ts, temp, hum, "FROST", level,
                f"❄️ ÎNGHEȚ – {title}\nTemperatura: {temp:.1f} °C (prag critic {crop['name']}: {crop['frost_critical']:.1f} °C)"
                if level == "CRITICAL" else
                f"⚠️ Risc de îngheț – {title}\nTemperatura: {temp:.1f} °C\nUmiditate: {hum:.0f}% · "
                f"Punct de rouă: {dew_point(temp, hum):.1f} °C\n{crop['frost_advice']}")
        elif level == "OK" and frost != "OK" and temp > crop["frost_warning"] + FROST_CLEAR_MARGIN_C:
            frost = "OK"
            add(ts, temp, hum, "FROST", "OK", f"✅ Pericol trecut – {title}\nTemperatura: {temp:.1f} °C")

        state = "LOW" if hum <= crop["hum_low"] else \
            "HIGH" if hum >= crop["hum_high"] and temp >= DISEASE_MIN_TEMP_C else "OK"
        if humidity is None and state != "OK":
            humidity = "HUMIDITY_" + state
            high = state == "HIGH"
            add(ts, temp, hum, humidity, "WARNING",
                f"{'💧 Umiditate ridicată' if high else '🌵 Umiditate scăzută'} – {title}\n"
                f"Umiditate: {hum:.0f}% (prag {crop['name']}: {crop['hum_high' if high else 'hum_low']:.0f}%) · "
                f"Temperatura: {temp:.1f} °C\n{crop['humid_advice' if high else 'dry_advice']}")
        elif humidity and state == "OK" and \
                crop["hum_low"] + HUMIDITY_CLEAR_MARGIN <= hum <= crop["hum_high"] - HUMIDITY_CLEAR_MARGIN:
            add(ts, temp, hum, humidity, "OK", f"✅ Umiditate revenită la normal – {title}\nUmiditate: {hum:.0f}%")
            humidity = None
    return alerts


def stamp(ts):
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    start, end = date(2026, 5, 1), date.today() - timedelta(days=1)
    region = weather(start, end)
    all_readings, all_alerts = [], []
    for i, sensor in enumerate(SENSORS):
        rnd = random.Random(SEED + 1 + i)
        readings = [(ts, round(temp + sensor["temp"] + rnd.gauss(0, 0.15), 1),
                     round(max(15, min(98, hum + sensor["hum"] + rnd.gauss(0, 1))), 1)) for ts, temp, hum in region]
        all_readings += [[sensor["id"], stamp(ts), temp, hum] for ts, temp, hum in readings]
        all_alerts += [[*a[:5], stamp(a[5]), *a[6:]] for a in alerts_for(sensor, readings)]

    note = [f"# Sample data, invented (not measured): {start} to {end}, hourly, UTC. Written by make_sample.py."]
    with READINGS_FILE.open("w", newline="", encoding="utf-8") as f:
        f.write("\n".join(note) + "\n")
        csv.writer(f).writerows([["parcelId", "timestamp", "temperatureC", "humidityPct"], *all_readings])
    with ALERTS_FILE.open("w", newline="", encoding="utf-8") as f:
        f.write("\n".join(note) + "\n")
        csv.writer(f).writerows([["parcelId", "parcelName", "crop", "type", "level", "timestamp", "temperatureC",
                                  "humidityPct", "dewPointC", "message"], *all_alerts])
    print(f"{READINGS_FILE.name}: {len(all_readings)} readings; {ALERTS_FILE.name}: {len(all_alerts)} alerts")


if __name__ == "__main__":
    main()
