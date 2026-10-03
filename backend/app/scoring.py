"""Merges drone (vision) and soil/weather (field) results into prioritized actions with reasons.

Every rule returns an action with a 0..100 score; score -> priority:
>= 70 high, >= 40 medium, otherwise low. Actions below MIN_ACTION_SCORE are dropped.
"""
from datetime import datetime, timezone

CROP_THRESHOLDS = {
    "wheat":     {"moisture_low": 25, "moisture_critical": 15, "ndvi_good": 0.65, "ndvi_poor": 0.40, "heat_c": 30},
    "barley":    {"moisture_low": 25, "moisture_critical": 15, "ndvi_good": 0.65, "ndvi_poor": 0.40, "heat_c": 30},
    "corn":      {"moisture_low": 30, "moisture_critical": 20, "ndvi_good": 0.70, "ndvi_poor": 0.45, "heat_c": 35},
    "sunflower": {"moisture_low": 22, "moisture_critical": 12, "ndvi_good": 0.60, "ndvi_poor": 0.40, "heat_c": 35},
}
DEFAULT_CROP = "wheat"

DISEASE_NAMES = {
    "rust": "rugină",
    "septoria": "septorioză",
    "powdery_mildew": "făinare",
    "fusarium": "fuzarioză",
    "smut": "tăciune",
}
NO_DISEASE = {None, "", "none", "healthy"}

MIN_ACTION_SCORE = 20
DISEASE_MIN_CONFIDENCE = 0.5
RIPE = 0.9            # ready to harvest
RIPENING = 0.75       # harvest soon; NDVI naturally drops from here on
HEAVY_RAIN_MM = 10
HIGH_HUMIDITY = 80
VISION_MAX_AGE_DAYS = 7
FIELD_MAX_AGE_HOURS = 48


def priority_for(score):
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def make_action(type_, title, score, reasons):
    score = int(max(0, min(100, round(score))))
    return {"type": type_, "title": title, "score": score, "priority": priority_for(score), "reasons": reasons}


def reason(code, text, source):
    return {"code": code, "text": text, "source": source}


def _has_disease(v):
    return (v.get("disease") or "").lower() not in NO_DISEASE and \
        (v.get("disease_confidence") or 0) >= DISEASE_MIN_CONFIDENCE


def _irrigation(v, f, t):
    if (v.get("ripeness") or 0) >= RIPE:
        return None  # no point watering a crop that is ready to harvest
    score, reasons = 0, []

    moisture = f.get("soil_moisture_pct")
    if moisture is not None:
        if moisture < t["moisture_critical"]:
            score += 70
            reasons.append(reason("soil_moisture_critical",
                                   f"Umiditatea solului {moisture:.0f}% — critic de scăzută (normal de la {t['moisture_low']}%)", "field"))
        elif moisture < t["moisture_low"]:
            score += 45
            reasons.append(reason("soil_moisture_low",
                                   f"Umiditatea solului {moisture:.0f}% — sub normă ({t['moisture_low']}%)", "field"))

    stress = v.get("water_stress_pct")
    if stress is not None and stress >= 10:
        score += 30 if stress >= 30 else 15
        reasons.append(reason("water_stress", f"Drona detectează stres hidric pe {stress:.0f}% din suprafață", "vision"))

    if score == 0:
        return None

    temp_max = f.get("temp_max_forecast_c")
    if temp_max is not None and temp_max >= t["heat_c"]:
        score += 10
        reasons.append(reason("heat_forecast", f"Prognoza de căldură până la {temp_max:.0f}°C va usca și mai mult solul", "field"))

    rain = f.get("rain_forecast_mm_48h")
    if rain is not None and rain >= HEAVY_RAIN_MM:
        score -= 40
        reasons.append(reason("rain_expected", f"Se așteaptă {rain:.0f} mm de ploaie în 48 h — irigarea poate fi amânată", "field"))

    return make_action("irrigate", "Este necesară irigarea", score, reasons)


def _disease(v, f):
    if not _has_disease(v):
        return None
    name = DISEASE_NAMES.get(v["disease"].lower(), v["disease"])
    conf = v["disease_confidence"]
    area = v.get("disease_area_pct") or 0
    score = 50 + min(area, 40) + (10 if conf >= 0.8 else 0)
    reasons = [reason("disease_detected",
                       f"Boală detectată: {name} (încredere {conf:.0%}, {area:.0f}% din suprafață)", "vision")]
    humidity = f.get("humidity_pct")
    if humidity is not None and humidity >= HIGH_HUMIDITY:
        score += 10
        reasons.append(reason("high_humidity", f"Umiditatea aerului {humidity:.0f}% favorizează răspândirea", "field"))
    return make_action("treat_disease", f"Tratează boala ({name})", score, reasons)


def _pests(v):
    area = v.get("pest_area_pct")
    if area is None or area < 5:
        return None
    return make_action("treat_pests", "Tratează împotriva dăunătorilor", 40 + area,
                   [reason("pests_detected", f"Dăunători pe {area:.0f}% din suprafață", "vision")])


def _weeds(v):
    area = v.get("weed_area_pct")
    if area is None or area < 10:
        return None
    return make_action("remove_weeds", "Elimină buruienile", 30 + area / 2,
                   [reason("weeds_detected", f"Buruieni pe {area:.0f}% din suprafață", "vision")])


