from typing import Any

from pydantic import BaseModel, Field, field_validator

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


class UserProfileCreateRequest(BaseModel):
    age: int = Field(ge=13, le=120)
    sex: Sex
    height_cm: float = Field(ge=50, le=260)
    weight_kg: float = Field(ge=20, le=500)
    activity_level: ActivityLevel
    goal: Goal
    target_rate: float | None = Field(default=None, gt=0, le=2.5)
    max_cooking_minutes: int = Field(ge=1, le=240)
    meals_per_day: int = Field(ge=1, le=8)
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


class UserProfileUpdateRequest(BaseModel):
    age: int | None = Field(default=None, ge=13, le=120)
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, ge=50, le=260)
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    activity_level: ActivityLevel | None = None
    goal: Goal | None = None
    target_rate: float | None = Field(default=None, gt=0, le=2.5)
    max_cooking_minutes: int | None = Field(default=None, ge=1, le=240)
    meals_per_day: int | None = Field(default=None, ge=1, le=8)
    allergies: list[str] | None = None
    dietary_restrictions: list[str] | None = None
    preferred_foods: list[str] | None = None
    disliked_foods: list[str] | None = None
    equipment: list[str] | None = None

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
    activity_level: ActivityLevel
    goal: Goal
    target_rate: float | None
    max_cooking_minutes: int
    meals_per_day: int
    allergies: list[str]
    dietary_restrictions: list[str]
    preferred_foods: list[str]
    disliked_foods: list[str]
    equipment: list[str]
