from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.enums import MealPlanStatus
from app.core.exceptions import APIErrorException
from app.meal_planning.scaling import scale_amount, unscale_amount
from app.meal_planning.solver import (
    CALORIES_CODE,
    CARBOHYDRATES_CODE,
    FAT_CODE,
    PROTEIN_CODE,
    DailyPlanSolverResult,
    SolverMicronutrientTarget,
    SolverNutritionTargets,
    SolverStatus,
)
from app.models.adaptation import MealPlanAdaptationSnapshot
from app.models.meal_plan import MealPlan
from app.models.user import User
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.macros import calculate_macros_with_fixed_protein_and_fat
from app.schemas.adaptive_planning import AdaptivePlanRequest
from app.schemas.meal_plan import MealPlanCreateRequest, MealSlotRequest
from app.services.meal_log_service import get_actual_summary
from app.services.meal_plan_service import create_daily_meal_plan, get_meal_plan_detail
from app.services.meal_solver_service import solve_daily_plan_preview


ADAPTIVE_POLICY_VERSION = "adaptive_v1"
COMPENSATION_FRACTION = 0.25
MAX_ADJUSTMENT_KCAL = 250.0
MAX_ADJUSTMENT_PERCENT = 0.10
MINIMUM_ADJUSTED_CALORIES = 1200.0
MICRONUTRIENT_STRATEGY = "report_only_standard_targets_unchanged"


@dataclass(frozen=True)
class AdaptivePolicy:
    policy_version: str = ADAPTIVE_POLICY_VERSION
    compensation_fraction: float = COMPENSATION_FRACTION
    max_adjustment_kcal: float = MAX_ADJUSTMENT_KCAL
    max_adjustment_percent: float = MAX_ADJUSTMENT_PERCENT
    minimum_adjusted_calories: float = MINIMUM_ADJUSTED_CALORIES


@dataclass(frozen=True)
class AdaptiveTarget:
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
    safety_caps_applied: list[str]
    policy_version: str
    solver_targets: SolverNutritionTargets


@dataclass(frozen=True)
class AdaptivePreview:
    source_plan: MealPlan
    next_day_date: str
    actual_totals: dict[str, float]
    target_totals: dict[str, float]
    deviation: dict[str, float]
    micronutrient_deviation: dict[str, float]
    policy: AdaptivePolicy
    adjusted_target: AdaptiveTarget
    solver_result: DailyPlanSolverResult


@dataclass(frozen=True)
class AdaptivePlanCreation:
    source_plan: MealPlan
    adjusted_target: AdaptiveTarget
    plan: MealPlan


def incomplete_daily_log_error(planned: int, logged: int, unlogged_item_ids: list[UUID]) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="INCOMPLETE_DAILY_LOG",
        message="Adaptive planning requires every planned meal item to be logged.",
        details={
            "planned_meals_count": planned,
            "logged_meals_count": logged,
            "unlogged_meal_item_ids": [str(item_id) for item_id in unlogged_item_ids],
        },
    )


def actual_log_nutrition_incomplete_error(missing_codes: list[str]) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="ACTUAL_LOG_NUTRITION_INCOMPLETE",
        message="Actual log snapshots are missing required macro nutrition.",
        details={"missing_or_invalid_codes": missing_codes},
    )


def source_plan_archived_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="MEAL_PLAN_ARCHIVED",
        message="Archived meal plans cannot be used for adaptive next-day planning.",
    )


def adaptive_target_invalid_error(reason: str) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="ADAPTIVE_TARGET_INVALID",
        message="Adaptive target calculation failed.",
        details={"reason": reason},
    )


def adaptive_plan_infeasible_error(result: DailyPlanSolverResult) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="ADAPTIVE_PLAN_INFEASIBLE",
        message="Adaptive next-day meal plan could not be generated.",
        details={"infeasibility_reasons": result.infeasibility_reasons},
    )


def adaptive_plan_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="ADAPTIVE_PLAN_SAVE_FAILED",
        message="Adaptive next-day meal plan could not be saved.",
    )


def preview_adaptive_next_day_plan(
    db: Session,
    user: User,
    source_plan_id: UUID,
    payload: AdaptivePlanRequest,
) -> AdaptivePreview:
    source_plan = load_valid_source_plan(db=db, user=user, source_plan_id=source_plan_id)
    adjusted_target, actual_totals, target_totals, deviation, micro_deviation = build_adjusted_target(
        db=db,
        user=user,
        source_plan=source_plan,
    )
    solver_payload = adaptive_solver_payload(source_plan=source_plan, payload=payload)
    solver_result = solve_daily_plan_preview(
        db=db,
        user=user,
        payload=solver_payload,
        target_override=adjusted_target.solver_targets,
    )
    return AdaptivePreview(
        source_plan=source_plan,
        next_day_date=next_day_date(source_plan).isoformat(),
        actual_totals=actual_totals,
        target_totals=target_totals,
        deviation=deviation,
        micronutrient_deviation=micro_deviation,
        policy=AdaptivePolicy(),
        adjusted_target=adjusted_target,
        solver_result=solver_result,
    )


