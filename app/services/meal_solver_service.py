from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from app.meal_planning.solver import (
    DailyPlanSolverInput,
    DailyPlanSolverResult,
    MealSlot,
    MealSolverInputError,
    SolverConfig,
    SolverMicronutrientTarget,
    SolverNutritionTargets,
    default_meal_slots,
    solve_daily_plan,
)
from app.models.user import User
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.micronutrients import (
    MicronutrientReferenceDataError,
    MicronutrientTargetError,
    get_micronutrient_targets,
)
from app.nutrition.targets import calculate_nutrition_targets
from app.schemas.meal_plan import DailySolverPreviewRequest
from app.services.recipe_candidate_service import get_recipe_candidates
from app.services.user_profile_service import get_profile


def solve_daily_plan_preview(
    db: Session,
    user: User,
    payload: DailySolverPreviewRequest,
    target_override: SolverNutritionTargets | None = None,
) -> DailyPlanSolverResult:
    if target_override is None:
        profile = get_profile(db=db, user=user)
        targets = build_solver_targets_from_profile(profile)
    else:
        targets = target_override
    candidate_result = get_recipe_candidates(
        db=db,
        user=user,
        meal_type=None,
        max_total_time_minutes=payload.max_total_time_minutes,
        require_complete_nutrition=payload.require_complete_nutrition,
        required_nutrient_codes=payload.required_nutrient_codes,
        excluded_recipe_ids=payload.excluded_recipe_ids,
        required_tags=payload.required_tags,
        excluded_tags=payload.excluded_tags,
    )
    solver_config = SolverConfig(
        time_limit_seconds=payload.solver_time_limit_seconds or SolverConfig().time_limit_seconds
    )
    meal_slots = [
        MealSlot(meal_type=slot.meal_type, required=slot.required)
        for slot in payload.meal_slots
    ] if payload.meal_slots is not None else default_meal_slots()

    try:
        return solve_daily_plan(
            DailyPlanSolverInput(
                candidates=candidate_result.candidates,
                targets=targets,
                meal_slots=meal_slots,
                config=solver_config,
            )
        )
    except MealSolverInputError as exc:
        raise APIErrorException(
            status_code=422,
            code="MEAL_SOLVER_INVALID_INPUT",
            message=str(exc),
        ) from exc


def build_solver_targets_from_profile(profile) -> SolverNutritionTargets:
    try:
        macro_targets = calculate_nutrition_targets(
            age=profile.age,
            sex=profile.sex,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity_level=profile.activity_level,
            goal=profile.goal,
            target_rate=profile.target_rate,
        )
        micronutrient_targets = get_micronutrient_targets(
            age=profile.age,
            sex=profile.sex,
        )
    except NutritionCalculationError as exc:
        raise APIErrorException(
            status_code=422,
            code="NUTRITION_TARGETS_INVALID",
            message=str(exc),
        ) from exc
    except MicronutrientTargetError as exc:
        raise APIErrorException(
            status_code=422,
            code="MICRONUTRIENT_TARGETS_UNSUPPORTED",
            message=str(exc),
        ) from exc
    except MicronutrientReferenceDataError as exc:
        raise APIErrorException(
            status_code=500,
            code="MICRONUTRIENT_REFERENCE_DATA_MISSING",
            message="Micronutrient reference data is incomplete.",
            details={"reason": str(exc)},
        ) from exc

    return SolverNutritionTargets(
        calories=macro_targets.target_calories,
        protein_g=macro_targets.macros.protein_g,
        carbohydrates_g=macro_targets.macros.carbs_g,
        fat_g=macro_targets.macros.fat_g,
        micronutrients=[
            SolverMicronutrientTarget(
                code=target.nutrient_code,
                name=target.nutrient_name,
                target=target.amount,
                unit=target.unit,
                minimum_target=target.minimum_target,
                upper_limit=target.upper_limit,
                upper_limit_type=target.upper_limit_type,
            )
            for target in micronutrient_targets
        ],
    )
