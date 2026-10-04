"""HTTP client for the sensors-alerts service (Coder 2): the source of truth for sensor readings,
frost and humidity levels, alerts and demo modes. Responses use the shared JSON contract field names."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SENSORS_URL = os.getenv("SENSORS_URL", "http://localhost:8081").rstrip("/")
TIMEOUT_SEC = float(os.getenv("SENSORS_TIMEOUT_SEC", 2))


class SensorsUnavailable(Exception):
    """The service is down or answered with an error other than 404 and 409."""


class SensorsConflict(Exception):
    """409: the service refused the request; the message says why, in Romanian."""


def _call(method, path, params=None, body=None):
    url = SENSORS_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    request = urllib.request.Request(url, method=method, data=data,
                                     headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        if e.code == 404:  # unknown parcel or no readings yet
            return None
        if e.code == 409:
            try:
                message = json.loads(e.read()).get("message")
            except ValueError:
                message = None
            raise SensorsConflict(message or "Serviciul de senzori a refuzat cererea") from e
        raise SensorsUnavailable(f"{method} {path}: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SensorsUnavailable(f"Serviciul de senzori ({SENSORS_URL}) nu răspunde") from e


def _parcel_path(parcel_id):
    return f"/sensors/parcels/{urllib.parse.quote(parcel_id)}"


def parcels():
    """[{id, name, crop}]: the sensor locations configured in sensors-alerts."""
    return _call("GET", "/sensors/parcels") or []


def latest(parcel_id):
    """{parcelId, timestamp, temperatureC, humidityPct, precipitationMm, dewPointC, frostLevel, crop, humidityLevel,
    mode, phase, frostWarningC, frostCriticalC, disease} or None."""
    return _call("GET", _parcel_path(parcel_id) + "/latest")


def readings(parcel_id, minutes):
    """[{parcelId, timestamp, temperatureC, humidityPct}], oldest first."""
    return _call("GET", _parcel_path(parcel_id) + "/readings", {"minutes": minutes}) or []


def alerts(parcel_id=None, type_="ALL"):
    """[{parcelId, parcelName, crop, type, level, temperatureC, humidityPct, dewPointC, timestamp, message}],
    newest first. type_: FROST | HUMIDITY | ALL."""
    params = {"type": type_}
    if parcel_id:
        params["parcelId"] = parcel_id
    return _call("GET", "/alerts", params) or []


def send_advice(parcel_id, alert):
    """Hands watering or sowing advice to sensors-alerts, which stores it and sends it to Telegram.
    alert: {type: IRRIGATION | SOWING, timestamp, level, temperatureC, humidityPct, dewPointC, message}.
    Returns {"sent": bool} or None."""
    return _call("POST", _parcel_path(parcel_id) + "/advice", body=alert)


def demo(kind, parcel_id):
    """kind: frost | humid | dry | replay | normal | irrigate. SensorsConflict when the demo cannot run now."""
    return _call("POST", f"/demo/{kind}/{urllib.parse.quote(parcel_id)}")


def demo_reset():
    return _call("POST", "/demo/reset")
