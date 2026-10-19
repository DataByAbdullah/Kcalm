from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.enums import MealPlanStatus
from app.meal_planning.solver import SolverStatus, ToleranceStatus


MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class MealSlotRequest(BaseModel):
    meal_type: MealType
    required: bool = True


class DailySolverPreviewRequest(BaseModel):
    meal_slots: list[MealSlotRequest] | None = Field(default=None, min_length=1)
    max_total_time_minutes: int | None = Field(default=None, ge=0)
    require_complete_nutrition: bool = True
    required_nutrient_codes: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[UUID] = Field(default_factory=list)
    required_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    solver_time_limit_seconds: float | None = Field(default=None, gt=0, le=5)

    @field_validator("meal_slots")
    @classmethod
    def meal_slots_must_be_unique(
        cls,
        value: list[MealSlotRequest] | None,
    ) -> list[MealSlotRequest] | None:
        if value is None:
            return value
        meal_types = [slot.meal_type for slot in value]
        if len(meal_types) != len(set(meal_types)):
            raise ValueError("meal_slots cannot contain duplicate meal_type values")
        return value


class SelectedMealResponse(BaseModel):
    meal_type: str
    recipe_id: UUID
    recipe_name: str
    serving_amount: float
    nutrition: dict[str, float]


class SolverMicronutrientTargetResponse(BaseModel):
    code: str
    name: str
    target: float
    unit: str
    minimum_target: float | None
    upper_limit: float | None
    upper_limit_type: str | None


class SolverTargetsResponse(BaseModel):
    calories: float
    protein_g: float
    carbohydrates_g: float
    fat_g: float
    micronutrients: list[SolverMicronutrientTargetResponse]


class NutritionDeviationResponse(BaseModel):
    nutrient_code: str
    nutrient_name: str
    target: float
    actual: float
    unit: str
    deviation_amount: float
    deviation_percent: float
    tolerance_lower: float
    tolerance_upper: float
    status: ToleranceStatus


class MicronutrientCoverageResponse(BaseModel):
    nutrient_code: str
    nutrient_name: str
    target: float
    actual: float
    unit: str
    coverage_percent: float
    met: bool
    upper_limit: float | None
    upper_limit_type: str | None
    upper_limit_applicable: bool
    upper_limit_exceeded: bool


class DailySolverPreviewResponse(BaseModel):
    status: SolverStatus
    meals: list[SelectedMealResponse]
    daily_totals: dict[str, float]
    targets: SolverTargetsResponse
    deviations: list[NutritionDeviationResponse]
    micronutrient_coverage: list[MicronutrientCoverageResponse]
    within_preferred_tolerance: bool
    objective_value: int | None
    infeasibility_reasons: list[str]
    solve_time_seconds: float
    candidate_count: int


class MealPlanCreateRequest(DailySolverPreviewRequest):
    plan_date: date | None = None


class MealSwapRequest(BaseModel):
    max_total_time_minutes: int | None = Field(default=None, ge=0)
    require_complete_nutrition: bool = True
    required_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[UUID] = Field(default_factory=list)
    solver_time_limit_seconds: float | None = Field(default=None, gt=0, le=5)
    different_protein: bool = False
    eating_out: bool = False


class PersistedMealPlanItemResponse(BaseModel):
    id: UUID
    meal_type: str
    recipe_id: UUID
    recipe_name: str
    servings: float
    position: int
    nutrition: dict[str, float]


class MealPlanResponse(BaseModel):
    meal_plan_id: UUID
    plan_date: date
    status: MealPlanStatus
    solver_status: SolverStatus
    meals: list[PersistedMealPlanItemResponse]
    daily_totals: dict[str, float]
    targets: SolverTargetsResponse
    deviations: list[NutritionDeviationResponse]
    micronutrient_coverage: list[MicronutrientCoverageResponse]
    within_preferred_tolerance: bool
    objective_value: int | None
    solve_time_seconds: float
    candidate_count: int
    created_at: datetime
    updated_at: datetime


class MealPlanSummaryResponse(BaseModel):
    meal_plan_id: UUID
    plan_date: date
    status: MealPlanStatus
    solver_status: SolverStatus
    daily_totals: dict[str, float]
    within_preferred_tolerance: bool
    created_at: datetime
    updated_at: datetime


class MealPlanListResponse(BaseModel):
    items: list[MealPlanSummaryResponse]
    total: int