def create_adaptive_next_day_plan(
    db: Session,
    user: User,
    source_plan_id: UUID,
    payload: AdaptivePlanRequest,
) -> AdaptivePlanCreation:
    source_plan = load_valid_source_plan(db=db, user=user, source_plan_id=source_plan_id)
    adjusted_target, _, _, _, _ = build_adjusted_target(
        db=db,
        user=user,
        source_plan=source_plan,
    )
    solver_payload = adaptive_solver_payload(source_plan=source_plan, payload=payload)
    solver_result = solve_daily_plan_preview(
        db=db,
        user=user,
        payload=solver_payload,
        target_override=adjusted_target.solver_targets,
    )
    if solver_result.status is SolverStatus.INFEASIBLE:
        raise adaptive_plan_infeasible_error(solver_result)

    try:
        plan = create_daily_meal_plan(
            db=db,
            user=user,
            payload=MealPlanCreateRequest(**solver_payload.model_dump()),
            commit=False,
            target_override=adjusted_target.solver_targets,
        )
        persist_adaptation_snapshot(db=db, plan=plan, adjusted_target=adjusted_target)
        db.commit()
        db.expire_all()
    except APIErrorException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise adaptive_plan_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    persisted_plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=plan.id)
    return AdaptivePlanCreation(
        source_plan=source_plan,
        adjusted_target=adjusted_target,
        plan=persisted_plan,
    )


def load_valid_source_plan(db: Session, user: User, source_plan_id: UUID) -> MealPlan:
    source_plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=source_plan_id)
    if source_plan.status == MealPlanStatus.ARCHIVED.value:
        raise source_plan_archived_error()
    if not source_plan.micronutrient_targets:
        raise adaptive_target_invalid_error("source_plan_micronutrient_targets_missing")
    return source_plan


