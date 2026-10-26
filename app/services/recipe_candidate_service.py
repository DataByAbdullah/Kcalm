from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import APIErrorException
from app.models.food import Food
from app.models.recipe import Recipe, RecipeIngredient, RecipeTagLink
from app.models.user import User
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.services.recipe_service import ALLOWED_RECIPE_TAGS, normalize_key
from app.services.user_profile_service import load_user_with_profile_data
from app.services.dietary_service import ALLERGEN_CODES, normalize_allergies


MEAL_TYPE_TAGS = {"breakfast", "lunch", "pre_workout", "dinner", "snack"}
DIETARY_RESTRICTION_TAGS = {"vegetarian", "vegan", "dairy_free", "gluten_free", "pescatarian", "halal"}
DIETARY_RESTRICTION_ALIASES = {
    "dairy_free": "dairy_free",
    "dairyfree": "dairy_free",
    "no_dairy": "dairy_free",
    "gluten_free": "gluten_free",
    "glutenfree": "gluten_free",
}
EQUIPMENT_ALIASES = {
    "stove": "stovetop",
    "air_fryer": "air_fryer",
    "air_fryer_": "air_fryer",
}


def profile_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="PROFILE_NOT_FOUND",
        message="Profile not found for this user.",
    )


class CandidateRejectionReason(StrEnum):
    INACTIVE = "inactive"
    WRONG_MEAL_TYPE = "wrong_meal_type"
    EXCEEDS_TIME_LIMIT = "exceeds_time_limit"
    MISSING_REQUIRED_EQUIPMENT = "missing_required_equipment"
    DIETARY_RESTRICTION_MISMATCH = "dietary_restriction_mismatch"
    ALLERGY_CONFLICT = "allergy_conflict"
    ALLERGY_METADATA_MISSING = "allergy_metadata_missing"
    UNSUPPORTED_ALLERGY = "unsupported_allergy"
    DISLIKED_FOOD = "disliked_food"
    INCOMPLETE_NUTRITION = "incomplete_nutrition"
    EXPLICITLY_EXCLUDED = "explicitly_excluded"
    MISSING_REQUIRED_TAG = "missing_required_tag"
    EXCLUDED_TAG = "excluded_tag"


@dataclass(frozen=True)
class CandidateFilterContext:
    user_id: UUID
    meal_type: str | None = None
    max_total_time_minutes: int | None = None
    available_equipment: set[str] = field(default_factory=set)
    dietary_restrictions: set[str] = field(default_factory=set)
    unsupported_dietary_restrictions: set[str] = field(default_factory=set)
    allergies: set[str] = field(default_factory=set)
    unsupported_allergies: set[str] = field(default_factory=set)
    disliked_foods: set[str] = field(default_factory=set)
    preferred_foods: set[str] = field(default_factory=set)
    excluded_recipe_ids: set[UUID] = field(default_factory=set)
    required_tags: set[str] = field(default_factory=set)
    excluded_tags: set[str] = field(default_factory=set)
    require_complete_nutrition: bool = False
    required_nutrient_codes: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class CandidateNutrient:
    code: str
    name: str
    amount: float
    unit: str
    complete: bool
    missing_ingredient_count: int


@dataclass(frozen=True)
class RecipeCandidate:
    recipe_id: UUID
    name: str
    servings: float
    total_time_minutes: int
    meal_tags: list[str]
    tags: list[str]
    required_equipment: list[str]
    total_nutrition: list[CandidateNutrient]
    per_serving_nutrition: list[CandidateNutrient]
    nutrition_complete: bool
    missing_nutrient_codes: list[str]
    preference_match_count: int
    matched_preference_food_names: list[str]
    matched_preference_tags: list[str]


@dataclass(frozen=True)
class ExcludedRecipe:
    recipe_id: UUID
    name: str
    reasons: list[CandidateRejectionReason]


@dataclass(frozen=True)
class CandidateFilterResult:
    candidates: list[RecipeCandidate]
    total_eligible: int
    exclusion_summary: dict[CandidateRejectionReason, int]
    excluded: list[ExcludedRecipe]
    allergy_filtering_supported: bool
    unsupported_dietary_restrictions: list[str]
    filter_order: list[str]
    unsupported_allergies: list[str] = field(default_factory=list)


