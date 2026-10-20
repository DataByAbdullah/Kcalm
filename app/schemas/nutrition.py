from pydantic import BaseModel, Field
from datetime import date
from app.core.enums import ActivityLevel, Goal, Sex
from app.nutrition.constants import MAX_TARGET_RATE


class NutritionCalculationRequest(BaseModel):
    age: int = Field(ge=13, le=120)
    sex: Sex
    height_cm: float = Field(ge=50, le=260)
    weight_kg: float = Field(ge=20, le=500)
    activity_level: ActivityLevel
    goal: Goal
    target_rate: float | None = Field(default=None, gt=0, le=MAX_TARGET_RATE)


class MacroTargetsResponse(BaseModel):
    protein_g: float
    carbs_g: float
    fat_g: float


class NutritionCalculationResponse(BaseModel):
    bmr: float
    tdee: float
    target_calories: float
    macros: MacroTargetsResponse


class MicronutrientTargetResponse(BaseModel):
    code: str
    name: str
    target: float
    unit: str
    minimum_target: float | None
    upper_limit: float | None
    upper_limit_unit: str | None
    target_type: str
    upper_limit_type: str | None
    age_min: int
    age_max: int
    sex: Sex
    source: str
    source_url: str
    source_version: str
    note: str | None


class MicronutrientTargetsResponse(BaseModel):
    micronutrients: list[MicronutrientTargetResponse]


class DailyIntakeResponse(BaseModel):
    date: date
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float

class MicronutrientActualResponse(BaseModel):
    code: str
    name: str
    actual: float
    target: float
    unit: str
    percentage: float


class DailyMicronutrientIntakeResponse(BaseModel):
    date: date
    micronutrients: list[MicronutrientActualResponse]