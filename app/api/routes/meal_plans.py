from datetime import date
from fastapi import APIRouter, Depends
from fastapi import Query, Response, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.enums import MealPlanStatus
from app.core.security import get_current_user
from app.meal_planning.solver import DailyPlanSolverResult
from app.models.meal_plan import MealPlan
from app.models.user import User
from app.schemas.meal_plan import (
    DailySolverPreviewRequest,
    DailySolverPreviewResponse,
    MealPlanCreateRequest,
    MealPlanListResponse,
    MealPlanResponse,
    MealPlanSummaryResponse,
    MealSwapRequest,
    MicronutrientCoverageResponse,
    NutritionDeviationResponse,
    PersistedMealPlanItemResponse,
    SelectedMealResponse,
    SolverMicronutrientTargetResponse,
    SolverTargetsResponse,
)
from app.schemas.adaptive_planning import (
    AdaptivePlanRequest,
    AdaptivePlanResponse,
    AdaptivePolicyResponse,
    AdaptivePreviewResponse,
    AdaptiveTargetResponse,
)
from app.schemas.ai import NaturalLanguageConstraintRequest
from app.schemas.meal_log import (
    AdherenceSummaryResponse,
    MealLogNutrientResponse,
    MealLogRequest,
    MealLogResponse,
    MealPlanActualSummaryResponse,
)
from app.services.adaptive_planning_service import (
    AdaptivePolicy,
    AdaptiveTarget,
    create_adaptive_next_day_plan,
    preview_adaptive_next_day_plan,
)
from app.services.ai_constraint_service import swap_meal_plan_item_from_text
from app.services.meal_log_service import (
    active_logs_for_plan,
    get_actual_summary,
    log_meal_plan_item,
    missing_nutrient_codes_for_log,
    reset_meal_plan_item_log,
)
from app.services.meal_plan_service import (
    archive_meal_plan,
    create_daily_meal_plan,
    daily_totals_from_plan,
    deviations_from_plan,
    get_meal_plan_detail,
    list_meal_plans,
    micronutrient_coverage_from_plan,
    solver_targets_from_plan,
)
from app.services.meal_solver_service import solve_daily_plan_preview
from app.services.meal_swap_service import swap_meal_plan_item


router = APIRouter()


def meal_log_to_response(meal_log) -> MealLogResponse:
    known_codes = [nutrient.nutrient_code for nutrient in meal_log.nutrients]
    return MealLogResponse(
        meal_log_id=meal_log.id,
        meal_plan_id=meal_log.meal_plan_id,
        meal_plan_item_id=meal_log.meal_plan_item_id,
        log_date=meal_log.log_date,
        type=meal_log.log_type,
        status=meal_log.status,
        source_type=meal_log.source_type,
        food_id=meal_log.food_id,
        recipe_id=meal_log.recipe_id,
        quantity_grams=meal_log.quantity_grams,
        servings=meal_log.servings,
        nutrient_complete=meal_log.nutrient_complete,
        nutrients=[
            MealLogNutrientResponse(
                code=nutrient.nutrient_code,
                name=nutrient.nutrient_name,
                amount=nutrient.amount,
                unit=nutrient.unit,
            )
            for nutrient in meal_log.nutrients
        ],
        known_nutrient_codes=known_codes,
        missing_nutrient_codes=missing_nutrient_codes_for_log(meal_log),
        created_at=meal_log.created_at,
        updated_at=meal_log.updated_at,
    )


def actual_summary_to_response(summary) -> MealPlanActualSummaryResponse:
    return MealPlanActualSummaryResponse(
        meal_plan_id=summary.plan.id,
        plan_date=summary.plan.plan_date,
        planned_totals=summary.planned_totals,
        actual_totals=summary.actual_totals,
        targets=targets_to_response(summary.plan),
        difference_actual_vs_planned=summary.difference_actual_vs_planned,
        difference_actual_vs_target=summary.difference_actual_vs_target,
        actual_known_nutrient_codes=summary.actual_known_nutrient_codes,
        missing_actual_target_nutrient_codes=summary.missing_actual_target_nutrient_codes,
        adherence=AdherenceSummaryResponse(
            planned_meals_count=summary.planned_meals_count,
            logged_meals_count=summary.logged_meals_count,
            unlogged_meals_count=summary.unlogged_meals_count,
            ate_as_planned_count=summary.ate_as_planned_count,
            corrected_count=summary.corrected_count,
            adherence_percent=summary.adherence_percent,
        ),
    )


