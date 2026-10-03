"""API contracts.

Input:  VisionReport (Coder 1, drone analysis), FieldReport (Coder 2, soil/weather), SensorReadingIn.
Output: ParcelOut, SensorLatestOut, SensorReadingOut, AlertOut.
All analysis fields are optional: send whatever your module can compute.
JSON field names are camelCase (shared contract); inputs also accept snake_case.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Priority = Literal["high", "medium", "low"]
Mode = Literal["NORMAL", "FROST", "REPLAY"]
FrostLevel = Literal["NONE", "LOW", "MEDIUM", "HIGH"]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True)


# ---------- input ----------

class ParcelIn(CamelModel):
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
    """Coder 1: result of the drone image analysis for the whole parcel."""
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
    """Coder 2: soil sensors and weather for the parcel."""
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
    source: Literal["vision", "field", "sensor", "system"]


class Action(CamelModel):
    type: str = Field(description="protect_from_frost | irrigate | treat_disease | treat_pests | remove_weeds | harvest | fertilize | fly_drone | check_sensors")
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


class SensorReadingIn(CamelModel):
    """Real sensors (or another module's simulator) post readings here."""
    timestamp: datetime | None = Field(None, description="Defaults to now")
    temperature: float = Field(description="Air temperature, °C")
    humidity: float = Field(ge=0, le=100, description="Relative humidity, %")
    wind_speed: float | None = Field(None, ge=0, description="m/s")
    soil_temperature: float | None = Field(None, description="°C")


class SensorReadingOut(CamelModel):
    timestamp: datetime
    temperature: float
    humidity: float
    wind_speed: float | None
    soil_temperature: float | None
    dew_point: float = Field(description="°C, Magnus formula")
    frost_level: FrostLevel
    trend: float | None = Field(description="Temperature change, °C/h")
    predicted_temperature_1h: float | None = Field(alias="predictedTemperature1h")
    source: str = Field(description="simulated | sensor | replay:<original time>")


class FrostAssessment(CamelModel):
    frost_level: FrostLevel
    score: int
    priority: Priority | Literal["none"]
    title: str
    message: str = Field(description="Recommendation for the farmer")
    reasons: list[Reason]


class SensorLatestOut(SensorReadingOut):
    parcel_id: int
    mode: Mode
    frost: FrostAssessment


class AlertOut(CamelModel):
    id: int
    parcel_id: int
    created_at: datetime
    type: str
    level: FrostLevel
    priority: Priority
    title: str
    message: str
    reasons: list[Reason]


class DemoOut(CamelModel):
    parcel_id: int | None = None
    mode: Mode | None = None
    message: str


class ParcelOut(CamelModel):
    id: int
    name: str
    crop: str
    area_ha: float | None
    planted_at: date | None
    lat: float | None
    lon: float | None
    boundary: list[list[float]] | None
    mode: Mode
    sensors: SensorLatestOut | None
    status: Literal["ok", "warning", "critical", "no_data"]
    health_score: int | None = Field(description="0..100, null if no drone data")
    priority: Priority | Literal["none"]
    summary: str
    actions: list[Action] = Field(description="Sorted by score, most urgent first")
    metrics: Metrics
    zones: list[Zone]
    updated_at: UpdatedAt