def _harvest(v, f):
    ripeness = v.get("ripeness")
    if ripeness is None or ripeness < RIPENING:
        return None
    if ripeness < RIPE:
        return make_action("harvest", "Pregătește recoltarea", 40,
                       [reason("ripening", f"Maturitate {ripeness:.0%} — recoltarea în următoarele zile", "vision")])
    score = 75
    reasons = [reason("ripe", f"Maturitate {ripeness:.0%} — recolta este gata", "vision")]
    rain = f.get("rain_forecast_mm_48h")
    if rain is not None and rain >= HEAVY_RAIN_MM:
        score += 20
        reasons.append(reason("rain_before_harvest", f"Se așteaptă {rain:.0f} mm de ploaie — recoltează înainte de ploaie", "field"))
    return make_action("harvest", "Recoltează", score, reasons)


def _nutrients(v, f, t):
    """Low NDVI that is not explained by drought, disease or ripening -> likely nutrient deficiency."""
    ndvi = v.get("ndvi_mean")
    moisture = f.get("soil_moisture_pct")
    if ndvi is None or ndvi >= t["ndvi_poor"] or moisture is None or moisture < t["moisture_low"]:
        return None
    if _has_disease(v) or (v.get("ripeness") or 0) >= RIPENING:
        return None
    return make_action("fertilize", "Aplică îngrășăminte", 45, [
        reason("low_ndvi", f"NDVI {ndvi:.2f} — plante slabe (normal de la {t['ndvi_good']:.2f})", "vision"),
        reason("moisture_ok", f"Umiditatea solului e normală ({moisture:.0f}%) — probabil deficit de azot", "field"),
    ])


def _age(reported_at, now):
    ts = datetime.fromisoformat(reported_at)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return now - ts


def _freshness(vision, field, now):
    actions = []
    if vision is None:
        actions.append(make_action("fly_drone", "Lansează drona", 35,
                               [reason("no_vision_data", "Nu există date de la dronă pentru acest teren", "system")]))
    elif (days := _age(vision["reported_at"], now).days) >= VISION_MAX_AGE_DAYS:
        actions.append(make_action("fly_drone", "Actualizează zborul cu drona", 25,
                               [reason("vision_outdated", f"Ultimul zbor a fost acum {days} zile", "system")]))
    if field is None:
        actions.append(make_action("check_sensors", "Verifică senzorii", 25,
                               [reason("no_field_data", "Nu există date despre sol și vreme", "system")]))
    elif (hours := int(_age(field["reported_at"], now).total_seconds() // 3600)) >= FIELD_MAX_AGE_HOURS:
        actions.append(make_action("check_sensors", "Verifică senzorii", 20,
                               [reason("field_outdated", f"Datele despre sol nu au fost actualizate de {hours} h", "system")]))
    return actions


def _health_score(v, t):
    if not v:
        return None
    ndvi = v.get("ndvi_mean")
    if ndvi is None or (v.get("ripeness") or 0) >= RIPENING:
        base = 90
    else:
        base = max(0, min(100, 100 * (ndvi - 0.1) / (t["ndvi_good"] - 0.1)))
    penalty = (v.get("pest_area_pct") or 0) * 0.8 \
        + (v.get("weed_area_pct") or 0) * 0.3 \
        + (v.get("water_stress_pct") or 0) * 0.4
    if _has_disease(v):
        penalty += v.get("disease_area_pct") or 0
    return int(round(max(0, min(100, base - penalty))))


def _frost_action(sensors):
    if not sensors or sensors["frost"]["frost_level"] == "NONE":
        return None
    frost = sensors["frost"]
    return make_action("protect_from_frost", f"{frost['title']} — protejează culturile", frost["score"], frost["reasons"])


def assess(parcel, vision, field, sensors=None, now=None):
    """parcel: DB row dict; vision/field: latest reports (or None); sensors: sensors.latest() (or None).
    Returns the ParcelOut-shaped dict."""
    now = now or datetime.now(timezone.utc)
    v, f = vision or {}, field or {}
    t = CROP_THRESHOLDS.get((parcel["crop"] or "").lower(), CROP_THRESHOLDS[DEFAULT_CROP])

    candidates = [_frost_action(sensors), _irrigation(v, f, t), _disease(v, f), _pests(v), _weeds(v),
                  _harvest(v, f), _nutrients(v, f, t), *_freshness(vision, field, now)]
    actions = sorted((a for a in candidates if a and a["score"] >= MIN_ACTION_SCORE),
                     key=lambda a: a["score"], reverse=True)

    health = _health_score(v, t)
    priority = actions[0]["priority"] if actions else "none"
    if vision is None and field is None and sensors is None:
        status = "no_data"
    elif priority == "high" or (health is not None and health < 40):
        status = "critical"
    elif priority == "medium" or (health is not None and health < 70):
        status = "warning"
    else:
        status = "ok"

    urgent = [a["title"] for a in actions if a["priority"] != "low"]
    if status == "no_data":
        summary = "Nu există date pentru teren — lansează drona"
    else:
        summary = "; ".join(urgent) if urgent else ("Nicio acțiune urgentă" if actions else "Totul este în regulă")

    metric_keys = ("ndvi_mean", "water_stress_pct", "disease", "disease_confidence", "disease_area_pct",
                   "pest_area_pct", "weed_area_pct", "ripeness", "soil_moisture_pct", "air_temp_c",
                   "humidity_pct", "temp_max_forecast_c", "rain_forecast_mm_48h")
    merged = {**v, **f}

    return {
        **parcel,
        "sensors": sensors,
        "status": status,
        "health_score": health,
        "priority": priority,
        "summary": summary,
        "actions": actions,
        "metrics": {k: merged.get(k) for k in metric_keys},
        "zones": v.get("zones") or [],
        "updated_at": {"vision": v.get("reported_at"), "field": f.get("reported_at")},
    }
