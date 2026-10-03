"""API contracts.

Input:  VisionReport (drone analysis), FieldReport (soil / weather).
Output: ParcelOut, SensorLatestOut, SensorReadingOut, AlertOut (sensor data comes from the sensors-alerts service).
All analysis fields are optional: send whatever your module can compute.
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


# ---------- input ----------

class ParcelIn(CamelModel):
    id: str | None = Field(None, description="e.g. P4; must match the sensors-alerts config. Generated if omitted")
    name: str
    crop: str = "wheat"
    area_ha: float | None = None
    planted_at: date | None = None
    lat: float | None = None
    lon: float | None = None
    boundary: list[list[float]] | None = Field(None, description="Polygon [[lon, lat], ...]")


class Zone(CamelModel):
    """One cell of the drone grid, passed through to the frontend map."""
    model_config = ConfigDict(extra="allow")  # merged with CamelModel config
    id: str
    lat: float | None = None
    lon: float | None = None
    ndvi: float | None = None
    issue: str | None = Field(None, description="water_stress | disease | pest | weed | null")


class VisionReport(CamelModel):
    """Result of the drone image analysis for the whole parcel."""
    model_config = ConfigDict(extra="allow")  # merged with CamelModel config
    captured_at: datetime | None = Field(None, description="Flight time; defaults to now")
    ndvi_mean: float | None = Field(None, ge=-1, le=1)
    water_stress_pct: float | None = Field(None, ge=0, le=100, description="% of area with water stress")
    disease: str | None = Field(None, description="e.g. rust, septoria, powdery_mildew, fusarium; null/none = healthy")
    disease_confidence: float | None = Field(None, ge=0, le=1)
    disease_area_pct: float | None = Field(None, ge=0, le=100)
    pest_area_pct: float | None = Field(None, ge=0, le=100)
    weed_area_pct: float | None = Field(None, ge=0, le=100)
    ripeness: float | None = Field(None, ge=0, le=1, description="0 = green, 1 = ready to harvest")
    zones: list[Zone] = []


class FieldReport(CamelModel):
    """Soil sensors and weather for the parcel."""
    model_config = ConfigDict(extra="allow")  # merged with CamelModel config
    measured_at: datetime | None = Field(None, description="Measurement time; defaults to now")
    soil_moisture_pct: float | None = Field(None, ge=0, le=100)
    air_temp_c: float | None = None
    humidity_pct: float | None = Field(None, ge=0, le=100)
    temp_max_forecast_c: float | None = Field(None, description="Max temperature in the next 48h")
    rain_forecast_mm_48h: float | None = Field(None, ge=0, alias="rainForecastMm48h")


# ---------- output ----------

class Reason(CamelModel):
    code: str
    text: str
    source: Literal["vision", "field", "sensor", "satellite", "system"]


class Action(CamelModel):
    type: str = Field(description="protect_from_frost | check_sensor_service | inspect_weak_zone | irrigate | treat_disease | treat_pests | remove_weeds | harvest | fertilize | fly_drone | check_sensors")
    title: str
    score: int = Field(ge=0, le=100)
    priority: Priority
    reasons: list[Reason]


class Metrics(CamelModel):
    ndvi_mean: float | None = None
    water_stress_pct: float | None = None
    disease: str | None = None
    disease_confidence: float | None = None
    disease_area_pct: float | None = None
    pest_area_pct: float | None = None
    weed_area_pct: float | None = None
    ripeness: float | None = None
    soil_moisture_pct: float | None = None
    air_temp_c: float | None = None
    humidity_pct: float | None = None
    temp_max_forecast_c: float | None = None
    rain_forecast_mm_48h: float | None = Field(None, alias="rainForecastMm48h")


class UpdatedAt(CamelModel):
    vision: datetime | None = None
    field: datetime | None = None
    imagery: datetime | None = None


class SensorReadingOut(CamelModel):
    """Shared contract (sensors-alerts service) + dewPointC for the chart."""
    parcel_id: str
    timestamp: datetime
    temperature_c: float
    humidity_pct: float
    dew_point_c: float = Field(description="°C, Magnus formula")


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


class ImageryOut(CamelModel):
    """Latest satellite scene of the parcel, as posted by the imagery pipeline (imagery/push.py)."""
    model_config = ConfigDict(extra="allow")  # merged with CamelModel config
    scene_date: date
    ndvi_median: float | None = None
    affected_pct: float | None = Field(None, description="% of the visible parcel in weak-vegetation zones")
    affected_sector: str | None = Field(None, description="N, NE, ... | C | scattered | null")
    zone_count: int | None = None
    zone_center: list[float] | None = Field(None, description="[lon, lat] of the largest weak zone")
    zone_confirmed: bool | None = None
    overlay_path: str | None = Field(None, description="Transparent weak-zone overlay, served by this API")
    photo_path: str | None = Field(None, description="True-colour photo with the same bounds")
    overlay_bounds: list[float] | None = Field(None, description="[south, west, north, east]")
    warnings: list[dict] = []


class ParcelOut(CamelModel):
    id: str
    name: str
    crop: str
    area_ha: float | None
    planted_at: date | None
    lat: float | None
    lon: float | None
    boundary: list[list[float]] | None
    sensors: SensorLatestOut | None
    sensors_status: Literal["ok", "no_readings", "unavailable"]
    status: Literal["ok", "warning", "critical", "no_data"]
    health_score: int | None = Field(description="0..100, null if no drone data")
    priority: Priority | Literal["none"]
    summary: str
    actions: list[Action] = Field(description="Sorted by score, most urgent first")
    metrics: Metrics
    zones: list[Zone]
    imagery: ImageryOut | None = None
    updated_at: UpdatedAt