FILTER_ORDER = [
    "active",
    "explicit_exclusions",
    "meal_type",
    "required_and_excluded_tags",
    "time",
    "equipment",
    "dietary_restrictions",
    "allergies",
    "disliked_foods",
    "nutrition_completeness",
]


def get_recipe_candidates(
    db: Session,
    user: User,
    meal_type: str | None = None,
    max_total_time_minutes: int | None = None,
    require_complete_nutrition: bool = False,
    required_nutrient_codes: list[str] | None = None,
    excluded_recipe_ids: list[UUID] | None = None,
    required_tags: list[str] | None = None,
    excluded_tags: list[str] | None = None,
) -> CandidateFilterResult:
    loaded_user = load_user_with_profile_data(db=db, user_id=user.id)
    if loaded_user.profile is None:
        raise profile_not_found_error()

    context = build_candidate_context(
        loaded_user=loaded_user,
        meal_type=meal_type,
        max_total_time_minutes=max_total_time_minutes,
        require_complete_nutrition=require_complete_nutrition,
        required_nutrient_codes=required_nutrient_codes or [],
        excluded_recipe_ids=excluded_recipe_ids or [],
        required_tags=required_tags or [],
        excluded_tags=excluded_tags or [],
    )
    recipes = load_candidate_recipes(db)
    candidates: list[RecipeCandidate] = []
    excluded: list[ExcludedRecipe] = []
    exclusion_summary: dict[CandidateRejectionReason, int] = {}

    for recipe in recipes:
        reasons = rejection_reasons_for_recipe(recipe=recipe, context=context)
        if reasons:
            excluded.append(
                ExcludedRecipe(
                    recipe_id=recipe.id,
                    name=recipe.name,
                    reasons=reasons,
                )
            )
            first_reason = reasons[0]
            exclusion_summary[first_reason] = exclusion_summary.get(first_reason, 0) + 1
            continue

        candidates.append(recipe_to_candidate(recipe=recipe, context=context))

    candidates.sort(key=lambda candidate: (candidate.name.lower(), str(candidate.recipe_id)))
    excluded.sort(key=lambda item: (item.name.lower(), str(item.recipe_id)))
    return CandidateFilterResult(
        candidates=candidates,
        total_eligible=len(candidates),
        exclusion_summary=exclusion_summary,
        excluded=excluded,
        allergy_filtering_supported=not bool(context.unsupported_allergies),
        unsupported_allergies=sorted(context.unsupported_allergies),
        unsupported_dietary_restrictions=sorted(context.unsupported_dietary_restrictions),
        filter_order=FILTER_ORDER,
    )


def build_candidate_context(
    loaded_user: User,
    meal_type: str | None,
    max_total_time_minutes: int | None,
    require_complete_nutrition: bool,
    required_nutrient_codes: list[str],
    excluded_recipe_ids: list[UUID],
    required_tags: list[str],
    excluded_tags: list[str],
) -> CandidateFilterContext:
    normalized_meal_type = normalize_meal_type(meal_type)
    normalized_required_tags = normalize_candidate_tags(required_tags)
    normalized_excluded_tags = normalize_candidate_tags(excluded_tags)
    normalized_required_nutrients = normalize_required_nutrient_codes(required_nutrient_codes)
    dietary_restrictions, unsupported_dietary_restrictions = normalize_dietary_restrictions(
        [item.name for item in loaded_user.dietary_restrictions]
    )
    profile_max_total_time = (
        loaded_user.profile.max_cooking_minutes if loaded_user.profile is not None else None
    )
    allergies, unsupported_allergies = normalize_allergies([item.name for item in loaded_user.allergies])
    effective_max_total_time = (
        max_total_time_minutes
        if max_total_time_minutes is not None
        else profile_max_total_time
    )

    return CandidateFilterContext(
        user_id=loaded_user.id,
        meal_type=normalized_meal_type,
        max_total_time_minutes=effective_max_total_time,
        available_equipment={
            normalize_equipment(item.equipment) for item in loaded_user.equipment
        },
        dietary_restrictions=dietary_restrictions,
        unsupported_dietary_restrictions=unsupported_dietary_restrictions,
        allergies=allergies,
        unsupported_allergies=unsupported_allergies,
        disliked_foods={
            normalize_profile_text(item.name) for item in loaded_user.disliked_foods
        },
        preferred_foods={
            normalize_profile_text(item.name) for item in loaded_user.preferred_foods
        },
        excluded_recipe_ids=set(excluded_recipe_ids),
        required_tags=normalized_required_tags,
        excluded_tags=normalized_excluded_tags,
        require_complete_nutrition=require_complete_nutrition,
        required_nutrient_codes=normalized_required_nutrients,
    )


