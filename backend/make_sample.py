"""Writes the sample history from real weather, so the season the app shows is the one the satellite saw:
hourly temperature, humidity, rain, soil temperature (0-7 cm) and soil moisture (7-28 cm) at each demo parcel
from 1 April until yesterday, and the alerts the crop rules of sensors-alerts would have raised. Also writes the spells the simulator replays: for every crop the
first damp spell with a disease alert (HUMID) and the first dry, hot spell (DRY), and a real frost night.

The weather is not measured by a sensor in the field: it is the Open-Meteo Historical Weather API (reanalysis,
ERA5 and ERA5-Land for the soil, https://open-meteo.com, CC BY 4.0) at the centre of each parcel. Only this
script needs the internet.

    python make_sample.py        # rewrites data/sensor-history-sample.csv, data/alert-history-sample.csv and the replays
    python load_sample.py        # puts readings and alerts into the database
"""
import csv
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import crops
from app.frost import dew_point

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PARCELS_FILE = DATA / "parcels.geojson"
READINGS_FILE = DATA / "sensor-history-sample.csv"
ALERTS_FILE = DATA / "alert-history-sample.csv"
REPLAY_DIR = HERE.parent / "sensors-alerts" / "src" / "main" / "resources" / "replay"
FROST_NIGHT_FILE = DATA / "frost-night-orhei-2025-04-09.csv"
API = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "Open-Meteo Historical Weather API (reanalysis), https://open-meteo.com, CC BY 4.0"
SEASON_START = date(2026, 4, 1)  # April: the soil warms up for sowing
# A replayed spell starts this long before its alert (so the rule has the hours it counts) and runs on after it.
DRY_LEAD_H, TAIL_H = 12, 6
# The coldest night of the April 2025 frosts near Orhei (-3.2 °C on 9 April), when the apple trees were in bud.
FROST_NIGHT = (datetime(2025, 4, 8, 18), datetime(2025, 4, 9, 11))


def parcels():
    """The demo parcels with the centre of their polygon."""
    out = []
    for f in json.loads(PARCELS_FILE.read_text(encoding="utf-8"))["features"]:
        ring = f["geometry"]["coordinates"][0]
        out.append({"id": f["properties"]["parcel_id"], "name": f["properties"]["name"], "crop": f["properties"]["crop"],
                    "lon": sum(p[0] for p in ring) / len(ring), "lat": sum(p[1] for p in ring) / len(ring)})
    return out


def weather(lat, lon, start, end, zone="GMT"):
    """Hourly (time, temperature °C, humidity %, rain mm, soil temperature °C, soil moisture %) from start to end
    (dates, both included). In GMT the times are aware UTC datetimes; in another zone, that zone's naive local times."""
    query = urllib.parse.urlencode({"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}", "start_date": start,
                                    "end_date": end, "timezone": zone,
                                    "hourly": "temperature_2m,relative_humidity_2m,precipitation,"
                                              "soil_temperature_0_to_7cm,soil_moisture_7_to_28cm"})
    with urllib.request.urlopen(f"{API}?{query}", timeout=60) as response:
        h = json.loads(response.read())["hourly"]
    rows = []
    for t, temp, hum, rain, soil_t, soil_m in zip(h["time"], h["temperature_2m"], h["relative_humidity_2m"],
                                                  h["precipitation"], h["soil_temperature_0_to_7cm"],
                                                  h["soil_moisture_7_to_28cm"]):
        if temp is None or hum is None:
            continue
        ts = datetime.fromisoformat(t)
        rows.append((ts.replace(tzinfo=timezone.utc) if zone == "GMT" else ts, round(temp, 1), round(hum),
                     round(rain or 0, 1), None if soil_t is None else round(soil_t, 1),
                     None if soil_m is None else round(soil_m * 100, 1)))
    return rows


def stamp(ts):
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


REPLAY_HEADER = ["timestamp", "temperatureC", "humidityPct", "precipitationMm", "soilTemperatureC", "soilMoisturePct"]


def write_replay(path, note, rows):
    """The columns of REPLAY_HEADER, as the sensors-alerts replay reads them."""
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write("".join(f"# {line}\n" for line in note))
        csv.writer(f).writerows([REPLAY_HEADER, *rows])


