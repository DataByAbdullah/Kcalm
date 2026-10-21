from datetime import date, datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HabitCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    start_date: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("name cannot be blank")
        return value


class HabitUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for key in ("name", "active"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if self.name is not None:
            self.name = HabitCreateRequest.name_not_blank(self.name)
        return self


class HabitCompletionRequest(BaseModel):
    completed: bool = Field(strict=True)


class HabitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    start_date: date
    active: bool
    created_at: datetime
    updated_at: datetime


class HabitDailyResponse(HabitResponse):
    date: date
    completed: bool
    scheduled: bool


class HabitListResponse(BaseModel):
    items: list[HabitDailyResponse]
    total: int
    limit: int
    offset: int


class HabitDayResponse(BaseModel):
    date: date
    completed: bool


class HabitHistoryResponse(BaseModel):
    habit_id: UUID
    items: list[HabitDayResponse]
