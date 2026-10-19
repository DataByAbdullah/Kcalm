from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

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
    build_macro_deviations,
    build_micronutrient_coverage,
)
from app.models.meal_plan import (
    MealPlan,
    MealPlanItem,
    MealPlanItemIngredientSnapshot,
    MealPlanItemNutrientSnapshot,
    MealPlanMicronutrientTargetSnapshot,
)
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.schemas.meal_plan import MealPlanCreateRequest
from app.services.meal_solver_service import solve_daily_plan_preview


def plan_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="MEAL_PLAN_NOT_FOUND",
        message="Meal plan not found.",
    )


def plan_already_exists_error(plan_date: date) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="PLAN_ALREADY_EXISTS",
        message="A generated meal plan already exists for this user and date.",
        details={"plan_date": plan_date.isoformat()},
    )


def infeasible_plan_error(result: DailyPlanSolverResult) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="MEAL_PLAN_INFEASIBLE",
        message="A meal plan could not be generated for the requested constraints.",
        details={"infeasibility_reasons": result.infeasibility_reasons},
    )


def current_plan_date() -> date:
    return datetime.now(timezone.utc).date()


def create_daily_meal_plan(
    db: Session,
    user: User,
    payload: MealPlanCreateRequest,
    *,
    commit: bool = True,
    weekly_plan_id: UUID | None = None,
    additional_excluded_recipe_ids: list[UUID] | None = None,
    target_override: SolverNutritionTargets | None = None,
) -> MealPlan:
    plan_date = payload.plan_date or current_plan_date()
    ensure_no_generated_plan_for_date(db=db, user_id=user.id, plan_date=plan_date)

    solver_payload = payload_with_additional_exclusions(
        payload=payload,
        additional_excluded_recipe_ids=additional_excluded_recipe_ids or [],
    )
    solver_result = solve_daily_plan_preview(
        db=db,
        user=user,
        payload=solver_payload,
        target_override=target_override,
    )
    if solver_result.status is SolverStatus.INFEASIBLE:
        raise infeasible_plan_error(solver_result)

    plan = MealPlan(
        user_id=user.id,
        weekly_plan_id=weekly_plan_id,
        plan_date=plan_date,
        status=MealPlanStatus.GENERATED.value,
        solver_status=solver_result.status.value,
        calorie_target=solver_result.targets.calories,
        protein_target=solver_result.targets.protein_g,
        carbohydrate_target=solver_result.targets.carbohydrates_g,
        fat_target=solver_result.targets.fat_g,
        within_preferred_tolerance=solver_result.within_preferred_tolerance,
        objective_value=solver_result.objective_value,
        solve_time_seconds=solver_result.solve_time_seconds,
        candidate_count=solver_result.candidate_count,
    )

    try:
        db.add(plan)
        db.flush()
        persist_target_snapshots(db=db, plan=plan, solver_result=solver_result)
        persist_meal_plan_items(db=db, plan=plan, solver_result=solver_result)
        if commit:
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise plan_already_exists_error(plan_date) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=500,
            code="MEAL_PLAN_SAVE_FAILED",
            message="Meal plan could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    if not commit:
        return get_meal_plan_detail(db=db, user=user, meal_plan_id=plan.id)

    return get_meal_plan_detail(db=db, user=user, meal_plan_id=plan.id)


def payload_with_additional_exclusions(
    payload: MealPlanCreateRequest,
    additional_excluded_recipe_ids: list[UUID],
) -> MealPlanCreateRequest:
    if not additional_excluded_recipe_ids:
        return payload
    excluded_recipe_ids = [
        *payload.excluded_recipe_ids,
        *additional_excluded_recipe_ids,
    ]
    deduplicated = list(dict.fromkeys(excluded_recipe_ids))
    return payload.model_copy(update={"excluded_recipe_ids": deduplicated})


def ensure_no_generated_plan_for_date(
    db: Session,
    user_id: UUID,
    plan_date: date,
) -> None:
    existing = (
        db.query(MealPlan.id)
        .filter(
            MealPlan.user_id == user_id,
            MealPlan.plan_date == plan_date,
            MealPlan.status == MealPlanStatus.GENERATED.value,
        )
        .one_or_none()
    )
    if existing is not None:
        raise plan_already_exists_error(plan_date)


def persist_target_snapshots(
    db: Session,
    plan: MealPlan,
    solver_result: DailyPlanSolverResult,
) -> None:
    for target in solver_result.targets.micronutrients:
        db.add(
            MealPlanMicronutrientTargetSnapshot(
                meal_plan_id=plan.id,
                nutrient_code=target.code,
                nutrient_name=target.name,
                target=target.target,
                unit=target.unit,
                minimum_target=target.minimum_target,
                upper_limit=target.upper_limit,
                upper_limit_type=target.upper_limit_type,
            )
        )


def persist_meal_plan_items(
    db: Session,
    plan: MealPlan,
    solver_result: DailyPlanSolverResult,
) -> None:
    for position, meal in enumerate(solver_result.meals, start=1):
        item = MealPlanItem(
            meal_plan_id=plan.id,
            meal_type=meal.meal_type,
            recipe_id=meal.recipe_id,
            recipe_name_snapshot=meal.recipe_name,
            servings=meal.serving_amount,
            position=position,
        )
        db.add(item)
        db.flush()

        for nutrient_code, amount in meal.nutrition.items():
            definition = RECIPE_NUTRIENT_DEFINITION_BY_CODE.get(nutrient_code)
            if definition is None:
                continue
            db.add(
                MealPlanItemNutrientSnapshot(
                    meal_plan_item_id=item.id,
                    nutrient_code=nutrient_code,
                    nutrient_name=definition.name,
                    amount=amount,
                    unit=definition.unit,
                )
            )
        persist_item_ingredient_snapshots(
            db=db,
            item=item,
            recipe_id=meal.recipe_id,
            servings=meal.serving_amount,
        )


