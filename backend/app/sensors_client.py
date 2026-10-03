"""HTTP client for the sensors-alerts service (Coder 2): the source of truth for sensor readings,
frost levels, alerts and demo modes. Responses use the shared JSON contract field names."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SENSORS_URL = os.getenv("SENSORS_URL", "http://localhost:8081").rstrip("/")
TIMEOUT_SEC = float(os.getenv("SENSORS_TIMEOUT_SEC", 2))


class SensorsUnavailable(Exception):
    """The service is down or answered with an error other than 404."""


def _call(method, path, params=None):
    url = SENSORS_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        if e.code == 404:  # unknown parcel or no readings yet
            return None
        raise SensorsUnavailable(f"{method} {path}: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SensorsUnavailable(f"Serviciul de senzori ({SENSORS_URL}) nu răspunde") from e


def latest(parcel_id):
    """{parcelId, timestamp, temperatureC, humidityPct, dewPointC, frostLevel} or None."""
    return _call("GET", f"/sensors/parcels/{urllib.parse.quote(parcel_id)}/latest")


def readings(parcel_id, minutes):
    """[{parcelId, timestamp, temperatureC, humidityPct}], oldest first."""
    return _call("GET", f"/sensors/parcels/{urllib.parse.quote(parcel_id)}/readings", {"minutes": minutes}) or []


def alerts(parcel_id=None):
    """[{parcelId, parcelName, level, temperatureC, humidityPct, dewPointC, timestamp, message}], newest first."""
    return _call("GET", "/alerts", {"parcelId": parcel_id} if parcel_id else None) or []


def demo_frost(parcel_id):
    return _call("POST", f"/demo/frost/{urllib.parse.quote(parcel_id)}")


def demo_replay(parcel_id):
    return _call("POST", f"/demo/replay/{urllib.parse.quote(parcel_id)}")


def demo_reset():
    return _call("POST", "/demo/reset")
