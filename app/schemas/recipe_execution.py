from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import RecipeExecutionStatus, RecipeStepPhase


class RecipeExecutionStartRequest(BaseModel):
    servings: float = Field(gt=0)


class RecipeExecutionProgressRequest(BaseModel):
    current_step_index: int = Field(ge=0)


class RecipeExecutionIngredientSummaryResponse(BaseModel):
    ingredient_id: UUID | None
    food_id: UUID | None
    food_name: str
    quantity_grams: float
    display_quantity: str | None = None
    display_unit: str | None = None
    preparation_note: str | None = None


class RecipeExecutionProgressResponse(BaseModel):
    completed_steps: int
    total_steps: int
    percent_complete: float


class RecipeExecutionStepResponse(BaseModel):
    id: UUID
    step_index: int
    recipe_step_position: int
    instruction: str
    phase: RecipeStepPhase
    duration_seconds: int | None
    timer_required: bool
    timer_seconds: int | None
    completed: bool
    completed_at: datetime | None
    equipment: list[str]
    ingredients: list[dict]
    cue_action: str | None
    animation_key: str | None
    media_asset_key: str | None
    visual_cue: str | None
    timer_started_at: datetime | None
    timer_completed_at: datetime | None


class RecipeExecutionSessionResponse(BaseModel):
    session_id: UUID
    recipe_id: UUID | None
    meal_plan_id: UUID | None
    meal_plan_item_id: UUID | None
    recipe_name: str
    servings: float
    status: RecipeExecutionStatus
    current_step_index: int
    total_estimated_time_minutes: int | None
    required_equipment: list[str]
    ingredients: list[RecipeExecutionIngredientSummaryResponse]
    step_count: int
    progress: RecipeExecutionProgressResponse
    steps: list[RecipeExecutionStepResponse]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