def load_candidate_recipes(db: Session) -> list[Recipe]:
    return (
        db.query(Recipe)
        .options(
            selectinload(Recipe.ingredients).selectinload(RecipeIngredient.food),
            selectinload(Recipe.tag_links).selectinload(RecipeTagLink.tag),
            selectinload(Recipe.equipment),
            selectinload(Recipe.nutrients),
        )
        .order_by(Recipe.name.asc(), Recipe.id.asc())
        .all()
    )


def rejection_reasons_for_recipe(
    recipe: Recipe,
    context: CandidateFilterContext,
) -> list[CandidateRejectionReason]:
    recipe_tags = tag_names(recipe)
    reasons: list[CandidateRejectionReason] = []

    if not recipe.active:
        return [CandidateRejectionReason.INACTIVE]
    if recipe.id in context.excluded_recipe_ids:
        return [CandidateRejectionReason.EXPLICITLY_EXCLUDED]
    if context.meal_type is not None and context.meal_type not in recipe_tags:
        return [CandidateRejectionReason.WRONG_MEAL_TYPE]
    if not context.required_tags.issubset(recipe_tags):
        return [CandidateRejectionReason.MISSING_REQUIRED_TAG]
    if context.excluded_tags.intersection(recipe_tags):
        return [CandidateRejectionReason.EXCLUDED_TAG]
    if (
        context.max_total_time_minutes is not None
        and recipe.total_time_minutes > context.max_total_time_minutes
    ):
        return [CandidateRejectionReason.EXCEEDS_TIME_LIMIT]
    if not required_equipment(recipe).issubset(context.available_equipment):
        return [CandidateRejectionReason.MISSING_REQUIRED_EQUIPMENT]
    if not context.dietary_restrictions.issubset(recipe_tags):
        return [CandidateRejectionReason.DIETARY_RESTRICTION_MISMATCH]
    if context.unsupported_allergies:
        return [CandidateRejectionReason.UNSUPPORTED_ALLERGY]
    if context.allergies:
        for ingredient in recipe.ingredients:
            codes = ingredient.food.allergen_codes
            if (codes is None or not isinstance(codes, list) or not (ingredient.food.allergen_reference or "").strip()
                    or any(not isinstance(code, str) or code not in ALLERGEN_CODES for code in codes)):
                return [CandidateRejectionReason.ALLERGY_METADATA_MISSING]
            if context.allergies.intersection(codes):
                return [CandidateRejectionReason.ALLERGY_CONFLICT]
        if not recipe.ingredients:
            return [CandidateRejectionReason.ALLERGY_METADATA_MISSING]
    if disliked_food_names(recipe).intersection(context.disliked_foods):
        return [CandidateRejectionReason.DISLIKED_FOOD]
    if has_incomplete_required_nutrition(recipe=recipe, context=context):
        return [CandidateRejectionReason.INCOMPLETE_NUTRITION]

    return reasons


