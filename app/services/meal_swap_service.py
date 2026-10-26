from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.enums import MealPlanStatus
from app.core.exceptions import APIErrorException
from app.meal_planning.scaling import scale_amount, unscale_amount
from app.meal_planning.solver import (
    DailyPlanSolverInput,
    MealSlot,
    SolverConfig,
    SolverStatus,
    required_nutrient_codes,
    solve_daily_plan,
)
from app.models.meal_plan import (
    MealPlan,
    MealPlanItem,
    MealPlanItemIngredientSnapshot,
    MealPlanItemNutrientSnapshot,
)
from app.models.user import User
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.schemas.meal_plan import MealSwapRequest
from app.services.meal_plan_service import (
    get_meal_plan_detail,
    persist_item_ingredient_snapshots,
    solver_targets_from_plan,
)
from app.services.recipe_candidate_service import get_recipe_candidates


def meal_plan_archived_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="MEAL_PLAN_ARCHIVED",
        message="Archived meal plans cannot be swapped.",
    )


def meal_plan_item_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="MEAL_PLAN_ITEM_NOT_FOUND",
        message="Meal plan item not found.",
    )


def no_swap_candidate_error(details: dict | None = None) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="NO_SWAP_CANDIDATE",
        message="No eligible replacement meal could be found.",
        details=details or {},
    )


def unsupported_swap_constraint_error(constraint: str) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="UNSUPPORTED_SWAP_CONSTRAINT",
        message="Swap constraint is not supported by the current structured data model.",
        details={"constraint": constraint},
    )


def swap_meal_plan_item(
    db: Session,
    user: User,
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    payload: MealSwapRequest,
) -> MealPlan:
    validate_supported_swap_constraints(payload)
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    if plan.status == MealPlanStatus.ARCHIVED.value:
        raise meal_plan_archived_error()

    target_item = item_for_swap(plan=plan, meal_plan_item_id=meal_plan_item_id)
    locked_items = [item for item in plan.items if item.id != target_item.id]
    targets = solver_targets_from_plan(plan)
    target_codes = list(required_nutrient_codes(targets))
    excluded_recipe_ids = excluded_recipe_ids_for_swap(
        target_item=target_item,
        locked_items=locked_items,
        request_excluded_recipe_ids=payload.excluded_recipe_ids,
    )

    candidate_result = get_recipe_candidates(
        db=db,
        user=user,
        meal_type=target_item.meal_type,
        max_total_time_minutes=payload.max_total_time_minutes,
        require_complete_nutrition=payload.require_complete_nutrition,
        required_nutrient_codes=target_codes,
        excluded_recipe_ids=excluded_recipe_ids,
        required_tags=payload.required_tags,
        excluded_tags=payload.excluded_tags,
    )
    candidates = candidate_result.candidates
    if payload.recipe_id is not None:
        candidates = [
            candidate for candidate in candidates if candidate.recipe_id == payload.recipe_id
        ]
    if not candidates:
        raise no_swap_candidate_error(
            {
                "meal_type": target_item.meal_type,
                "exclusion_summary": {
                    reason.value: count
                    for reason, count in candidate_result.exclusion_summary.items()
                },
            }
        )

    solver_result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=candidates,
            targets=targets,
            meal_slots=[MealSlot(meal_type=target_item.meal_type, required=True)],
            config=SolverConfig(
                time_limit_seconds=(
                    payload.solver_time_limit_seconds
                    or SolverConfig().time_limit_seconds
                )
            ),
            locked_nutrition=nutrition_totals_for_items(locked_items),
        )
    )
    if solver_result.status is SolverStatus.INFEASIBLE or not solver_result.meals:
        raise no_swap_candidate_error(
            {
                "meal_type": target_item.meal_type,
                "infeasibility_reasons": solver_result.infeasibility_reasons,
            }
        )

    replacement = solver_result.meals[0]

    try:
        target_item.recipe_id = replacement.recipe_id
        target_item.recipe_name_snapshot = replacement.recipe_name
        target_item.servings = replacement.serving_amount
        db.query(MealPlanItemNutrientSnapshot).filter(
            MealPlanItemNutrientSnapshot.meal_plan_item_id == target_item.id
        ).delete(synchronize_session=False)
        db.query(MealPlanItemIngredientSnapshot).filter(
            MealPlanItemIngredientSnapshot.meal_plan_item_id == target_item.id
        ).delete(synchronize_session=False)

        for nutrient_code, amount in replacement.nutrition.items():
            definition = RECIPE_NUTRIENT_DEFINITION_BY_CODE.get(nutrient_code)
            if definition is None:
                continue
            db.add(
                MealPlanItemNutrientSnapshot(
                    meal_plan_item_id=target_item.id,
                    nutrient_code=nutrient_code,
                    nutrient_name=definition.name,
                    amount=amount,
                    unit=definition.unit,
                )
            )
        persist_item_ingredient_snapshots(
            db=db,
            item=target_item,
            recipe_id=replacement.recipe_id,
            servings=replacement.serving_amount,
        )

        plan.solver_status = solver_result.status.value
        plan.within_preferred_tolerance = solver_result.within_preferred_tolerance
        plan.objective_value = solver_result.objective_value
        plan.solve_time_seconds = solver_result.solve_time_seconds
        plan.candidate_count = solver_result.candidate_count
        db.commit()
        db.expire_all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=500,
            code="MEAL_SWAP_SAVE_FAILED",
            message="Meal swap could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return get_meal_plan_detail(db=db, user=user, meal_plan_id=plan.id)


def validate_supported_swap_constraints(payload: MealSwapRequest) -> None:
    if payload.different_protein:
        raise unsupported_swap_constraint_error("different_protein")
    if payload.eating_out:
        raise unsupported_swap_constraint_error("eating_out")


def item_for_swap(plan: MealPlan, meal_plan_item_id: UUID) -> MealPlanItem:
    for item in plan.items:
        if item.id == meal_plan_item_id:
            return item
    raise meal_plan_item_not_found_error()


def excluded_recipe_ids_for_swap(
    target_item: MealPlanItem,
    locked_items: list[MealPlanItem],
    request_excluded_recipe_ids: list[UUID],
) -> list[UUID]:
    excluded_ids = {target_item.recipe_id, *request_excluded_recipe_ids}
    excluded_ids.update(item.recipe_id for item in locked_items)
    return sorted(excluded_ids, key=str)


def nutrition_totals_for_items(items: list[MealPlanItem]) -> dict[str, float]:
    totals_scaled: dict[str, int] = {}
    for item in items:
        for nutrient in item.nutrients:
            totals_scaled[nutrient.nutrient_code] = totals_scaled.get(
                nutrient.nutrient_code,
                0,
            ) + scale_amount(nutrient.amount)
    return {
        nutrient_code: unscale_amount(amount)
        for nutrient_code, amount in sorted(totals_scaled.items())
    }
