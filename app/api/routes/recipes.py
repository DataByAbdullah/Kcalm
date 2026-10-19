from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.recipe import (
    ExcludedRecipeCandidateResponse,
    RecipeCandidatePreviewRequest,
    RecipeCandidatePreviewResponse,
    RecipeCandidateResponse,
    RecipeCreateRequest,
    RecipeDetailResponse,
    RecipeIngredientResponse,
    RecipeListResponse,
    RecipeNutrientResponse,
    RecipeNutritionResponse,
    RecipeStepResponse,
    RecipeSummaryResponse,
    RecipeUpdateRequest,
)
from app.services.recipe_candidate_service import (
    CandidateFilterResult,
    CandidateNutrient,
    RecipeCandidate,
    get_recipe_candidates,
)
from app.services.recipe_service import (
    archive_recipe,
    create_recipe,
    get_recipe_detail,
    list_recipes,
    update_recipe,
)


router = APIRouter()


def recipe_to_summary_response(recipe: Recipe) -> RecipeSummaryResponse:
    return RecipeSummaryResponse(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        servings=float(recipe.servings),
        total_time_minutes=recipe.total_time_minutes,
        difficulty=recipe.difficulty,
        active=recipe.active,
        tags=sorted(link.tag.name for link in recipe.tag_links),
    )


def recipe_to_detail_response(recipe: Recipe) -> RecipeDetailResponse:
    total_nutrients = [
        RecipeNutrientResponse(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=nutrient.total_amount,
            unit=nutrient.unit,
            complete=nutrient.complete,
            missing_ingredient_count=nutrient.missing_ingredient_count,
        )
        for nutrient in recipe.nutrients
    ]
    per_serving_nutrients = [
        RecipeNutrientResponse(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=nutrient.per_serving_amount,
            unit=nutrient.unit,
            complete=nutrient.complete,
            missing_ingredient_count=nutrient.missing_ingredient_count,
        )
        for nutrient in recipe.nutrients
    ]

    return RecipeDetailResponse(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        servings=float(recipe.servings),
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        total_time_minutes=recipe.total_time_minutes,
        difficulty=recipe.difficulty,
        instructions_summary=recipe.instructions_summary,
        active=recipe.active,
        tags=sorted(link.tag.name for link in recipe.tag_links),
        equipment=sorted(item.equipment for item in recipe.equipment),
        ingredients=[
            RecipeIngredientResponse(
                id=ingredient.id,
                food_id=ingredient.food_id,
                food_name=ingredient.food.name,
                quantity_grams=float(ingredient.quantity_grams),
                display_quantity=ingredient.display_quantity,
                display_unit=ingredient.display_unit,
                preparation_note=ingredient.preparation_note,
                position=ingredient.position,
            )
            for ingredient in recipe.ingredients
        ],
        steps=[
            RecipeStepResponse(
                id=step.id,
                position=step.position,
                instruction=step.instruction,
                phase=step.phase,
                duration_seconds=step.duration_seconds,
                timer=step.timer,
                timer_required=step.timer or step.timer_seconds is not None,
                timer_seconds=step.timer_seconds,
                cue_action=step.cue_action,
                animation_key=step.animation_key,
                media_asset_key=step.media_asset_key,
                visual_cue=step.visual_cue,
            )
            for step in recipe.steps
        ],
        nutrition=RecipeNutritionResponse(
            total=total_nutrients,
            per_serving=per_serving_nutrients,
        ),
    )


def candidate_nutrient_to_response(nutrient: CandidateNutrient) -> RecipeNutrientResponse:
    return RecipeNutrientResponse(
        code=nutrient.code,
        name=nutrient.name,
        amount=nutrient.amount,
        unit=nutrient.unit,
        complete=nutrient.complete,
        missing_ingredient_count=nutrient.missing_ingredient_count,
    )


def candidate_to_response(candidate: RecipeCandidate) -> RecipeCandidateResponse:
    return RecipeCandidateResponse(
        recipe_id=candidate.recipe_id,
        name=candidate.name,
        servings=candidate.servings,
        total_time_minutes=candidate.total_time_minutes,
        meal_tags=candidate.meal_tags,
        tags=candidate.tags,
        required_equipment=candidate.required_equipment,
        total_nutrition=[
            candidate_nutrient_to_response(nutrient)
            for nutrient in candidate.total_nutrition
        ],
        per_serving_nutrition=[
            candidate_nutrient_to_response(nutrient)
            for nutrient in candidate.per_serving_nutrition
        ],
        nutrition_complete=candidate.nutrition_complete,
        missing_nutrient_codes=candidate.missing_nutrient_codes,
        preference_match_count=candidate.preference_match_count,
        matched_preference_food_names=candidate.matched_preference_food_names,
        matched_preference_tags=candidate.matched_preference_tags,
    )


def candidate_result_to_response(
    result: CandidateFilterResult,
) -> RecipeCandidatePreviewResponse:
    return RecipeCandidatePreviewResponse(
        candidates=[candidate_to_response(candidate) for candidate in result.candidates],
        total_eligible=result.total_eligible,
        exclusion_summary={
            reason.value: count for reason, count in result.exclusion_summary.items()
        },
        excluded=[
            ExcludedRecipeCandidateResponse(
                recipe_id=item.recipe_id,
                name=item.name,
                reasons=[reason.value for reason in item.reasons],
            )
            for item in result.excluded
        ],
        allergy_filtering_supported=result.allergy_filtering_supported,
        unsupported_dietary_restrictions=result.unsupported_dietary_restrictions,
        filter_order=result.filter_order,
    )


@router.get("", response_model=RecipeListResponse)
def read_recipes(
    search: str | None = Query(default=None, min_length=1, max_length=128),
    tag: str | None = Query(default=None, min_length=1, max_length=64),
    max_total_time_minutes: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeListResponse:
    recipes, total = list_recipes(
        db=db,
        search=search,
        tag=tag,
        max_total_time_minutes=max_total_time_minutes,
        limit=limit,
        offset=offset,
    )
    return RecipeListResponse(
        items=[recipe_to_summary_response(recipe) for recipe in recipes],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/candidates/preview", response_model=RecipeCandidatePreviewResponse)
def preview_recipe_candidates(
    payload: RecipeCandidatePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeCandidatePreviewResponse:
    result = get_recipe_candidates(
        db=db,
        user=current_user,
        meal_type=payload.meal_type,
        max_total_time_minutes=payload.max_total_time_minutes,
        require_complete_nutrition=payload.require_complete_nutrition,
        required_nutrient_codes=payload.required_nutrient_codes,
        excluded_recipe_ids=payload.excluded_recipe_ids,
        required_tags=payload.required_tags,
        excluded_tags=payload.excluded_tags,
    )
    return candidate_result_to_response(result)


@router.post("", response_model=RecipeDetailResponse, status_code=status.HTTP_201_CREATED)
def create_recipe_endpoint(
    payload: RecipeCreateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetailResponse:
    return recipe_to_detail_response(create_recipe(db=db, payload=payload))


@router.get("/{recipe_id}", response_model=RecipeDetailResponse)
def read_recipe_detail(
    recipe_id: UUID,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetailResponse:
    return recipe_to_detail_response(get_recipe_detail(db=db, recipe_id=recipe_id))


@router.patch("/{recipe_id}", response_model=RecipeDetailResponse)
def patch_recipe(
    recipe_id: UUID,
    payload: RecipeUpdateRequest,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetailResponse:
    return recipe_to_detail_response(update_recipe(db=db, recipe_id=recipe_id, payload=payload))


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: UUID,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    archive_recipe(db=db, recipe_id=recipe_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
