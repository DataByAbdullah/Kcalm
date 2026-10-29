from datetime import date

from pydantic import BaseModel, Field


class AchievementResponse(BaseModel):
    code: str
    name: str
    current: int
    target: int
    unit: str
    unlocked: bool


class AchievementsResponse(BaseModel):
    items: list[AchievementResponse]


class InsightResponse(BaseModel):
    code: str
    message: str
    values: dict[str, float | int | None]


class CalorieAdherenceResponse(BaseModel):
    score: float | None = Field(ge=0, le=100)
    average_actual_calories: float | None
    average_target_calories: float | None
    logged_days: int


class MacroBalanceResponse(BaseModel):
    score: float | None = Field(ge=0, le=100)
    protein_adherence_percent: float | None
    carbs_adherence_percent: float | None
    fat_adherence_percent: float | None


class NutritionDataCompletenessResponse(BaseModel):
    logged_days: int
    days_in_range: int
    percentage: float
    scored_days: int
    unscored_days: int
    planned_meals: int
    logged_planned_meals: int
    meal_logging_percentage: float | None


class NutritionSummaryResponse(BaseModel):
    formula_version: str
    nutrition_score: float | None = Field(ge=0, le=100)
    unavailable_reason: str | None
    target_sources: list[str]
    calorie_adherence: CalorieAdherenceResponse
    macro_balance: MacroBalanceResponse
    data_completeness: NutritionDataCompletenessResponse


class InsightsResponse(BaseModel):
    start_date: date
    end_date: date
    logged_nutrition_days: int
    items: list[InsightResponse]
    nutrition_summary: NutritionSummaryResponse
