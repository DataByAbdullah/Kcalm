from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DailyMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    water_glasses: int = Field(ge=0, le=100, strict=True)
    fruit_veg_servings: float = Field(ge=0, le=100, allow_inf_nan=False, strict=True)
    sleep_hours: float = Field(ge=0, le=24, allow_inf_nan=False, strict=True)


class DailyMetricsResponse(DailyMetricsRequest):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    log_date: date
    created_at: datetime
    updated_at: datetime


class DailyMetricsHistoryResponse(BaseModel):
    items: list[DailyMetricsResponse]
    total: int
    limit: int
    offset: int
