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
AlertType = Literal["FROST", "HUMIDITY_HIGH", "HUMIDITY_LOW", "IRRIGATION", "SOWING"]


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
    precipitation_mm: float | None = Field(None, description="Rain since the previous reading, mm; null if not reported")
    soil_temperature_c: float | None = Field(None, description="Soil at ~5 cm; null without a soil probe")
    soil_moisture_pct: float | None = Field(None, description="Soil water at ~20 cm, % of the soil volume; null without a soil probe")
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
    humidity_level: HumidityLevel | None = Field(None, description="HIGH: disease risk (damp hours); LOW: dry, hot air")
    mode: Mode = Field(description="Simulator mode, as reported by sensors-alerts")
    phase: str | None = Field(None, description="The crop's phase on the reading's day")
    frost_warning_c: float | None = Field(None, description="Frost thresholds of that phase; null = frost does no harm then")
    frost_critical_c: float | None = None
    disease: str | None = Field(None, description="The disease the damp-air rule watches for that day; null outside its window")
    drop_last_hour_c: float | None = Field(description="How much colder than an hour ago (reading time); <0 = warming")
    frost: FrostAssessment


class WaterDayOut(CamelModel):
    date: date
    phase: str | None = None
    kc: float | None = Field(None, description="FAO-56 crop coefficient of the phase; null = no crop to water")
    et0_mm: float = Field(description="Reference evapotranspiration of the day (Hargreaves), mm")
    etc_mm: float = Field(description="Water the crop used that day, Kc x ET0, mm")
    rain_mm: float
    deficit_mm: float = Field(description="Water missing from the root zone at the end of the day, mm")
    measured: bool = Field(description="false: no readings that day, counted as no rain and no use")


class WateringOut(CamelModel):
    time: datetime = Field(description="Hour the soil moisture rose without rain")
    from_pct: float
    to_pct: float


class WaterStatusOut(CamelModel):
    """Whether to water on a day: from the soil probe when it reported in the last two days (a watering shows up
    in it), else from the soil water balance since 1 May (FAO-56), which takes the field as not watered."""
    date: date
    phase: str | None = None
    has_crop: bool = Field(description="false: nothing to water in this phase (not sown, harvested, dormant)")
    source: Literal["sensor", "balance"]
    soil_moisture_pct: float | None = Field(None, description="sensor: latest soil moisture at ~20 cm, %")
    threshold_pct: float | None = Field(None, description="sensor: the crop suffers below this soil moisture, %")
    field_capacity_pct: float | None = Field(None, description="sensor: the soil is full at this moisture, %")
    waterings: list[WateringOut] = Field([], description="sensor: waterings seen in the last 14 days, newest first")
    deficit_mm: float = Field(description="Water missing from the root zone, mm (1 mm = 10 m³/ha)")
    readily_available_mm: float = Field(description="The crop suffers once the deficit passes this (FAO-56 RAW)")
    total_available_mm: float = Field(description="All the water the roots can reach (FAO-56 TAW)")
    irrigate: bool = Field(description="Time to water: the deficit has passed the readily available water")
    amount_mm: float = Field(description="Least water that takes the crop out of stress, mm; 0 when no watering is needed")
    days: list[WaterDayOut] | None = Field(None, description="The day-by-day balance since 1 May (water endpoint only)")


class SensorParcelOut(CamelModel):
    """A sensor location as configured in sensors-alerts, with its latest reading and its soil water today."""
    id: str
    name: str
    crop: str | None = None
    latest: SensorLatestOut | None = Field(description="null until the sensor sends its first reading")
    water: WaterStatusOut | None = Field(None, description="null for a crop without a water balance")


class AlertOut(CamelModel):
    """Shared contract + priority and title. Level OK is the all-clear; humidity and irrigation alerts are
    WARNING or OK. IRRIGATION alerts come from the water balance here, not from sensors-alerts."""
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
    deficit_mm: float | None = Field(None, description="IRRIGATION: water missing from the soil that day, mm")


class UserOut(CamelModel):
    id: int
    name: str = Field(description="What the app shows: first and last name")
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class UserIn(CamelModel):
    first_name: str = Field("", max_length=60)
    last_name: str = Field("", max_length=60)
    email: str = Field("", max_length=120)


class CropIn(CamelModel):
    crop: str = Field(description="Crop key: wheat, corn, sunflower, orchard, vineyard")


class SowingIn(CamelModel):
    sowing_date: date | None = Field(None, description="null clears it")


class CropOptionOut(CamelModel):
    key: str
    name: str
    sown: bool = Field(description="true: the crop is sown each year, so its sowing date can be given")


class TemperatureStatOut(CamelModel):
    minutes: int = Field(description="The window, counted back from the newest reading")
    min_c: float | None = None
    mean_c: float | None = None
    max_c: float | None = None
    min_humidity_pct: float | None = None
    mean_humidity_pct: float | None = None
    max_humidity_pct: float | None = None
    readings: int


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
    sowing_date: date | None = Field(None, description="Set by the farmer; moves the calendar of spring crops")


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
    phase: str | None = Field(None, description="The crop's phase on the scene's day (crop calendar)")
    season: Literal["dormant", "establishing", "growing", "maturing", "harvested"] | None = Field(
        None, description="growing: low or falling NDVI is a warning; otherwise it is normal for the phase")


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
