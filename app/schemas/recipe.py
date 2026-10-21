from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import RecipeStepPhase


class RecipeIngredientRequest(BaseModel):
    food_id: UUID
    quantity_grams: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    display_quantity: str | None = Field(default=None, max_length=64)
    display_unit: str | None = Field(default=None, max_length=64)
    preparation_note: str | None = None
    position: int | None = Field(default=None, ge=1)


class RecipeStepRequest(BaseModel):
    position: int | None = Field(default=None, ge=1)
    instruction: str = Field(min_length=1)
    phase: RecipeStepPhase = RecipeStepPhase.COOK
    duration_seconds: int | None = Field(default=None, ge=0)
    timer: bool = False
    timer_required: bool | None = None
    timer_seconds: int | None = Field(default=None, ge=0)
    cue_action: str | None = Field(default=None, max_length=64)
    animation_key: str | None = Field(default=None, max_length=128)
    media_asset_key: str | None = Field(default=None, max_length=128)
    visual_cue: str | None = Field(default=None, max_length=128)

    @field_validator("instruction")
    @classmethod
    def strip_instruction(cls, value: str) -> str:
        return value.strip()

    @field_validator("cue_action", "animation_key", "media_asset_key", "visual_cue")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class RecipeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    servings: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    prep_time_minutes: int = Field(ge=0)
    cook_time_minutes: int = Field(ge=0)
    difficulty: str | None = Field(default=None, max_length=64)
    instructions_summary: str | None = None
    ingredients: list[RecipeIngredientRequest] = Field(min_length=1)
    steps: list[RecipeStepRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class RecipeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    servings: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)
    prep_time_minutes: int | None = Field(default=None, ge=0)
    cook_time_minutes: int | None = Field(default=None, ge=0)
    difficulty: str | None = Field(default=None, max_length=64)
    instructions_summary: str | None = None
    ingredients: list[RecipeIngredientRequest] | None = None
    steps: list[RecipeStepRequest] | None = None
    tags: list[str] | None = None
    equipment: list[str] | None = None

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class RecipeSummaryResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    servings: float
    total_time_minutes: int
    difficulty: str | None
    active: bool
    tags: list[str]


class RecipeListResponse(BaseModel):
    items: list[RecipeSummaryResponse]
    total: int
    limit: int
    offset: int


class RecipeIngredientResponse(BaseModel):
    id: UUID
    food_id: UUID
    food_name: str
    quantity_grams: float
    display_quantity: str | None
    display_unit: str | None
    preparation_note: str | None
    position: int

    model_config = ConfigDict(from_attributes=True)


class RecipeStepResponse(BaseModel):
    id: UUID
    position: int
    instruction: str
    phase: RecipeStepPhase
    duration_seconds: int | None
    timer: bool
    timer_required: bool
    timer_seconds: int | None
    cue_action: str | None
    animation_key: str | None
    media_asset_key: str | None
    visual_cue: str | None

    model_config = ConfigDict(from_attributes=True)


class RecipeNutrientResponse(BaseModel):
    code: str
    name: str
    amount: float
    unit: str
    complete: bool
    missing_ingredient_count: int


class RecipeNutritionResponse(BaseModel):
    total: list[RecipeNutrientResponse]
    per_serving: list[RecipeNutrientResponse]


class RecipeDetailResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    servings: float
    prep_time_minutes: int
    cook_time_minutes: int
    total_time_minutes: int
    difficulty: str | None
    instructions_summary: str | None
    active: bool
    tags: list[str]
    equipment: list[str]
    ingredients: list[RecipeIngredientResponse]
    steps: list[RecipeStepResponse]
    nutrition: RecipeNutritionResponse


class RecipeCandidatePreviewRequest(BaseModel):
    meal_type: str | None = Field(default=None, max_length=64)
    max_total_time_minutes: int | None = Field(default=None, ge=0)
    require_complete_nutrition: bool = False
    required_nutrient_codes: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[UUID] = Field(default_factory=list)
    required_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)


class RecipeCandidateResponse(BaseModel):
    recipe_id: UUID
    name: str
    servings: float
    total_time_minutes: int
    meal_tags: list[str]
    tags: list[str]
    required_equipment: list[str]
    total_nutrition: list[RecipeNutrientResponse]
    per_serving_nutrition: list[RecipeNutrientResponse]
    nutrition_complete: bool
    missing_nutrient_codes: list[str]
    preference_match_count: int
    matched_preference_food_names: list[str]
    matched_preference_tags: list[str]


class ExcludedRecipeCandidateResponse(BaseModel):
    recipe_id: UUID
    name: str
    reasons: list[str]


class RecipeCandidatePreviewResponse(BaseModel):
    candidates: list[RecipeCandidateResponse]
    total_eligible: int
    exclusion_summary: dict[str, int]
    excluded: list[ExcludedRecipeCandidateResponse]
    allergy_filtering_supported: bool
    unsupported_dietary_restrictions: list[str]
    filter_order: list[str]
    unsupported_allergies: list[str] = Field(default_factory=list)
    allergy_filtering_scope: str = "reviewed_ingredient_metadata_only"
    allergy_limitation: str = "Cross-contact and medical safety are not assessed."
