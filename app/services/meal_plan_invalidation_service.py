from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.enums import MealPlanStatus, WeeklyMealPlanStatus
from app.models.meal_plan import MealPlan, WeeklyMealPlan


def invalidate_future_meal_plans(db: Session, user_id: UUID, timezone: str) -> None:
    """Archive obsolete plans in the caller's transaction, retaining all snapshots."""
    local_today = datetime.now(ZoneInfo(timezone)).date()
    future_plan_filters = (
        MealPlan.user_id == user_id,
        MealPlan.status == MealPlanStatus.GENERATED.value,
        MealPlan.plan_date >= local_today,
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
