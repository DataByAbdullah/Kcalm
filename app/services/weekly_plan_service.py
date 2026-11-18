from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.enums import MealPlanStatus, WeeklyMealPlanStatus
from app.core.exceptions import APIErrorException
from app.models.meal_plan import MealPlan, MealPlanItem, WeeklyMealPlan
from app.models.user import User
from app.schemas.meal_plan import MealPlanCreateRequest
from app.schemas.weekly_plan import WeeklyMealPlanCreateRequest
from app.services.meal_plan_consumption_service import (
    ensure_dates_have_no_consumption,
    lock_user_meal_plans,
    planning_snapshot,
)
from app.services.meal_plan_service import (
    ensure_profile_unchanged,
    persist_prepared_daily_plan,
    prepare_daily_meal_plan,
)


WEEK_LENGTH_DAYS = 7


def weekly_plan_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="WEEKLY_PLAN_NOT_FOUND",
        message="Weekly meal plan not found.",
    )


def weekly_plan_already_exists_error(start_date: date, end_date: date) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="WEEKLY_PLAN_ALREADY_EXISTS",
        message="A generated weekly meal plan already exists for this user and date range.",
        details={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    )


def daily_plan_conflict_error(conflict_dates: list[date]) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK",
        message="A generated daily meal plan already exists inside the requested week.",
        details={"conflict_dates": [item.isoformat() for item in conflict_dates]},
    )


def weekly_plan_infeasible_error(
    failed_date: date,
    cause: APIErrorException,
) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="WEEKLY_PLAN_INFEASIBLE",
        message="Weekly meal plan could not be generated for every requested date.",
        details={
            "failed_date": failed_date.isoformat(),
            "cause_code": cause.code,
            "cause_details": cause.details,
        },
    )


def weekly_plan_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="WEEKLY_PLAN_SAVE_FAILED",
        message="Weekly meal plan could not be saved.",
    )


def create_weekly_plan(
    db: Session,
    user: User,
    payload: WeeklyMealPlanCreateRequest,
) -> WeeklyMealPlan:
    start_date = payload.start_date
    end_date = week_end_date(start_date)
    prepared_days = []
    previous_day_recipe_ids: list[UUID] = []
    with planning_snapshot(db) as snapshot:
        ensure_no_generated_week_for_range(snapshot, user.id, start_date, end_date)
        ensure_no_generated_daily_conflicts(snapshot, user.id, start_date, end_date)
        ensure_dates_have_no_consumption(snapshot, user.id, start_date, end_date)
        for plan_date in week_dates(start_date):
            daily_payload = daily_payload_for_date(payload=payload, plan_date=plan_date)
            try:
                prepared = prepare_daily_meal_plan(
                    snapshot, user, daily_payload,
                    additional_excluded_recipe_ids=previous_day_recipe_ids,
                )
            except APIErrorException as exc:
                if exc.code != "MEAL_PLAN_INFEASIBLE":
                    raise
                if not previous_day_recipe_ids:
                    raise weekly_plan_infeasible_error(plan_date, exc) from exc
                try:
                    prepared = prepare_daily_meal_plan(snapshot, user, daily_payload)
                except APIErrorException as retry_exc:
                    if retry_exc.code == "MEAL_PLAN_INFEASIBLE":
                        raise weekly_plan_infeasible_error(plan_date, retry_exc) from retry_exc
                    raise
            prepared_days.append(prepared)
            previous_day_recipe_ids = sorted([meal.recipe_id for meal in prepared.result.meals], key=str)

    week = WeeklyMealPlan(
        user_id=user.id, start_date=start_date, end_date=end_date,
        status=WeeklyMealPlanStatus.GENERATED.value,
    )
    try:
        lock_user_meal_plans(db, user.id)
        ensure_no_generated_week_for_range(db, user.id, start_date, end_date)
        ensure_no_generated_daily_conflicts(db, user.id, start_date, end_date)
        ensure_dates_have_no_consumption(db, user.id, start_date, end_date)
        ensure_profile_unchanged(db, user, prepared_days[0].profile)
        db.add(week)
        db.flush()
        for prepared in prepared_days:
            persist_prepared_daily_plan(db, user, prepared, commit=False, weekly_plan_id=week.id)

        db.commit()
        db.expire_all()
    except IntegrityError as exc:
        db.rollback()
        raise weekly_plan_already_exists_error(start_date, end_date) from exc
    except APIErrorException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise weekly_plan_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_weekly_plan_detail(db=db, user=user, weekly_plan_id=week.id)