def build_adjusted_target(
    db: Session,
    user: User,
    source_plan: MealPlan,
) -> tuple[AdaptiveTarget, dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    summary = get_actual_summary(db=db, user=user, meal_plan_id=source_plan.id)
    if summary.logged_meals_count != summary.planned_meals_count:
        logged_item_ids = active_logged_item_ids(db=db, source_plan_id=source_plan.id)
        planned_item_ids = {item.id for item in source_plan.items}
        raise incomplete_daily_log_error(
            planned=summary.planned_meals_count,
            logged=summary.logged_meals_count,
            unlogged_item_ids=sorted(planned_item_ids - logged_item_ids, key=str),
        )

    validate_actual_macros(summary.actual_totals)
    target_totals = source_target_totals(source_plan)
    deviation = {
        code: unscale_amount(
            scale_amount(summary.actual_totals.get(code, 0.0)) - scale_amount(target)
        )
        for code, target in sorted(target_totals.items())
    }
    micro_deviation = {
        target.nutrient_code: unscale_amount(
            scale_amount(summary.actual_totals.get(target.nutrient_code, 0.0))
            - scale_amount(target.target)
        )
        for target in source_plan.micronutrient_targets
    }
    adjusted_target = apply_compensation_policy(
        source_plan=source_plan,
        actual_totals=summary.actual_totals,
        calorie_deviation=deviation[CALORIES_CODE],
    )
    return adjusted_target, summary.actual_totals, target_totals, deviation, micro_deviation


def active_logged_item_ids(db: Session, source_plan_id: UUID) -> set[UUID]:
    from app.models.meal_log import MealLog
    from app.core.enums import MealLogStatus

    return {
        row[0]
        for row in db.query(MealLog.meal_plan_item_id)
        .filter(
            MealLog.meal_plan_id == source_plan_id,
            MealLog.status == MealLogStatus.ACTIVE.value,
        )
        .all()
    }


def validate_actual_macros(actual_totals: dict[str, float]) -> None:
    missing_or_invalid = []
    for code in (CALORIES_CODE, PROTEIN_CODE, CARBOHYDRATES_CODE, FAT_CODE):
        amount = actual_totals.get(code)
        if amount is None or amount < 0 or (code == CALORIES_CODE and amount <= 0):
            missing_or_invalid.append(code)
    if missing_or_invalid:
        raise actual_log_nutrition_incomplete_error(missing_or_invalid)


def apply_compensation_policy(
    source_plan: MealPlan,
    actual_totals: dict[str, float],
    calorie_deviation: float,
) -> AdaptiveTarget:
    policy = AdaptivePolicy()
    raw_compensation = -calorie_deviation * policy.compensation_fraction
    cap = min(policy.max_adjustment_kcal, source_plan.calorie_target * policy.max_adjustment_percent)
    safety_caps_applied = []
    compensation_amount = raw_compensation
    if abs(compensation_amount) > cap:
        compensation_amount = cap if compensation_amount > 0 else -cap
        safety_caps_applied.append("max_adjustment_cap")

    adjusted_calories = source_plan.calorie_target + compensation_amount
    if adjusted_calories < policy.minimum_adjusted_calories:
        adjusted_calories = policy.minimum_adjusted_calories
        compensation_amount = adjusted_calories - source_plan.calorie_target
        safety_caps_applied.append("minimum_adjusted_calories")

    try:
        adjusted_macros = calculate_macros_with_fixed_protein_and_fat(
            target_calories=adjusted_calories,
            protein_g=source_plan.protein_target,
            fat_g=source_plan.fat_target,
        )
    except NutritionCalculationError as exc:
        raise adaptive_target_invalid_error(str(exc)) from exc

    solver_targets = SolverNutritionTargets(
        calories=adjusted_calories,
        protein_g=adjusted_macros.protein_g,
        carbohydrates_g=adjusted_macros.carbs_g,
        fat_g=adjusted_macros.fat_g,
        micronutrients=[
            SolverMicronutrientTarget(
                code=target.nutrient_code,
                name=target.nutrient_name,
                target=target.target,
                unit=target.unit,
                minimum_target=target.minimum_target,
                upper_limit=target.upper_limit,
                upper_limit_type=target.upper_limit_type,
            )
            for target in source_plan.micronutrient_targets
        ],
    )
    return AdaptiveTarget(
        source_plan_id=source_plan.id,
        base_calorie_target=source_plan.calorie_target,
        previous_day_actual_calories=actual_totals[CALORIES_CODE],
        previous_day_calorie_deviation=calorie_deviation,
        compensation_fraction=policy.compensation_fraction,
        raw_compensation_amount=raw_compensation,
        compensation_amount=compensation_amount,
        adjusted_calorie_target=adjusted_calories,
        base_macro_targets={
            PROTEIN_CODE: source_plan.protein_target,
            CARBOHYDRATES_CODE: source_plan.carbohydrate_target,
            FAT_CODE: source_plan.fat_target,
        },
        adjusted_macro_targets={
            PROTEIN_CODE: adjusted_macros.protein_g,
            CARBOHYDRATES_CODE: adjusted_macros.carbs_g,
            FAT_CODE: adjusted_macros.fat_g,
        },
        micronutrient_strategy=MICRONUTRIENT_STRATEGY,
        safety_caps_applied=safety_caps_applied,
        policy_version=policy.policy_version,
        solver_targets=solver_targets,
    )


def source_target_totals(source_plan: MealPlan) -> dict[str, float]:
    targets = {
        CALORIES_CODE: source_plan.calorie_target,
        PROTEIN_CODE: source_plan.protein_target,
        CARBOHYDRATES_CODE: source_plan.carbohydrate_target,
        FAT_CODE: source_plan.fat_target,
    }
    for target in source_plan.micronutrient_targets:
        targets[target.nutrient_code] = target.target
    return targets


def adaptive_solver_payload(
    source_plan: MealPlan,
    payload: AdaptivePlanRequest,
) -> MealPlanCreateRequest:
    meal_slots = payload.meal_slots or [
        MealSlotRequest(meal_type=item.meal_type, required=True)
        for item in sorted(source_plan.items, key=lambda item: item.position)
    ]
    return MealPlanCreateRequest(
        plan_date=next_day_date(source_plan),
        meal_slots=meal_slots,
        max_total_time_minutes=payload.max_total_time_minutes,
        require_complete_nutrition=payload.require_complete_nutrition,
        required_nutrient_codes=payload.required_nutrient_codes,
        excluded_recipe_ids=payload.excluded_recipe_ids,
        required_tags=payload.required_tags,
        excluded_tags=payload.excluded_tags,
        solver_time_limit_seconds=payload.solver_time_limit_seconds,
    )


def next_day_date(source_plan: MealPlan):
    return source_plan.plan_date + timedelta(days=1)


def persist_adaptation_snapshot(
    db: Session,
    plan: MealPlan,
    adjusted_target: AdaptiveTarget,
) -> None:
    db.add(
        MealPlanAdaptationSnapshot(
            meal_plan_id=plan.id,
            source_meal_plan_id=adjusted_target.source_plan_id,
            policy_version=adjusted_target.policy_version,
            base_calorie_target=adjusted_target.base_calorie_target,
            source_actual_calories=adjusted_target.previous_day_actual_calories,
            source_calorie_deviation=adjusted_target.previous_day_calorie_deviation,
            compensation_fraction=adjusted_target.compensation_fraction,
            compensation_amount=adjusted_target.compensation_amount,
            adjusted_calorie_target=adjusted_target.adjusted_calorie_target,
            base_protein_target=adjusted_target.base_macro_targets[PROTEIN_CODE],
            base_carbohydrate_target=adjusted_target.base_macro_targets[CARBOHYDRATES_CODE],
            base_fat_target=adjusted_target.base_macro_targets[FAT_CODE],
            adjusted_protein_target=adjusted_target.adjusted_macro_targets[PROTEIN_CODE],
            adjusted_carbohydrate_target=adjusted_target.adjusted_macro_targets[CARBOHYDRATES_CODE],
            adjusted_fat_target=adjusted_target.adjusted_macro_targets[FAT_CODE],
            safety_cap_applied=bool(adjusted_target.safety_caps_applied),
        )
    )
    db.flush()
