from dataclasses import dataclass
from uuid import UUID
from datetime import date, timedelta
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.enums import MealLogSourceType, MealLogStatus, MealLogType, MealPlanStatus
from app.core.exceptions import APIErrorException
from app.meal_planning.scaling import scale_amount, unscale_amount
from app.models.food import Food
from app.models.meal_log import MealLog, MealLogNutrientSnapshot
from app.models.meal_plan import MealPlan, MealPlanItem
from app.models.recipe import Recipe
from app.models.user import User
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.schemas.meal_log import MealLogRequest
from app.services.food_service import food_not_found_error
from app.services.meal_plan_service import (
    daily_totals_from_plan,
    get_meal_plan_detail,
    solver_targets_from_plan,
)
from app.services.recipe_service import recipe_not_found_error


@dataclass(frozen=True)
class NutrientSnapshotValue:
    code: str
    name: str
    amount: float
    unit: str


@dataclass(frozen=True)
class MealPlanActualSummary:
    plan: MealPlan
    planned_totals: dict[str, float]
    actual_totals: dict[str, float]
    difference_actual_vs_planned: dict[str, float]
    difference_actual_vs_target: dict[str, float]
    actual_known_nutrient_codes: list[str]
    missing_actual_target_nutrient_codes: list[str]
    planned_meals_count: int
    logged_meals_count: int
    unlogged_meals_count: int
    ate_as_planned_count: int
    corrected_count: int
    adherence_percent: float


def meal_plan_archived_for_logging_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="MEAL_PLAN_ARCHIVED",
        message="Archived meal plans cannot be logged.",
    )


def meal_plan_item_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="MEAL_PLAN_ITEM_NOT_FOUND",
        message="Meal plan item not found.",
    )


def meal_log_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="MEAL_LOG_NOT_FOUND",
        message="Meal log not found.",
    )


def meal_log_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="MEAL_LOG_SAVE_FAILED",
        message="Meal log could not be saved.",
    )


def log_meal_plan_item(
    db: Session,
    user: User,
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    payload: MealLogRequest,
) -> MealLog:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    ensure_plan_can_be_logged(plan)
    item = item_for_log(plan=plan, meal_plan_item_id=meal_plan_item_id)
    nutrients = nutrients_for_log_payload(db=db, item=item, payload=payload)
    nutrient_complete = len(nutrients) == len(RECIPE_NUTRIENT_DEFINITION_BY_CODE)
    meal_log = active_log_for_item(db=db, meal_plan_item_id=item.id)

    try:
        if meal_log is None:
            meal_log = MealLog(
                user_id=user.id,
                meal_plan_id=plan.id,
                meal_plan_item_id=item.id,
                log_date=plan.plan_date,
            )
            db.add(meal_log)
            db.flush()

        apply_payload_to_log(meal_log=meal_log, payload=payload, nutrient_complete=nutrient_complete)
        replace_log_nutrients(db=db, meal_log=meal_log, nutrients=nutrients)
        db.commit()
        db.expire_all()
    except IntegrityError as exc:
        db.rollback()
        raise meal_log_save_failed_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise meal_log_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_meal_log_detail(db=db, user=user, meal_log_id=meal_log.id)


def reset_meal_plan_item_log(
    db: Session,
    user: User,
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
) -> None:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    ensure_plan_can_be_logged(plan)
    item = item_for_log(plan=plan, meal_plan_item_id=meal_plan_item_id)
    meal_log = active_log_for_item(db=db, meal_plan_item_id=item.id)
    if meal_log is None:
        raise meal_log_not_found_error()

    try:
        db.delete(meal_log)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise meal_log_save_failed_error() from exc


def get_meal_log_detail(db: Session, user: User, meal_log_id: UUID) -> MealLog:
    meal_log = (
        db.query(MealLog)
        .options(selectinload(MealLog.nutrients))
        .filter(MealLog.id == meal_log_id, MealLog.user_id == user.id)
        .one_or_none()
    )
    if meal_log is None:
        raise meal_log_not_found_error()
    return meal_log