def recipe_to_candidate(recipe: Recipe, context: CandidateFilterContext) -> RecipeCandidate:
    total_nutrition = [
        CandidateNutrient(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=nutrient.total_amount,
            unit=nutrient.unit,
            complete=nutrient.complete,
            missing_ingredient_count=nutrient.missing_ingredient_count,
        )
        for nutrient in recipe.nutrients
    ]
    per_serving_nutrition = [
        CandidateNutrient(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=nutrient.per_serving_amount,
            unit=nutrient.unit,
            complete=nutrient.complete,
            missing_ingredient_count=nutrient.missing_ingredient_count,
        )
        for nutrient in recipe.nutrients
    ]
    missing_nutrient_codes = sorted(
        nutrient.nutrient_code for nutrient in recipe.nutrients if not nutrient.complete
    )
    matched_preference_food_names = sorted(
        {
            ingredient.food.name
            for ingredient in recipe.ingredients
            if normalize_profile_text(ingredient.food.name) in context.preferred_foods
        }
    )
    matched_preference_tags: list[str] = []

    return RecipeCandidate(
        recipe_id=recipe.id,
        name=recipe.name,
        servings=float(recipe.servings),
        total_time_minutes=recipe.total_time_minutes,
        meal_tags=sorted(tag_names(recipe).intersection(MEAL_TYPE_TAGS)),
        tags=sorted(tag_names(recipe)),
        required_equipment=sorted(required_equipment(recipe)),
        total_nutrition=total_nutrition,
        per_serving_nutrition=per_serving_nutrition,
        nutrition_complete=not missing_nutrient_codes,
        missing_nutrient_codes=missing_nutrient_codes,
        preference_match_count=len(matched_preference_food_names) + len(matched_preference_tags),
        matched_preference_food_names=matched_preference_food_names,
        matched_preference_tags=matched_preference_tags,
    )


def has_incomplete_required_nutrition(
    recipe: Recipe,
    context: CandidateFilterContext,
) -> bool:
    if not context.require_complete_nutrition:
        return False

    required_codes = context.required_nutrient_codes or set(RECIPE_NUTRIENT_DEFINITION_BY_CODE)
    nutrients_by_code = {nutrient.nutrient_code: nutrient for nutrient in recipe.nutrients}
    for code in required_codes:
        nutrient = nutrients_by_code.get(code)
        if nutrient is None or not nutrient.complete:
            return True
    return False


def tag_names(recipe: Recipe) -> set[str]:
    return {link.tag.name for link in recipe.tag_links}


def required_equipment(recipe: Recipe) -> set[str]:
    return {normalize_equipment(item.equipment) for item in recipe.equipment}


def disliked_food_names(recipe: Recipe) -> set[str]:
    return {normalize_profile_text(ingredient.food.name) for ingredient in recipe.ingredients}


def normalize_meal_type(meal_type: str | None) -> str | None:
    if meal_type is None:
        return None
    normalized = normalize_key(meal_type)
    if normalized not in MEAL_TYPE_TAGS:
        raise APIErrorException(
            status_code=422,
            code="INVALID_CANDIDATE_MEAL_TYPE",
            message="Candidate meal type is not supported.",
            details={"meal_type": meal_type, "supported_meal_types": sorted(MEAL_TYPE_TAGS)},
        )
    return normalized


def normalize_candidate_tags(values: list[str]) -> set[str]:
    normalized_values: set[str] = set()
    for value in values:
        normalized = normalize_key(value)
        if normalized not in ALLOWED_RECIPE_TAGS:
            raise APIErrorException(
                status_code=422,
                code="INVALID_CANDIDATE_TAG",
                message="Candidate tag is not supported.",
                details={"tag": value, "supported_tags": sorted(ALLOWED_RECIPE_TAGS)},
            )
        normalized_values.add(normalized)
    return normalized_values


def normalize_required_nutrient_codes(values: list[str]) -> set[str]:
    normalized_values: set[str] = set()
    for value in values:
        normalized = normalize_key(value)
        if normalized not in RECIPE_NUTRIENT_DEFINITION_BY_CODE:
            raise APIErrorException(
                status_code=422,
                code="INVALID_REQUIRED_NUTRIENT",
                message="Required nutrient code is not supported.",
                details={
                    "nutrient_code": value,
                    "supported_nutrient_codes": sorted(RECIPE_NUTRIENT_DEFINITION_BY_CODE),
                },
            )
        normalized_values.add(normalized)
    return normalized_values


def normalize_dietary_restrictions(values: list[str]) -> tuple[set[str], set[str]]:
    supported: set[str] = set()
    unsupported: set[str] = set()
    for value in values:
        normalized = DIETARY_RESTRICTION_ALIASES.get(normalize_key(value), normalize_key(value))
        if normalized in DIETARY_RESTRICTION_TAGS:
            supported.add(normalized)
        elif normalized:
            unsupported.add(normalized)
    return supported, unsupported


def normalize_equipment(value: str) -> str:
    normalized = normalize_key(value)
    return EQUIPMENT_ALIASES.get(normalized, normalized)


def normalize_profile_text(value: str) -> str:
    return " ".join(value.strip().lower().split())