def spells(parcel, readings, alerts):
    """The first disease alert (HUMID) and the first dry-air alert (DRY) of the season, with the hours around them."""
    cfg = crops.crop(parcel["crop"])
    lead = {"humid": max((c["within-hours"] for c in (cfg.get("disease") or {}).get("conditions", [])), default=0) + 6,
            "dry": DRY_LEAD_H}
    written = []
    for mode, kind in (("humid", "HUMIDITY_HIGH"), ("dry", "HUMIDITY_LOW")):
        path = REPLAY_DIR / f"{mode}-{parcel['crop']}.csv"
        first = next((a for a in alerts if a[3] == kind and a[4] == "WARNING"), None)
        if not first:
            path.unlink(missing_ok=True)
            continue
        at = first[5]
        rows = [(stamp(r[0]), *r[1:]) for r in readings
                if at - timedelta(hours=lead[mode]) <= r[0] <= at + timedelta(hours=TAIL_H)]
        what = f"{cfg['disease']['name']} risk" if mode == "humid" else "dry, hot air"
        write_replay(path, [f"Real {'damp' if mode == 'humid' else 'dry, hot'} spell at {parcel['name']} ({parcel['crop']}): "
                            f"{what} from {at.astimezone(crops.LOCAL):%Y-%m-%d %H:%M} local time. Written by backend/make_sample.py.",
                            f"Not measured by a sensor in the field: {SOURCE}."], rows)
        written.append(f"{path.name} ({len(rows)} h)")
    return written


def frost_night(parcel):
    """A real frost night at the parcel, in local time and every 15 minutes (linear between the hours)."""
    start, end = FROST_NIGHT
    hourly = weather(parcel["lat"], parcel["lon"], start.date(), end.date(), zone="Europe/Chisinau")
    hourly = [r for r in hourly if start <= r[0] <= end]
    rows = []
    for r0, r1 in zip(hourly, hourly[1:]):
        for q in range(4):
            mix = [None if a is None or b is None else round(a + (b - a) * q / 4, 1) for a, b in zip(r0[1:], r1[1:])]
            rows.append((f"{r0[0] + timedelta(minutes=15 * q):%Y-%m-%dT%H:%M}", mix[0], round(mix[1]),
                         r0[3] if q == 0 else 0.0, mix[3], mix[4]))
    last = hourly[-1]
    rows.append((f"{last[0]:%Y-%m-%dT%H:%M}", *last[1:]))
    with FROST_NIGHT_FILE.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# Real frost night at {parcel['name']} near Orhei, {start:%Y-%m-%d}/{end:%d} - local time Europe/Chisinau "
                f"- interpolated to 15 min\n# Source: {SOURCE}\n")
        csv.writer(f).writerows([REPLAY_HEADER, *rows])
    return min(r[1] for r in rows)


def main():
    end = date.today() - timedelta(days=1)
    all_readings, all_alerts, replays = [], [], []
    for parcel in parcels():
        # Local days: 1 April, 00:00 in Chișinău is 31 March, 21:00 UTC.
        first = datetime.combine(SEASON_START, datetime.min.time(), crops.LOCAL)
        after = datetime.combine(end + timedelta(days=1), datetime.min.time(), crops.LOCAL)
        readings = [r for r in weather(parcel["lat"], parcel["lon"], SEASON_START - timedelta(days=1), end)
                    if first <= r[0] < after]
        alerts = crops.history_alerts(parcel, [r[:3] for r in readings], dew_point)
        all_readings += [[parcel["id"], stamp(r[0]), *r[1:]] for r in readings]
        all_alerts += [[*a[:5], stamp(a[5]), *a[6:]] for a in alerts]
        replays += spells(parcel, readings, alerts)
        print(f"{parcel['id']} {parcel['crop']}: {len(readings)} hours, {len(alerts)} alerts")
    orchard = next(p for p in parcels() if p["crop"] == "orchard")
    coldest = frost_night(orchard)

    note = [f"# Real weather, not measured by a sensor in the field: {SEASON_START} to {end}, hourly, UTC. "
            f"Source: {SOURCE}. Alerts: the crop rules of sensors-alerts. Written by make_sample.py."]
    with READINGS_FILE.open("w", newline="", encoding="utf-8") as f:
        f.write("\n".join(note) + "\n")
        csv.writer(f).writerows([["parcelId", *REPLAY_HEADER], *all_readings])
    with ALERTS_FILE.open("w", newline="", encoding="utf-8") as f:
        f.write("\n".join(note) + "\n")
        csv.writer(f).writerows([["parcelId", "parcelName", "crop", "type", "level", "timestamp", "temperatureC",
                                  "humidityPct", "dewPointC", "message"], *all_alerts])
    print(f"{READINGS_FILE.name}: {len(all_readings)} readings; {ALERTS_FILE.name}: {len(all_alerts)} alerts")
    print(f"replays: {', '.join(replays)}; {FROST_NIGHT_FILE.name}: coldest {coldest} °C")


if __name__ == "__main__":
    main()
