from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import WeeklyMealPlanStatus
from app.schemas.meal_plan import DailySolverPreviewRequest, MealPlanResponse


class WeeklyMealPlanCreateRequest(DailySolverPreviewRequest):
    start_date: date


class WeeklyMealPlanSummaryResponse(BaseModel):
    weekly_plan_id: UUID
    start_date: date
    end_date: date
    status: WeeklyMealPlanStatus
    daily_plan_count: int
    created_at: datetime
    updated_at: datetime


class WeeklyMealPlanResponse(BaseModel):
    weekly_plan_id: UUID
    start_date: date
    end_date: date
    status: WeeklyMealPlanStatus
    daily_plans: list[MealPlanResponse]
    created_at: datetime
    updated_at: datetime


class WeeklyMealPlanListResponse(BaseModel):
    items: list[WeeklyMealPlanSummaryResponse]
    total: int


class WeeklyGroceryPreviewItemResponse(BaseModel):
    food_id: UUID
    food_name: str
    total_grams: float
    source: str | None = None
    source_food_id: str | None = None
    category: str | None = None


class WeeklyGroceryPreviewResponse(BaseModel):
    weekly_plan_id: UUID
    start_date: date
    end_date: date
    items: list[WeeklyGroceryPreviewItemResponse]
