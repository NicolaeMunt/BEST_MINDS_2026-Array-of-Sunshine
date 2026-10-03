"""Frost risk from a sensor reading: dew point, frost level, priority and reasons."""
import math

from .scoring import priority_for, reason

LEVELS = ("NONE", "LOW", "MEDIUM", "HIGH")
LEVEL_SCORE = {"NONE": 0, "LOW": 45, "MEDIUM": 75, "HIGH": 95}
LEVEL_TITLE = {"LOW": "Risc de îngheț", "MEDIUM": "Îngheț", "HIGH": "Îngheț puternic"}
LEVEL_MESSAGE = {
    "LOW": "Urmărește temperatura peste noapte și pregătește protecția: aspersiune, fumigene, material de acoperire",
    "MEDIUM": "Pornește protecția împotriva înghețului: aspersiune, fumigație sau acoperirea culturilor",
    "HIGH": "Pornește urgent protecția împotriva înghețului: aspersiune, fumigație sau acoperirea culturilor",
}

FAST_COOLING = -1.0   # °C/h
CALM_WIND = 1.5       # m/s
RISK_TEMP = 4.0       # °C, start watching below this


def dew_point(temperature, humidity):
    """Magnus formula, °C."""
    a, b = 17.62, 243.12
    g = math.log(max(humidity, 1) / 100) + a * temperature / (b + temperature)
    return round(b * g / (a - g), 1)


def level_index(level):
    return LEVELS.index(level)


def assess_frost(reading):
    """reading: dict with temperature, humidity, optional wind_speed, soil_temperature, trend (°C/h)."""
    t = reading["temperature"]
    dew = dew_point(t, reading["humidity"])
    trend = reading.get("trend")
    predicted = round(t + trend, 1) if trend is not None else None
    wind = reading.get("wind_speed")
    soil = reading.get("soil_temperature")

    if t <= -2:
        level = "HIGH"
    elif t <= 0:
        level = "MEDIUM"
    elif t <= 2 or (t <= RISK_TEMP and ((predicted is not None and predicted <= 0) or dew <= 0)):
        level = "LOW"
    else:
        level = "NONE"

    reasons = []
    if level != "NONE":
        if t <= 0:
            reasons.append(reason("below_zero", f"Temperatura aerului {t:.1f}°C — sub zero", "sensor"))
        else:
            reasons.append(reason("near_zero", f"Temperatura aerului {t:.1f}°C — aproape de zero", "sensor"))
        if trend is not None and trend <= FAST_COOLING:
            reasons.append(reason("fast_cooling",
                                  f"Temperatura scade cu {-trend:.1f}°C/h, peste o oră ≈ {predicted:.1f}°C", "sensor"))
        if dew <= 0:
            if t - dew <= 2:
                reasons.append(reason("hoarfrost", f"Punctul de rouă {dew:.1f}°C e aproape de temperatura aerului "
                                                   "— probabil brumă", "sensor"))
            else:
                reasons.append(reason("black_frost", f"Aer uscat (punct de rouă {dew:.1f}°C) — îngheț „negru” fără "
                                                     "brumă, țesuturile plantelor se deteriorează pe nevăzute", "sensor"))
        if wind is not None and wind < CALM_WIND:
            reasons.append(reason("calm_wind", f"Vânt slab ({wind:.1f} m/s) — aerul rece stagnează la sol", "sensor"))
        if soil is not None and soil <= 0:
            reasons.append(reason("soil_frozen", f"Solul s-a răcit până la {soil:.1f}°C", "sensor"))

    score = LEVEL_SCORE[level] + (5 if level != "NONE" and trend is not None and trend <= -2 else 0)
    return {
        "dew_point": dew,
        "frost_level": level,
        "predicted_temperature_1h": predicted,
        "score": min(score, 100),
        "priority": priority_for(score) if level != "NONE" else "none",
        "title": LEVEL_TITLE.get(level, "Fără risc de îngheț"),
        "message": LEVEL_MESSAGE.get(level, ""),
        "reasons": reasons,
    }
