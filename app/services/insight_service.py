from datetime import date, datetime, timezone

from sqlalchemy import select, union

from app.core.exceptions import APIErrorException
from app.models.extra_food_log import ExtraFoodLog
from app.models.habit import Habit, HabitCompletion
from app.models.meal_log import MealLog
from app.models.step_log import StepLog
from app.models.weight_log import WeightLog
from app.services.meal_log_service import get_daily_intake_history
from app.services.tracking_common import validate_date_range, validate_record_date


def get_insights(db, user, start_date=None, end_date=None):
    end_date = end_date or datetime.now(timezone.utc).date()
    start_date = start_date or date.fromordinal(max(date.min.toordinal(), end_date.toordinal() - 29))
    validate_date_range(start_date, end_date)
    validate_record_date(end_date)
    if (end_date - start_date).days > 365:
        raise APIErrorException(422, "DATE_RANGE_TOO_LARGE", "Insights are limited to 366 days per request.")
    dates = union(
        select(MealLog.log_date).where(MealLog.user_id == user.id, MealLog.status == "active",
                                       MealLog.log_date.between(start_date, end_date)),
        select(ExtraFoodLog.log_date).where(ExtraFoodLog.user_id == user.id,
                                            ExtraFoodLog.log_date.between(start_date, end_date)))
    recorded_dates = set(db.execute(dates).scalars().all())
    items = []
    if recorded_dates:
        history = get_daily_intake_history(db, user, start_date, end_date)
        recorded_days = [row for row in history if row["date"] in recorded_dates]
        items.append({"code": "recorded_nutrition", "message": "Average intake on days with recorded meals or snacks; partial days may be included.",
                      "values": {"logged_days": len(recorded_days), "average_calories": round(sum(row["calories"] for row in recorded_days) / len(recorded_days), 2),
                                 "average_protein_g": round(sum(row["protein_g"] for row in recorded_days) / len(recorded_days), 2)}})
    else:
        items.append({"code": "nutrition_data_missing", "message": "No nutrition intake was recorded in this period.", "values": {"logged_days": 0}})
    steps = db.query(StepLog).filter(StepLog.user_id == user.id, StepLog.log_date.between(start_date, end_date)).all()
    if steps:
        items.append({"code": "recorded_steps", "message": "Steps reported through manual entries.",
                      "values": {"logged_days": len(steps), "total_steps": sum(row.steps for row in steps),
                                 "average_steps": round(sum(row.steps for row in steps) / len(steps), 2)}})
    weights = db.query(WeightLog).filter(WeightLog.user_id == user.id, WeightLog.log_date.between(start_date, end_date)).order_by(WeightLog.log_date).all()
    if len(weights) >= 2:
        items.append({"code": "recorded_weight_change", "message": "Difference between first and last recorded weight in this period.",
                      "values": {"entries": len(weights), "change_kg": round(weights[-1].weight_kg - weights[0].weight_kg, 3)}})
    completions = db.query(HabitCompletion).join(Habit).filter(Habit.user_id == user.id,
                    HabitCompletion.log_date.between(start_date, end_date)).count()
    if completions:
        items.append({"code": "recorded_habit_completions", "message": "Habit completions recorded in this period.",
                      "values": {"completions": completions}})
    return {"start_date": start_date, "end_date": end_date, "logged_nutrition_days": len(recorded_dates), "items": items}
