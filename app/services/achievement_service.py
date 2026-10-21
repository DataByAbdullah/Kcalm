from sqlalchemy import func, select, union

from app.models.extra_food_log import ExtraFoodLog
from app.models.habit import Habit, HabitCompletion
from app.models.meal_log import MealLog
from app.models.recipe_execution import RecipeExecutionSession
from app.models.step_log import StepLog
from app.models.weight_log import WeightLog
from app.schemas.progress import AchievementResponse


def get_achievements(db, user):
    weights = db.query(WeightLog).filter_by(user_id=user.id).count()
    maximum_steps = db.query(func.max(StepLog.steps)).filter_by(user_id=user.id).scalar() or 0
    completions = db.query(HabitCompletion).join(Habit).filter(Habit.user_id == user.id).count()
    dates = union(select(MealLog.log_date).where(MealLog.user_id == user.id, MealLog.status == "active"),
                  select(ExtraFoodLog.log_date).where(ExtraFoodLog.user_id == user.id)).subquery()
    logged_days = db.query(func.count()).select_from(dates).scalar()
    cooked = db.query(RecipeExecutionSession).filter_by(user_id=user.id, status="completed").count()
    definitions = [
        ("first_weight", "First weight entry", weights, 1, "entries"),
        ("weight_checkins_7", "Seven weight check-ins", weights, 7, "entries"),
        ("steps_10000", "10,000 steps in a day", maximum_steps, 10000, "steps"),
        ("habit_completions_7", "Seven habit completions", completions, 7, "completions"),
        ("nutrition_days_7", "Seven days of nutrition logging", logged_days, 7, "days"),
        ("first_recipe_completed", "First completed recipe session", cooked, 1, "sessions"),
    ]
    return [AchievementResponse(code=code, name=name, current=current, target=target, unit=unit,
                                unlocked=current >= target) for code, name, current, target, unit in definitions]