def get_actual_summary(
    db: Session,
    user: User,
    meal_plan_id: UUID,
) -> MealPlanActualSummary:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    logs = active_logs_for_plan(db=db, meal_plan_id=plan.id)
    actual_totals = totals_from_logs(logs)
    planned_totals = daily_totals_from_plan(plan)
    target_totals = target_totals_from_plan(plan)
    target_codes = set(target_totals)
    actual_codes = set(actual_totals)

    planned_meals_count = len(plan.items)
    logged_meals_count = len({log.meal_plan_item_id for log in logs})
    ate_as_planned_count = sum(
        1 for log in logs if log.log_type == MealLogType.ATE_AS_PLANNED.value
    )
    corrected_count = sum(1 for log in logs if log.log_type == MealLogType.CORRECTED.value)

    return MealPlanActualSummary(
        plan=plan,
        planned_totals=planned_totals,
        actual_totals=actual_totals,
        difference_actual_vs_planned=differences(
            actual=actual_totals,
            baseline=planned_totals,
        ),
        difference_actual_vs_target=differences(
            actual=actual_totals,
            baseline=target_totals,
        ),
        actual_known_nutrient_codes=sorted(actual_codes),
        missing_actual_target_nutrient_codes=sorted(target_codes - actual_codes),
        planned_meals_count=planned_meals_count,
        logged_meals_count=logged_meals_count,
        unlogged_meals_count=planned_meals_count - logged_meals_count,
        ate_as_planned_count=ate_as_planned_count,
        corrected_count=corrected_count,
       adherence_percent=(
        round((ate_as_planned_count / planned_meals_count) * 100, 6)
        if planned_meals_count
        else 0.0
        ),
    )


def ensure_plan_can_be_logged(plan: MealPlan) -> None:
    if plan.status == MealPlanStatus.ARCHIVED.value:
        raise meal_plan_archived_for_logging_error()


def item_for_log(plan: MealPlan, meal_plan_item_id: UUID) -> MealPlanItem:
    for item in plan.items:
        if item.id == meal_plan_item_id:
            return item
    raise meal_plan_item_not_found_error()


def active_log_for_item(db: Session, meal_plan_item_id: UUID) -> MealLog | None:
    return (
        db.query(MealLog)
        .options(selectinload(MealLog.nutrients))
        .filter(
            MealLog.meal_plan_item_id == meal_plan_item_id,
            MealLog.status == MealLogStatus.ACTIVE.value,
        )
        .one_or_none()
    )


def active_logs_for_plan(db: Session, meal_plan_id: UUID) -> list[MealLog]:
    return (
        db.query(MealLog)
        .options(selectinload(MealLog.nutrients))
        .filter(
            MealLog.meal_plan_id == meal_plan_id,
            MealLog.status == MealLogStatus.ACTIVE.value,
        )
        .order_by(MealLog.log_date.asc(), MealLog.created_at.asc())
        .all()
    )


def nutrients_for_log_payload(
    db: Session,
    item: MealPlanItem,
    payload: MealLogRequest,
) -> list[NutrientSnapshotValue]:
    if payload.type == MealLogType.ATE_AS_PLANNED:
        return [
            NutrientSnapshotValue(
                code=nutrient.nutrient_code,
                name=nutrient.nutrient_name,
                amount=nutrient.amount,
                unit=nutrient.unit,
            )
            for nutrient in item.nutrients
        ]

    if payload.source_type == MealLogSourceType.FOOD:
        return nutrients_for_food_correction(
            db=db,
            food_id=payload.food_id,
            quantity_grams=payload.quantity_grams,
        )

    return nutrients_for_recipe_correction(
        db=db,
        recipe_id=payload.recipe_id,
        servings=payload.servings,
    )


def nutrients_for_food_correction(
    db: Session,
    food_id: UUID | None,
    quantity_grams: float | None,
) -> list[NutrientSnapshotValue]:
    if food_id is None or quantity_grams is None:
        raise meal_log_save_failed_error()
    food = (
        db.query(Food)
        .options(selectinload(Food.nutrients))
        .filter(Food.id == food_id)
        .one_or_none()
    )
    if food is None:
        raise food_not_found_error()
    return [
        NutrientSnapshotValue(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=unscale_amount(scale_amount(nutrient.amount * quantity_grams / 100)),
            unit=nutrient.unit,
        )
        for nutrient in food.nutrients
    ]


def nutrients_for_recipe_correction(
    db: Session,
    recipe_id: UUID | None,
    servings: float | None,
) -> list[NutrientSnapshotValue]:
    if recipe_id is None or servings is None:
        raise meal_log_save_failed_error()
    recipe = (
        db.query(Recipe)
        .options(selectinload(Recipe.nutrients))
        .filter(Recipe.id == recipe_id, Recipe.active.is_(True))
        .one_or_none()
    )
    if recipe is None:
        raise recipe_not_found_error()
    return [
        NutrientSnapshotValue(
            code=nutrient.nutrient_code,
            name=nutrient.nutrient_name,
            amount=unscale_amount(scale_amount(nutrient.per_serving_amount * servings)),
            unit=nutrient.unit,
        )
        for nutrient in recipe.nutrients
    ]


