"""API contracts: sensor readings, frost assessment and alerts (the data comes from the sensors-alerts
service; readings are also stored here with their timestamps).
JSON field names are camelCase (shared contract); inputs also accept snake_case.
"""
from datetime import datetime
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