def adaptive_policy_to_response(policy: AdaptivePolicy) -> AdaptivePolicyResponse:
    return AdaptivePolicyResponse(
        policy_version=policy.policy_version,
        compensation_fraction=policy.compensation_fraction,
        max_adjustment_kcal=policy.max_adjustment_kcal,
        max_adjustment_percent=policy.max_adjustment_percent,
        minimum_adjusted_calories=policy.minimum_adjusted_calories,
    )


def adaptive_target_to_response(target: AdaptiveTarget) -> AdaptiveTargetResponse:
    return AdaptiveTargetResponse(
        source_plan_id=target.source_plan_id,
        base_calorie_target=target.base_calorie_target,
        previous_day_actual_calories=target.previous_day_actual_calories,
        previous_day_calorie_deviation=target.previous_day_calorie_deviation,
        compensation_fraction=target.compensation_fraction,
        raw_compensation_amount=target.raw_compensation_amount,
        compensation_amount=target.compensation_amount,
        adjusted_calorie_target=target.adjusted_calorie_target,
        base_macro_targets=target.base_macro_targets,
        adjusted_macro_targets=target.adjusted_macro_targets,
        micronutrient_strategy=target.micronutrient_strategy,
        safety_caps_applied=target.safety_caps_applied,
        policy_version=target.policy_version,
    )


def adaptive_preview_to_response(preview) -> AdaptivePreviewResponse:
    return AdaptivePreviewResponse(
        source_plan_id=preview.source_plan.id,
        next_day_date=preview.next_day_date,
        actual_totals=preview.actual_totals,
        target_totals=preview.target_totals,
        deviation=preview.deviation,
        micronutrient_deviation=preview.micronutrient_deviation,
        policy=adaptive_policy_to_response(preview.policy),
        adjusted_targets=adaptive_target_to_response(preview.adjusted_target),
        solver_preview=solver_result_to_response(preview.solver_result),
    )


def adaptive_plan_to_response(creation) -> AdaptivePlanResponse:
    return AdaptivePlanResponse(
        source_plan_id=creation.source_plan.id,
        adaptation=adaptive_target_to_response(creation.adjusted_target),
        plan=plan_to_response(creation.plan),
    )


def solver_result_to_response(
    result: DailyPlanSolverResult,
) -> DailySolverPreviewResponse:
    return DailySolverPreviewResponse(
        status=result.status,
        meals=[
            SelectedMealResponse(
                meal_type=meal.meal_type,
                recipe_id=meal.recipe_id,
                recipe_name=meal.recipe_name,
                serving_amount=meal.serving_amount,
                nutrition=meal.nutrition,
            )
            for meal in result.meals
        ],
        daily_totals=result.daily_totals,
        targets=SolverTargetsResponse(
            calories=result.targets.calories,
            protein_g=result.targets.protein_g,
            carbohydrates_g=result.targets.carbohydrates_g,
            fat_g=result.targets.fat_g,
            micronutrients=[
                SolverMicronutrientTargetResponse(
                    code=target.code,
                    name=target.name,
                    target=target.target,
                    unit=target.unit,
                    minimum_target=target.minimum_target,
                    upper_limit=target.upper_limit,
                    upper_limit_type=target.upper_limit_type,
                )
                for target in result.targets.micronutrients
            ],
        ),
        deviations=[
            NutritionDeviationResponse(
                nutrient_code=deviation.nutrient_code,
                nutrient_name=deviation.nutrient_name,
                target=deviation.target,
                actual=deviation.actual,
                unit=deviation.unit,
                deviation_amount=deviation.deviation_amount,
                deviation_percent=deviation.deviation_percent,
                tolerance_lower=deviation.tolerance_lower,
                tolerance_upper=deviation.tolerance_upper,
                status=deviation.status,
            )
            for deviation in result.deviations
        ],
        micronutrient_coverage=[
            MicronutrientCoverageResponse(
                nutrient_code=coverage.nutrient_code,
                nutrient_name=coverage.nutrient_name,
                target=coverage.target,
                actual=coverage.actual,
                unit=coverage.unit,
                coverage_percent=coverage.coverage_percent,
                met=coverage.met,
                upper_limit=coverage.upper_limit,
                upper_limit_type=coverage.upper_limit_type,
                upper_limit_applicable=coverage.upper_limit_applicable,
                upper_limit_exceeded=coverage.upper_limit_exceeded,
            )
            for coverage in result.micronutrient_coverage
        ],
        within_preferred_tolerance=result.within_preferred_tolerance,
        objective_value=result.objective_value,
        infeasibility_reasons=result.infeasibility_reasons,
        solve_time_seconds=result.solve_time_seconds,
        candidate_count=result.candidate_count,
    )


