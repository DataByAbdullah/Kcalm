from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WeightLogRequest(BaseModel):
    weight_kg: float = Field(ge=20, le=500, allow_inf_nan=False)


class WeightLogResponse(WeightLogRequest):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    log_date: date
    created_at: datetime
    updated_at: datetime


class WeightProgressResponse(BaseModel):
    starting_weight_kg: float | None
    current_weight_kg: float | None
    target_weight_kg: float | None
    change_kg: float | None
    remaining_kg: float | None
    progress_percent: float | None


class WeightHistoryResponse(BaseModel):
    items: list[WeightLogResponse]
    total: int
    limit: int
    offset: int
    progress: WeightProgressResponse


class StepLogRequest(BaseModel):
    steps: int = Field(ge=0, le=200000, strict=True)


class StepLogResponse(StepLogRequest):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    log_date: date
    source: str = "manual"
    created_at: datetime
    updated_at: datetime


class StepHistoryResponse(BaseModel):
    items: list[StepLogResponse]
    total: int
    limit: int
    offset: int
