from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.meal_plan import MealType
from app.schemas.recipe import RecipeCandidatePreviewResponse


RequestedAIAction = Literal["find_options", "swap_meal", "unknown"]


class NaturalLanguageConstraintRequest(BaseModel):
    text: str = Field(min_length=1)
    context_meal_type: MealType | None = None


class NaturalLanguageMealConstraintLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_action: RequestedAIAction = "find_options"
    meal_type: MealType | None = None
    max_total_time_minutes: int | None = Field(default=None, ge=0, le=240)
    required_tags: list[str] = Field(default_factory=list, max_length=16)
    excluded_tags: list[str] = Field(default_factory=list, max_length=16)
    avoid_food_names: list[str] = Field(default_factory=list, max_length=16)
    preference_food_names: list[str] = Field(default_factory=list, max_length=16)
    unsupported_constraints: list[str] = Field(default_factory=list, max_length=16)
    clarification_required: bool = False
    clarification_question: str | None = Field(default=None, max_length=240)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "required_tags",
        "excluded_tags",
        "avoid_food_names",
        "preference_food_names",
        "unsupported_constraints",
    )
    @classmethod
    def values_must_not_be_blank(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.strip():
                raise ValueError("values cannot be blank")
        return values


class ResolvedAvoidFoodResponse(BaseModel):
    phrase: str
    food_id: UUID
    food_name: str
    excluded_recipe_ids: list[UUID]


class NaturalLanguageMealConstraintResponse(BaseModel):
    requested_action: RequestedAIAction
    meal_type: MealType | None
    max_total_time_minutes: int | None
    required_tags: list[str]
    excluded_tags: list[str]
    excluded_recipe_ids: list[UUID]
    avoid_food_names: list[str]
    preference_food_names: list[str]
    unsupported_constraints: list[str]
    clarification_required: bool
    clarification_question: str | None
    confidence: float | None
    resolved_avoid_foods: list[ResolvedAvoidFoodResponse]


class AIMealOptionsResponse(BaseModel):
    interpretation: NaturalLanguageMealConstraintResponse
    candidate_preview: RecipeCandidatePreviewResponse | None