def targets_to_response(plan: MealPlan) -> SolverTargetsResponse:
    targets = solver_targets_from_plan(plan)
    return SolverTargetsResponse(
        calories=targets.calories,
        protein_g=targets.protein_g,
        carbohydrates_g=targets.carbohydrates_g,
        fat_g=targets.fat_g,
        micronutrients=[
            SolverMicronutrientTargetResponse(
                code=target.code,
                name=target.name,
                target=target.target,
                unit=target.unit,
                minimum_target=target.minimum_target,
                upper_limit=target.upper_limit,
                upper_limit_type=target.upper_limit_type,
            )
            for target in targets.micronutrients
        ],
    )


def deviations_to_response(plan: MealPlan) -> list[NutritionDeviationResponse]:
    return [
        NutritionDeviationResponse(
            nutrient_code=deviation.nutrient_code,
            nutrient_name=deviation.nutrient_name,
            target=deviation.target,
            actual=deviation.actual,
            unit=deviation.unit,
            deviation_amount=deviation.deviation_amount,
            deviation_percent=deviation.deviation_percent,
            tolerance_lower=deviation.tolerance_lower,
            tolerance_upper=deviation.tolerance_upper,
            status=deviation.status,
        )
        for deviation in deviations_from_plan(plan)
    ]


def micronutrient_coverage_to_response(plan: MealPlan) -> list[MicronutrientCoverageResponse]:
    return [
        MicronutrientCoverageResponse(
            nutrient_code=coverage.nutrient_code,
            nutrient_name=coverage.nutrient_name,
            target=coverage.target,
            actual=coverage.actual,
            unit=coverage.unit,
            coverage_percent=coverage.coverage_percent,
            met=coverage.met,
            upper_limit=coverage.upper_limit,
            upper_limit_type=coverage.upper_limit_type,
            upper_limit_applicable=coverage.upper_limit_applicable,
            upper_limit_exceeded=coverage.upper_limit_exceeded,
        )
        for coverage in micronutrient_coverage_from_plan(plan)
    ]


