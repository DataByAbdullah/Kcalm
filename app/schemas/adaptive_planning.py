from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.meal_plan import DailySolverPreviewRequest, DailySolverPreviewResponse, MealPlanResponse


class AdaptivePlanRequest(DailySolverPreviewRequest):
    pass


class AdaptivePolicyResponse(BaseModel):
    policy_version: str
    compensation_fraction: float
    max_adjustment_kcal: float
    max_adjustment_percent: float
    minimum_adjusted_calories: float


class AdaptiveTargetResponse(BaseModel):
    source_plan_id: UUID
    base_calorie_target: float
    previous_day_actual_calories: float
    previous_day_calorie_deviation: float
    compensation_fraction: float
    raw_compensation_amount: float
    compensation_amount: float
    adjusted_calorie_target: float
    base_macro_targets: dict[str, float]
    adjusted_macro_targets: dict[str, float]
    micronutrient_strategy: str
    safety_caps_applied: list[str] = Field(default_factory=list)
    policy_version: str


class AdaptivePreviewResponse(BaseModel):
    source_plan_id: UUID
    next_day_date: str
    actual_totals: dict[str, float]
    target_totals: dict[str, float]
    deviation: dict[str, float]
    micronutrient_deviation: dict[str, float]
    policy: AdaptivePolicyResponse
    adjusted_targets: AdaptiveTargetResponse
    solver_preview: DailySolverPreviewResponse


class AdaptivePlanResponse(BaseModel):
    source_plan_id: UUID
    adaptation: AdaptiveTargetResponse
    plan: MealPlanResponse
