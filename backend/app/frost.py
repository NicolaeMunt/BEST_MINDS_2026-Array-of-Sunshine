"""Turns a sensors-alerts reading into priority, recommendation and reasons.
The frost level itself (OK / WARNING / CRITICAL) comes from the sensors-alerts service."""
import math
from datetime import timedelta

from .scoring import priority_for, reason

LEVEL_SCORE = {"OK": 0, "WARNING": 60, "CRITICAL": 95}
LEVEL_TITLE = {"OK": "Fără risc de îngheț", "WARNING": "Risc de îngheț", "CRITICAL": "Îngheț"}
LEVEL_MESSAGE = {
    "OK": "",
    "WARNING": "Urmărește temperatura și pregătește protecția: aspersiune, fumigene, material de acoperire",
    "CRITICAL": "Pornește imediat protecția împotriva înghețului: aspersiune, fumigație sau acoperirea culturilor",
}
FAST_DROP_C = 1.0     # °C colder than an hour ago
WINDOW = timedelta(hours=1)


def dew_point(temperature, humidity):
    """Magnus formula, °C (same as the sensors-alerts service)."""
    a, b = 17.62, 243.12
    g = math.log(max(1, min(100, humidity)) / 100) + a * temperature / (b + temperature)
    return round(b * g / (a - g), 1)


def drop_last_hour(latest, history, parse_ts):
    """How much colder it is now than at the start of the last hour of readings (reading time, so it
    is a simulated hour during replay). Negative when warming up; None without history."""
    now = parse_ts(latest["timestamp"])
    window = [r for r in history if now - WINDOW <= parse_ts(r["timestamp"]) <= now]
    if len(window) < 2:
        return None
    return round(window[0]["temperatureC"] - latest["temperatureC"], 1)


def assess_frost(latest, drop):
    t = latest["temperatureC"]
    dew = latest.get("dewPointC")
    if dew is None:
        dew = dew_point(t, latest["humidityPct"])
    level = latest.get("frostLevel") or "OK"

    reasons = []
    if level != "OK":
        if t <= 0:
            reasons.append(reason("below_zero", f"Temperatura aerului {t:.1f}°C — sub zero", "sensor"))
        elif t <= 2:
            reasons.append(reason("near_zero", f"Temperatura aerului {t:.1f}°C — aproape de zero", "sensor"))
        if drop is not None and drop >= FAST_DROP_C:
            reasons.append(reason("fast_cooling", f"Temperatura a scăzut cu {drop:.1f}°C în ultima oră", "sensor"))
        if dew <= 0:
            if t - dew <= 2:
                reasons.append(reason("hoarfrost", f"Punctul de rouă {dew:.1f}°C e aproape de temperatura aerului "
                                                   "— probabil brumă", "sensor"))
            else:
                reasons.append(reason("black_frost", f"Aer uscat (punct de rouă {dew:.1f}°C) — îngheț „negru” fără "
                                                     "brumă, țesuturile plantelor se deteriorează pe nevăzute", "sensor"))
        if not reasons:
            reasons.append(reason("frost_rule", f"Temperatura aerului {t:.1f}°C, în scădere", "sensor"))

    score = LEVEL_SCORE.get(level, 0) + (5 if level == "WARNING" and drop is not None and drop >= 3 else 0)
    return {
        "frost_level": level,
        "score": score,
        "priority": priority_for(score) if level != "OK" else "none",
        "title": LEVEL_TITLE.get(level, level),
        "message": LEVEL_MESSAGE.get(level, ""),
        "reasons": reasons,
    }