def plan_to_response(plan: MealPlan) -> MealPlanResponse:
    return MealPlanResponse(
        meal_plan_id=plan.id,
        plan_date=plan.plan_date,
        status=MealPlanStatus(plan.status),
        solver_status=plan.solver_status,
        meals=[
            PersistedMealPlanItemResponse(
                id=item.id,
                meal_type=item.meal_type,
                recipe_id=item.recipe_id,
                recipe_name=item.recipe_name_snapshot,
                servings=item.servings,
                position=item.position,
                nutrition={
                    nutrient.nutrient_code: nutrient.amount
                    for nutrient in item.nutrients
                },
            )
            for item in plan.items
        ],
        daily_totals=daily_totals_from_plan(plan),
        targets=targets_to_response(plan),
        deviations=deviations_to_response(plan),
        micronutrient_coverage=micronutrient_coverage_to_response(plan),
        within_preferred_tolerance=plan.within_preferred_tolerance,
        objective_value=plan.objective_value,
        solve_time_seconds=plan.solve_time_seconds,
        candidate_count=plan.candidate_count,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def plan_to_summary_response(plan: MealPlan) -> MealPlanSummaryResponse:
    return MealPlanSummaryResponse(
        meal_plan_id=plan.id,
        plan_date=plan.plan_date,
        status=MealPlanStatus(plan.status),
        solver_status=plan.solver_status,
        daily_totals=daily_totals_from_plan(plan),
        within_preferred_tolerance=plan.within_preferred_tolerance,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.post("/solve/preview", response_model=DailySolverPreviewResponse)
def preview_daily_solver(
    payload: DailySolverPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailySolverPreviewResponse:
    result = solve_daily_plan_preview(db=db, user=current_user, payload=payload)
    return solver_result_to_response(result)


@router.post("", response_model=MealPlanResponse, status_code=status.HTTP_201_CREATED)
def create_meal_plan(
    payload: MealPlanCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanResponse:
    plan = create_daily_meal_plan(db=db, user=current_user, payload=payload)
    return plan_to_response(plan)


@router.get("", response_model=MealPlanListResponse)
def read_meal_plans(
    plan_date: date | None = Query(default=None),
    status_filter: MealPlanStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanListResponse:
    plans, total = list_meal_plans(
        db=db,
        user=current_user,
        plan_date=plan_date,
        status=status_filter,
    )
    return MealPlanListResponse(
        items=[plan_to_summary_response(plan) for plan in plans],
        total=total,
    )


@router.get("/{meal_plan_id}", response_model=MealPlanResponse)
def read_meal_plan(
    meal_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanResponse:
    plan = get_meal_plan_detail(db=db, user=current_user, meal_plan_id=meal_plan_id)
    return plan_to_response(plan)


@router.get("/{meal_plan_id}/logs", response_model=list[MealLogResponse])
def read_meal_plan_logs(
    meal_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MealLogResponse]:
    plan = get_meal_plan_detail(db=db, user=current_user, meal_plan_id=meal_plan_id)
    return [meal_log_to_response(log) for log in active_logs_for_plan(db, plan.id)]


@router.get("/{meal_plan_id}/actual-summary", response_model=MealPlanActualSummaryResponse)
def read_actual_summary(
    meal_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanActualSummaryResponse:
    summary = get_actual_summary(db=db, user=current_user, meal_plan_id=meal_plan_id)
    return actual_summary_to_response(summary)


@router.post(
    "/{source_plan_id}/adaptive-preview",
    response_model=AdaptivePreviewResponse,
)
def preview_adaptive_next_day(
    source_plan_id: UUID,
    payload: AdaptivePlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdaptivePreviewResponse:
    preview = preview_adaptive_next_day_plan(
        db=db,
        user=current_user,
        source_plan_id=source_plan_id,
        payload=payload or AdaptivePlanRequest(),
    )
    return adaptive_preview_to_response(preview)


@router.post(
    "/{source_plan_id}/generate-next-day",
    response_model=AdaptivePlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_adaptive_next_day(
    source_plan_id: UUID,
    payload: AdaptivePlanRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdaptivePlanResponse:
    creation = create_adaptive_next_day_plan(
        db=db,
        user=current_user,
        source_plan_id=source_plan_id,
        payload=payload or AdaptivePlanRequest(),
    )
    return adaptive_plan_to_response(creation)


@router.post(
    "/{meal_plan_id}/items/{meal_plan_item_id}/log",
    response_model=MealLogResponse,
)
def log_meal_item(
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    payload: MealLogRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealLogResponse:
    meal_log = log_meal_plan_item(
        db=db,
        user=current_user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
        payload=payload,
    )
    return meal_log_to_response(meal_log)


@router.delete(
    "/{meal_plan_id}/items/{meal_plan_item_id}/log",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_meal_item_log(
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    reset_meal_plan_item_log(
        db=db,
        user=current_user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meal_plan_id}/items/{meal_plan_item_id}/swap",
    response_model=MealPlanResponse,
)
def swap_meal_plan_item_endpoint(
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    payload: MealSwapRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanResponse:
    plan = swap_meal_plan_item(
        db=db,
        user=current_user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
        payload=payload,
    )
    return plan_to_response(plan)


@router.post(
    "/{meal_plan_id}/items/{meal_plan_item_id}/ai-swap",
    response_model=MealPlanResponse,
)
def ai_swap_meal_plan_item_endpoint(
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    payload: NaturalLanguageConstraintRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MealPlanResponse:
    plan = swap_meal_plan_item_from_text(
        db=db,
        user=current_user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
        text=payload.text,
    )
    return plan_to_response(plan)


@router.delete("/{meal_plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal_plan(
    meal_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    archive_meal_plan(db=db, user=current_user, meal_plan_id=meal_plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
