"""API contracts: sensor readings, frost assessment and alerts (the data comes from the sensors-alerts
service; readings are also stored here with their timestamps).
JSON field names are camelCase (shared contract); inputs also accept snake_case.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Priority = Literal["high", "medium", "low"]
Mode = Literal["NORMAL", "FROST", "HUMID", "DRY", "REPLAY"]
FrostLevel = Literal["OK", "WARNING", "CRITICAL"]
HumidityLevel = Literal["OK", "LOW", "HIGH"]
AlertType = Literal["FROST", "HUMIDITY_HIGH", "HUMIDITY_LOW"]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True)


class Reason(CamelModel):
    code: str
    text: str
    source: Literal["sensor", "system"]


class SensorReadingOut(CamelModel):
    """Shared contract (sensors-alerts service) + dewPointC for the chart."""
    parcel_id: str
    timestamp: datetime
    temperature_c: float
    humidity_pct: float
    dew_point_c: float = Field(description="°C, Magnus formula")
    min_temperature_c: float | None = Field(None, description="Lowest in this point's stretch of time (long charts)")
    max_temperature_c: float | None = Field(None, description="Highest in this point's stretch of time (long charts)")


class FrostAssessment(CamelModel):
    frost_level: FrostLevel
    score: int
    priority: Priority | Literal["none"]
    title: str
    message: str = Field(description="Recommendation for the farmer")
    reasons: list[Reason]


class SensorLatestOut(SensorReadingOut):
    """Shared contract (parcelId, timestamp, temperatureC, humidityPct, dewPointC, frostLevel) + our additions."""
    frost_level: FrostLevel
    crop: str | None = Field(None, description="Crop key the sensors service applies thresholds for")
    humidity_level: HumidityLevel | None = Field(None, description="Against the crop's humidity range")
    mode: Mode = Field(description="Simulator mode, as reported by sensors-alerts")
    drop_last_hour_c: float | None = Field(description="How much colder than an hour ago (reading time); <0 = warming")
    frost: FrostAssessment


class SensorParcelOut(CamelModel):
    """A sensor location as configured in sensors-alerts, with its latest reading."""
    id: str
    name: str
    crop: str | None = None
    latest: SensorLatestOut | None = Field(description="null until the sensor sends its first reading")


class AlertOut(CamelModel):
    """Shared contract + priority and title. Level OK is the all-clear; humidity alerts are WARNING or OK."""
    parcel_id: str
    parcel_name: str
    crop: str | None = None
    type: AlertType = "FROST"
    level: FrostLevel
    temperature_c: float
    humidity_pct: float
    dew_point_c: float
    timestamp: datetime
    message: str
    priority: Priority
    title: str


class DemoOut(CamelModel):
    parcel_id: str | None = None
    mode: Mode
    message: str


# ---------- parcels and satellite imagery ----------

Sector = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW", "C", "scattered"]
WarningCode = Literal["low_pixel_count", "low_vegetation", "possible_cloud", "whole_field_drop", "stale_previous"]


class ParcelOut(CamelModel):
    parcel_id: str = Field(description="Cadastral number; fictive in the demo when idsFictive is true")
    user_id: int
    name: str
    crop: str | None = Field(None, description="Crop key, as in sensors-alerts")
    crop_confirmed: bool = Field(description="false = assumed from the satellite season curve")
    ids_fictive: bool
    lpis_parcel: str | None = Field(None, description="Agricultural parcel in LPIS, once that system exists")
    geometry: dict | None = Field(None, description="GeoJSON Polygon in [lon, lat]; null = no satellite analysis")
    note: str | None = None


class ImageryWarning(CamelModel):
    code: WarningCode
    text: str


class ImageryResultBase(CamelModel):
    """One satellite scene of a parcel, as written by imagery/analyze.py (see imagery/README.md)."""
    scene_date: date = Field(description="Day the satellite took the picture")
    scene_id: str
    ndvi_median: float
    ndmi_median: float | None = None
    affected_pct: float = Field(description="Share of the visible parcel in weak zones")
    affected_sector: Sector | None = Field(None, description="Where the main weak zone is; null = no weak zone")
    zone_count: int
    zone_center: list[float] | None = Field(None, description="[lon, lat] of a pixel of the main weak zone")
    valid_pct: float = Field(description="Share of the parcel seen without clouds")
    prev_scene_date: date | None = None
    median_change: float | None = None
    ndmi_change: float | None = None
    declined_pct: float | None = None
    zone_confirmed: bool | None = Field(None, description="Main zone overlaps weak pixels of the previous scene")
    overlay_path: str
    photo_path: str
    overlay_bounds: list[float] = Field(description="[south, west, north, east]; Leaflet: [[S, W], [N, E]]")
    warnings: list[ImageryWarning]


class ImageryResultOut(ImageryResultBase):
    rules_version: str = Field(description="Fingerprint of the analysis code that produced this result")


class ImagerySkippedOut(CamelModel):
    scene_date: date
    scene_id: str
    valid_pct: float
    reason: str


class ImageryAtDateOut(CamelModel):
    parcel_id: str
    day: date = Field(description="The day asked for")
    result: ImageryResultOut | None = Field(description="Newest result taken on that day or before; null if none")
    days_old: int | None = Field(None, description="Days between the picture and the day asked for")
    skipped_since: list[ImagerySkippedOut] = Field(description="Scenes skipped for clouds after the result, up to the day")


class ImageryHistoryOut(CamelModel):
    parcel_id: str
    start: date
    end: date
    results: list[ImageryResultOut]
    skipped: list[ImagerySkippedOut]


class ImageryResultIn(ImageryResultBase):
    parcel_id: str


class ImagerySkippedIn(ImagerySkippedOut):
    parcel_id: str


class ImageryFileIn(CamelModel):
    """The whole imagery/out/imagery.json."""
    rules_version: str
    results: list[ImageryResultIn]
    skipped: list[ImagerySkippedIn]


class ImageryImportOut(CamelModel):
    new_scenes: int = Field(description="(parcel, date) pairs that were not in the database before")


class ImageryRunOut(CamelModel):
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "ok", "failed"]
    new_scenes: int | None = None
    newest_scene: date | None = None
    error: str | None = None


class ImageryStatusOut(CamelModel):
    running: bool
    last_run: ImageryRunOut | None = None
    last_good_run: ImageryRunOut | None = None
    next_run_at: datetime | None = Field(None, description="Next daily run; null when only manual runs are on")