def apply_payload_to_log(
    meal_log: MealLog,
    payload: MealLogRequest,
    nutrient_complete: bool,
) -> None:
    meal_log.log_type = payload.type.value
    meal_log.status = MealLogStatus.ACTIVE.value
    meal_log.nutrient_complete = nutrient_complete
    meal_log.source_type = payload.source_type.value if payload.source_type is not None else None
    meal_log.food_id = payload.food_id
    meal_log.recipe_id = payload.recipe_id
    meal_log.quantity_grams = payload.quantity_grams
    meal_log.servings = payload.servings


def replace_log_nutrients(
    db: Session,
    meal_log: MealLog,
    nutrients: list[NutrientSnapshotValue],
) -> None:
    db.query(MealLogNutrientSnapshot).filter(
        MealLogNutrientSnapshot.meal_log_id == meal_log.id
    ).delete(synchronize_session=False)
    db.flush()
    for nutrient in nutrients:
        db.add(
            MealLogNutrientSnapshot(
                meal_log_id=meal_log.id,
                nutrient_code=nutrient.code,
                nutrient_name=nutrient.name,
                amount=nutrient.amount,
                unit=nutrient.unit,
            )
        )
    db.flush()


def totals_from_logs(logs: list[MealLog]) -> dict[str, float]:
    totals_scaled: dict[str, int] = {}
    for log in logs:
        for nutrient in log.nutrients:
            totals_scaled[nutrient.nutrient_code] = totals_scaled.get(
                nutrient.nutrient_code,
                0,
            ) + scale_amount(nutrient.amount)
    return {
        nutrient_code: unscale_amount(amount)
        for nutrient_code, amount in sorted(totals_scaled.items())
    }


def target_totals_from_plan(plan: MealPlan) -> dict[str, float]:
    targets = solver_targets_from_plan(plan)
    target_totals = {
        "calories": targets.calories,
        "protein": targets.protein_g,
        "carbohydrates": targets.carbohydrates_g,
        "fat": targets.fat_g,
    }
    for target in targets.micronutrients:
        target_totals[target.code] = target.target
    return target_totals


def differences(actual: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    return {
        nutrient_code: unscale_amount(
            scale_amount(actual.get(nutrient_code, 0.0)) - scale_amount(baseline_amount)
        )
        for nutrient_code, baseline_amount in sorted(baseline.items())
    }


def missing_nutrient_codes_for_log(meal_log: MealLog) -> list[str]:
    known_codes = {nutrient.nutrient_code for nutrient in meal_log.nutrients}
    return sorted(set(RECIPE_NUTRIENT_DEFINITION_BY_CODE) - known_codes)

def get_daily_intake_history(
    db: Session,
    user: User,
    start_date: date,
    end_date: date,
) -> list[dict]:
    logs = (
        db.query(MealLog)
        .options(selectinload(MealLog.nutrients))
        .filter(
            MealLog.user_id == user.id,
            MealLog.status == MealLogStatus.ACTIVE.value,
            MealLog.log_date >= start_date,
            MealLog.log_date <= end_date,
        )
        .order_by(MealLog.log_date.asc(), MealLog.created_at.asc())
        .all()
    )

    totals_by_date: dict[date, dict[str, float]] = {}

    current_date = start_date
    while current_date <= end_date:
        totals_by_date[current_date] = {
            "calories": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
        }
        current_date += timedelta(days=1)

    nutrient_field_map = {
        "calories": "calories",
        "protein": "protein_g",
        "carbohydrates": "carbs_g",
        "fat": "fat_g",
    }

    for log in logs:
        day_totals = totals_by_date[log.log_date]

        for nutrient in log.nutrients:
            field_name = nutrient_field_map.get(nutrient.nutrient_code)

            if field_name is not None:
                day_totals[field_name] += nutrient.amount

    return [
        {
            "date": log_date,
            "calories": round(values["calories"], 6),
            "protein_g": round(values["protein_g"], 6),
            "carbs_g": round(values["carbs_g"], 6),
            "fat_g": round(values["fat_g"], 6),
        }
        for log_date, values in sorted(totals_by_date.items())
    ]