from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.enums import MealLogSourceType, MealLogStatus, MealLogType
from app.schemas.meal_plan import SolverTargetsResponse


class MealLogRequest(BaseModel):
    type: MealLogType
    source_type: MealLogSourceType | None = None
    food_id: UUID | None = None
    quantity_grams: float | None = Field(default=None, gt=0)
    recipe_id: UUID | None = None
    servings: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_log_shape(self) -> Self:
        if self.type == MealLogType.ATE_AS_PLANNED:
            if any(
                value is not None
                for value in (
                    self.source_type,
                    self.food_id,
                    self.quantity_grams,
                    self.recipe_id,
                    self.servings,
                )
            ):
                raise ValueError("ate_as_planned logs cannot include correction fields")
            return self

        if self.source_type == MealLogSourceType.FOOD:
            if self.food_id is None or self.quantity_grams is None:
                raise ValueError("food corrections require food_id and quantity_grams")
            if self.recipe_id is not None or self.servings is not None:
                raise ValueError("food corrections cannot include recipe_id or servings")
            return self

        if self.source_type == MealLogSourceType.RECIPE:
            if self.recipe_id is None or self.servings is None:
                raise ValueError("recipe corrections require recipe_id and servings")
            if self.food_id is not None or self.quantity_grams is not None:
                raise ValueError("recipe corrections cannot include food_id or quantity_grams")
            return self

        raise ValueError("corrected logs require source_type")


class MealLogNutrientResponse(BaseModel):
    code: str
    name: str
    amount: float
    unit: str


class MealLogResponse(BaseModel):
    meal_log_id: UUID
    meal_plan_id: UUID
    meal_plan_item_id: UUID
    log_date: date
    type: MealLogType
    status: MealLogStatus
    source_type: MealLogSourceType | None
    food_id: UUID | None
    recipe_id: UUID | None
    quantity_grams: float | None
    servings: float | None
    nutrient_complete: bool
    nutrients: list[MealLogNutrientResponse]
    known_nutrient_codes: list[str]
    missing_nutrient_codes: list[str]
    created_at: datetime
    updated_at: datetime


class AdherenceSummaryResponse(BaseModel):
    planned_meals_count: int
    logged_meals_count: int
    unlogged_meals_count: int
    ate_as_planned_count: int
    corrected_count: int
    adherence_percent: float


class MealPlanActualSummaryResponse(BaseModel):
    meal_plan_id: UUID
    plan_date: date
    planned_totals: dict[str, float]
    actual_totals: dict[str, float]
    targets: SolverTargetsResponse
    difference_actual_vs_planned: dict[str, float]
    difference_actual_vs_target: dict[str, float]
    actual_known_nutrient_codes: list[str]
    missing_actual_target_nutrient_codes: list[str]
    adherence: AdherenceSummaryResponse
