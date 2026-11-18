from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.core.enums import MealPlanStatus, WeeklyMealPlanStatus
from app.models.meal_plan import MealPlan, WeeklyMealPlan
from app.models.meal_log import MealLog
from app.services.meal_plan_consumption_service import (
    active_consumption_dates,
    lock_user_meal_plans,
)


def invalidate_future_meal_plans(db: Session, user_id: UUID, timezone: str) -> None:
    """Retain consumed dates and their active weeks; invalidate other future plans."""
    lock_user_meal_plans(db, user_id)
    local_today = datetime.now(ZoneInfo(timezone)).date()
    protected_week = aliased(WeeklyMealPlan)
    week_has_consumption = active_consumption_dates(user_id).where(
        MealLog.log_date.between(protected_week.start_date, protected_week.end_date),
    ).correlate(protected_week).exists()
    belongs_to_protected_week = select(protected_week.id).where(
        protected_week.user_id == user_id,
        protected_week.status == WeeklyMealPlanStatus.GENERATED.value,
        week_has_consumption,
        or_(
            MealPlan.weekly_plan_id == protected_week.id,
            MealPlan.plan_date.between(protected_week.start_date, protected_week.end_date),
        ),
    ).exists()
    future_plan_filters = (
        MealPlan.user_id == user_id,
        MealPlan.status == MealPlanStatus.GENERATED.value,
        MealPlan.plan_date >= local_today,
        MealPlan.plan_date.not_in(active_consumption_dates(user_id)),
        ~belongs_to_protected_week,
    )
    affected_week = (
        select(MealPlan.id)
        .where(
            *future_plan_filters,
            or_(
                MealPlan.weekly_plan_id == WeeklyMealPlan.id,
                MealPlan.plan_date.between(WeeklyMealPlan.start_date, WeeklyMealPlan.end_date),
            ),
        )
        .exists()
    )

    # Find affected weeks before changing the generated status of their daily plans.
    db.query(WeeklyMealPlan).filter(
        WeeklyMealPlan.user_id == user_id,
        WeeklyMealPlan.status == WeeklyMealPlanStatus.GENERATED.value,
        affected_week,
    ).update({WeeklyMealPlan.status: WeeklyMealPlanStatus.ARCHIVED.value}, synchronize_session="fetch")

    db.query(MealPlan).filter(*future_plan_filters).update(
        {MealPlan.status: MealPlanStatus.ARCHIVED.value}, synchronize_session="fetch"
    )
