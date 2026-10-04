"""When the soil is warm enough to sow: the daily mean soil temperature at seed depth (the soil probe, ~5 cm)
has reached the crop's minimum for a few days in a row, inside its sowing window (app.crops.<crop>.sowing).
Unlike the fixed crop calendar, this follows the parcel's own soil, so it works in the north and the south."""
from datetime import date, datetime, time, timedelta

from . import crops, db

ADVICE_TIME = time(8, 0)


def warm_days(conn, parcel_id, start, end):
    """{local date: mean soil temperature} from the hourly soil readings between two dates."""
    rows = db.soil_hours(conn, parcel_id, datetime.combine(start, time(0), crops.LOCAL),
                         datetime.combine(end + timedelta(days=1), time(0), crops.LOCAL))
    sums = {}
    for r in rows:
        if r["soil_t"] is None:
            continue
        d = datetime.fromisoformat(r["hour"].replace("Z", "+00:00")).astimezone(crops.LOCAL).date()
        s = sums.setdefault(d, [0.0, 0])
        s[0] += r["soil_t"]
        s[1] += 1
    return {d: s[0] / s[1] for d, s in sums.items()}


def alerts(conn, parcel, day):
    """The season's "poți semăna" advice up to `day` (at most one): [alert] or []. parcel: {'id', 'name', 'crop'}."""
    cfg = crops.crop(parcel["crop"])
    rule = (cfg or {}).get("sowing")
    if not rule:
        return []
    # Once the farmer has sowed, the advice is no longer needed from that day on.
    row = db.parcel(conn, parcel["id"])
    sown = date.fromisoformat(row["sowing_date"]) if row and row["sowing_date"] else None
    first = date(day.year, *map(int, str(rule["from"]).split("-")))
    last = min(day, date(day.year, *map(int, str(rule["to"]).split("-"))))
    if last < first:
        return []
    temps = warm_days(conn, parcel["id"], first, last)
    need, run = int(rule.get("days", 3)), []
    d = first
    while d <= last:
        t = temps.get(d)
        run = run + [t] if t is not None and t >= rule["min-soil-temp-c"] else []
        if sown and d >= sown:
            return []
        if len(run) >= need:
            text = (f"🌱 Poți semăna – {parcel['name']} ({cfg['name']})\nSolul are în medie {sum(run[-need:]) / need:.1f} °C "
                    f"la 5 cm de {need} zile la rând; {cfg['name']} răsare uniform de la {rule['min-soil-temp-c']:.0f} °C.")
            return [{"parcelId": parcel["id"], "parcelName": parcel["name"], "crop": parcel["crop"], "type": "SOWING",
                     "level": "WARNING", "temperatureC": round(run[-1], 1), "humidityPct": 0, "dewPointC": 0.0,
                     "timestamp": db.ts_text(datetime.combine(d, ADVICE_TIME, crops.LOCAL)), "message": text}]
        d += timedelta(days=1)
    return []