def persist_item_ingredient_snapshots(
    db: Session,
    item: MealPlanItem,
    recipe_id: UUID,
    servings: float,
) -> None:
    recipe = (
        db.query(Recipe)
        .options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.food))
        .filter(Recipe.id == recipe_id)
        .one_or_none()
    )
    if recipe is None:
        raise APIErrorException(
            status_code=500,
            code="MEAL_PLAN_INGREDIENT_SNAPSHOT_FAILED",
            message="Meal plan ingredient snapshots could not be created.",
            details={"recipe_id": str(recipe_id), "reason": "recipe_not_found"},
        )

    quantities_by_food_id: dict[UUID, int] = {}
    food_names_by_id: dict[UUID, str] = {}
    for ingredient in recipe.ingredients:
        if ingredient.food is None:
            raise APIErrorException(
                status_code=500,
                code="MEAL_PLAN_INGREDIENT_SNAPSHOT_FAILED",
                message="Meal plan ingredient snapshots could not be created.",
                details={
                    "recipe_id": str(recipe_id),
                    "ingredient_id": str(ingredient.id),
                    "reason": "ingredient_food_not_found",
                },
            )
        quantity_grams = float(ingredient.quantity_grams) * servings
        food_id = ingredient.food_id
        quantities_by_food_id[food_id] = quantities_by_food_id.get(food_id, 0) + scale_amount(
            quantity_grams
        )
        food_names_by_id[food_id] = ingredient.food.name

    for food_id in sorted(quantities_by_food_id, key=str):
        db.add(
            MealPlanItemIngredientSnapshot(
                meal_plan_item_id=item.id,
                food_id=food_id,
                food_name_snapshot=food_names_by_id[food_id],
                quantity_grams=unscale_amount(quantities_by_food_id[food_id]),
            )
        )


def get_meal_plan_detail(
    db: Session,
    user: User,
    meal_plan_id: UUID,
) -> MealPlan:
    plan = (
        db.query(MealPlan)
        .options(
            selectinload(MealPlan.items).selectinload(MealPlanItem.nutrients),
            selectinload(MealPlan.items).selectinload(MealPlanItem.ingredient_snapshots),
            selectinload(MealPlan.micronutrient_targets),
        )
        .filter(MealPlan.id == meal_plan_id, MealPlan.user_id == user.id)
        .one_or_none()
    )
    if plan is None:
        raise plan_not_found_error()
    return plan


def list_meal_plans(
    db: Session,
    user: User,
    plan_date: date | None = None,
    status: MealPlanStatus | None = None,
) -> tuple[list[MealPlan], int]:
    effective_status = status or MealPlanStatus.GENERATED
    query = (
        db.query(MealPlan)
        .options(
            selectinload(MealPlan.items).selectinload(MealPlanItem.nutrients),
            selectinload(MealPlan.items).selectinload(MealPlanItem.ingredient_snapshots),
            selectinload(MealPlan.micronutrient_targets),
        )
        .filter(MealPlan.user_id == user.id, MealPlan.status == effective_status.value)
    )
    if plan_date is not None:
        query = query.filter(MealPlan.plan_date == plan_date)

    total = query.count()
    plans = query.order_by(MealPlan.plan_date.desc(), MealPlan.created_at.desc()).all()
    return plans, total


def archive_meal_plan(
    db: Session,
    user: User,
    meal_plan_id: UUID,
) -> None:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    if plan.status != MealPlanStatus.ARCHIVED.value:
        plan.status = MealPlanStatus.ARCHIVED.value
        db.commit()


def daily_totals_from_plan(plan: MealPlan) -> dict[str, float]:
    totals_scaled: dict[str, int] = {}
    for item in plan.items:
        for nutrient in item.nutrients:
            totals_scaled[nutrient.nutrient_code] = totals_scaled.get(
                nutrient.nutrient_code,
                0,
            ) + scale_amount(nutrient.amount)
    return {
        nutrient_code: unscale_amount(amount)
        for nutrient_code, amount in sorted(totals_scaled.items())
    }


def solver_targets_from_plan(plan: MealPlan) -> SolverNutritionTargets:
    return SolverNutritionTargets(
        calories=plan.calorie_target,
        protein_g=plan.protein_target,
        carbohydrates_g=plan.carbohydrate_target,
        fat_g=plan.fat_target,
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
            for target in plan.micronutrient_targets
        ],
    )


def deviations_from_plan(plan: MealPlan):
    return build_macro_deviations(
        daily_totals=daily_totals_from_plan(plan),
        targets=solver_targets_from_plan(plan),
        tolerance=0.05,
    )


def micronutrient_coverage_from_plan(plan: MealPlan):
    return build_micronutrient_coverage(
        daily_totals=daily_totals_from_plan(plan),
        micronutrient_targets=solver_targets_from_plan(plan).micronutrients,
    )


def core_daily_totals(plan: MealPlan) -> dict[str, float]:
    totals = daily_totals_from_plan(plan)
    return {
        code: totals.get(code, 0.0)
        for code in (CALORIES_CODE, PROTEIN_CODE, CARBOHYDRATES_CODE, FAT_CODE)
        if code in totals
    }