def week_end_date(start_date: date) -> date:
    return start_date + timedelta(days=WEEK_LENGTH_DAYS - 1)


def week_dates(start_date: date) -> list[date]:
    return [start_date + timedelta(days=offset) for offset in range(WEEK_LENGTH_DAYS)]


def ensure_no_generated_week_for_range(
    db: Session,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> None:
    existing = (
        db.query(WeeklyMealPlan.id)
        .filter(
            WeeklyMealPlan.user_id == user_id,
            WeeklyMealPlan.start_date == start_date,
            WeeklyMealPlan.end_date == end_date,
            WeeklyMealPlan.status == WeeklyMealPlanStatus.GENERATED.value,
        )
        .one_or_none()
    )
    if existing is not None:
        raise weekly_plan_already_exists_error(start_date=start_date, end_date=end_date)


def ensure_no_generated_daily_conflicts(
    db: Session,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> None:
    conflict_dates = [
        item[0]
        for item in (
            db.query(MealPlan.plan_date)
            .filter(
                MealPlan.user_id == user_id,
                MealPlan.status == MealPlanStatus.GENERATED.value,
                MealPlan.plan_date >= start_date,
                MealPlan.plan_date <= end_date,
            )
            .order_by(MealPlan.plan_date.asc())
            .all()
        )
    ]
    if conflict_dates:
        raise daily_plan_conflict_error(conflict_dates)


def daily_payload_for_date(
    payload: WeeklyMealPlanCreateRequest,
    plan_date: date,
) -> MealPlanCreateRequest:
    return MealPlanCreateRequest(
        **payload.model_dump(exclude={"start_date"}),
        plan_date=plan_date,
    )


def get_weekly_plan_detail(
    db: Session,
    user: User,
    weekly_plan_id: UUID,
) -> WeeklyMealPlan:
    week = (
        db.query(WeeklyMealPlan)
        .options(
            selectinload(WeeklyMealPlan.daily_plans)
            .selectinload(MealPlan.items)
            .selectinload(MealPlanItem.recipe),
            selectinload(WeeklyMealPlan.daily_plans)
            .selectinload(MealPlan.items)
            .selectinload(MealPlanItem.nutrients),
            selectinload(WeeklyMealPlan.daily_plans)
            .selectinload(MealPlan.items)
            .selectinload(MealPlanItem.ingredient_snapshots),
            selectinload(WeeklyMealPlan.daily_plans).selectinload(
                MealPlan.micronutrient_targets
            ),
        )
        .filter(WeeklyMealPlan.id == weekly_plan_id, WeeklyMealPlan.user_id == user.id)
        .populate_existing()
        .one_or_none()
    )
    if week is None:
        raise weekly_plan_not_found_error()
    return week


def list_weekly_plans(
    db: Session,
    user: User,
    status: WeeklyMealPlanStatus | None = None,
) -> tuple[list[WeeklyMealPlan], int]:
    effective_status = status or WeeklyMealPlanStatus.GENERATED
    query = (
        db.query(WeeklyMealPlan)
        .options(selectinload(WeeklyMealPlan.daily_plans))
        .filter(
            WeeklyMealPlan.user_id == user.id,
            WeeklyMealPlan.status == effective_status.value,
        )
    )
    total = query.count()
    weeks = query.order_by(
        WeeklyMealPlan.start_date.desc(),
        WeeklyMealPlan.created_at.desc(),
    ).all()
    return weeks, total


def archive_weekly_plan(
    db: Session,
    user: User,
    weekly_plan_id: UUID,
) -> None:
    lock_user_meal_plans(db, user.id)
    week = get_weekly_plan_detail(db=db, user=user, weekly_plan_id=weekly_plan_id)
    # Reject the entire operation before mutating any member of a consumed week.
    if week.status != WeeklyMealPlanStatus.ARCHIVED.value or any(
        day.status == MealPlanStatus.GENERATED.value for day in week.daily_plans
    ):
        ensure_dates_have_no_consumption(
            db, user.id, week.start_date, week.end_date,
            details={"weekly_plan_id": str(week.id)},
        )
    week.status = WeeklyMealPlanStatus.ARCHIVED.value
    for daily_plan in week.daily_plans:
        if daily_plan.status != MealPlanStatus.ARCHIVED.value:
            daily_plan.status = MealPlanStatus.ARCHIVED.value
    db.commit()
