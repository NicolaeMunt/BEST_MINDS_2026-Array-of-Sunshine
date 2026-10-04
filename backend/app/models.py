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
    """A sensor location with its latest reading: a demo sensor of sensors-alerts or the user's own field."""
    id: str
    name: str
    crop: str | None = None
    own: bool = Field(False, description="The signed-in user's own field (F1, F2, ...), not a demo sensor")
    area_ha: float | None = None
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


# ---------- accounts ----------
# Inputs are plain strings: accounts.py checks them and answers in Romanian, field by field.

class RegisterIn(CamelModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    password: str = ""


class LoginIn(CamelModel):
    email: str = ""
    password: str = ""


class ProfileIn(CamelModel):
    name: str = ""
    email: str = ""
    phone: str = ""


class PasswordIn(CamelModel):
    current: str = ""
    new: str = ""


class UserOut(CamelModel):
    id: int
    name: str
    email: str
    phone: str
    role: Literal["user", "admin"] = "user"
    created_at: datetime


class AdminUserOut(UserOut):
    field_count: int
    total_ari: float = Field(description="Total area of the user's fields, in ares")


class SessionOut(CamelModel):
    token: str = Field(description="Send it back as 'Authorization: Bearer <token>'")
    user: UserOut


class FieldIn(CamelModel):
    """A field as written in the official document; entered by an administrator."""
    name: str = ""
    crop: str = ""
    area_ari: str | float | None = Field(None, description="Area from the document, in ares (1 ha = 100 ari)")
    cadastral_number: str = ""
    location: str = Field("", description="Village and district")
    doc_type: str = Field("", description="titlu | extras | vanzare | donatie | mostenire | arenda | altul")
    doc_number: str = ""
    doc_date: str = Field("", description="YYYY-MM-DD")


class FieldOut(CamelModel):
    id: str = Field(description="Parcel ID in sensors-alerts: F1, F2, ...")
    user_id: int
    name: str
    crop: str
    area_ari: float | None = None
    area_ha: float | None = None
    cadastral_number: str | None = None
    location: str | None = None
    doc_type: str | None = None
    doc_number: str | None = None
    doc_date: str | None = None
    created_at: datetime


class AdminUserDetailOut(CamelModel):
    user: UserOut
    fields: list[FieldOut]


class DemoOut(CamelModel):
    parcel_id: str | None = None
    mode: Mode
    message: str
