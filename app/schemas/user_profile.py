from datetime import time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.core.enums import ActivityLevel, Goal, Sex


def normalize_text_items(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return value

    normalized_items: list[str] = []
    seen_items: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            normalized = str(item).strip().lower()
        else:
            normalized = item.strip().lower()
        if normalized and normalized not in seen_items:
            normalized_items.append(normalized)
            seen_items.add(normalized)
    return normalized_items


class ProfileScheduleValidation(BaseModel):
    @field_validator("usual_wake_time", "usual_sleep_time", check_fields=False)
    @classmethod
    def local_time_required(cls, value):
        if value is None or value.tzinfo is not None:
            raise ValueError("Use a non-null local time without an offset; specify timezone separately.")
        return value

    @field_validator("timezone", check_fields=False)
    @classmethod
    def valid_timezone_required(cls, value):
        if value is None:
            raise ValueError("timezone cannot be null.")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must identify a valid IANA time zone.") from exc
        return value

    @model_validator(mode="after")
    def wake_and_sleep_must_differ(self):
        if self.usual_wake_time is not None and self.usual_sleep_time is not None:
            if self.usual_wake_time == self.usual_sleep_time:
                raise ValueError("Wake and sleep times must be different.")
        return self


class UserProfileCreateRequest(ProfileScheduleValidation):
    age: int = Field(ge=13, le=120)
    sex: Sex
    height_cm: float = Field(ge=50, le=260)
    weight_kg: float = Field(ge=20, le=500)
    target_weight_kg: float | None = Field(default=None, ge=20, le=500)
    activity_level: ActivityLevel
    goal: Goal
    target_rate: float | None = Field(default=None, gt=0, le=2.5)
    max_cooking_minutes: int = Field(ge=1, le=240)
    meals_per_day: int = Field(ge=2, le=5)
    usual_wake_time: time = time(7)
    usual_sleep_time: time = time(23)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    allergies: list[str] = Field(default_factory=list)
    dietary_restrictions: list[str] = Field(default_factory=list)
    preferred_foods: list[str] = Field(default_factory=list)
    disliked_foods: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)

    @field_validator(
        "allergies",
        "dietary_restrictions",
        "preferred_foods",
        "disliked_foods",
        "equipment",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value: Any) -> Any:
        return normalize_text_items(value)


class UserProfileUpdateRequest(ProfileScheduleValidation):
    age: int | None = Field(default=None, ge=13, le=120)
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, ge=50, le=260)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    target_weight_kg: float | None = Field(default=None, ge=20, le=500)
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    target_rate: float | None = Field(default=None, gt=0, le=2.5)
    max_cooking_minutes: int | None = Field(default=None, ge=1, le=240)
    meals_per_day: int | None = Field(default=None, ge=2, le=5)
    usual_wake_time: time | None = None
    usual_sleep_time: time | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    allergies: list[str] | None = None
    dietary_restrictions: list[str] | None = None
    preferred_foods: list[str] | None = None
    disliked_foods: list[str] | None = None
    equipment: list[str] | None = None

    @field_validator("meals_per_day")
    @classmethod
    def meal_count_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("meals_per_day cannot be null.")
        return value

    @field_validator(
        "allergies",
        "dietary_restrictions",
        "preferred_foods",
        "disliked_foods",
        "equipment",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value: Any) -> Any:
        if value is None:
            return []
        return normalize_text_items(value)


class UserProfileResponse(BaseModel):
    age: int
    sex: Sex
    height_cm: float
    weight_kg: float
    target_weight_kg: float | None
    activity_level: ActivityLevel
    goal: Goal
    target_rate: float | None
    max_cooking_minutes: int
    meals_per_day: int
    usual_wake_time: time
    usual_sleep_time: time
    timezone: str
    allergies: list[str]
    dietary_restrictions: list[str]
    preferred_foods: list[str]
    disliked_foods: list[str]
    equipment: list[str]

    @computed_field
    @property
    def weight_direction(self) -> Literal["lose_weight", "gain_weight", "maintain_weight"] | None:
        if self.target_weight_kg is None:
            return None
        if self.target_weight_kg < self.weight_kg:
            return "lose_weight"
        if self.target_weight_kg > self.weight_kg:
            return "gain_weight"
        return "maintain_weight"
