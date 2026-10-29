from datetime import date, datetime, timezone

from sqlalchemy import select, union
from sqlalchemy.orm import selectinload

from app.core.exceptions import APIErrorException
from app.models.extra_food_log import ExtraFoodLog
from app.models.habit import Habit, HabitCompletion
from app.models.meal_log import MealLog
from app.models.meal_plan import MealPlan
from app.models.step_log import StepLog
from app.models.weight_log import WeightLog
from app.models.user_profile import UserProfile
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.insights import TARGET_FIELDS, NutritionInsightDay, build_nutrition_summary
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.nutrition.targets import calculate_nutrition_targets
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
    recorded_days = []
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
    return {"start_date": start_date, "end_date": end_date, "logged_nutrition_days": len(recorded_dates), "items": items,
            "nutrition_summary": nutrition_summary_for_history(db, user, start_date, end_date, recorded_days)}


def nutrition_summary_for_history(db, user, start_date, end_date, recorded_days):
    days_in_range = (end_date - start_date).days + 1
    if not recorded_days:
        return build_nutrition_summary([], days_in_range)
    plans = db.query(MealPlan).options(selectinload(MealPlan.items)).filter(
        MealPlan.user_id == user.id, MealPlan.status == "generated",
        MealPlan.plan_date.between(start_date, end_date),
    ).all()
    plans_by_date = {plan.plan_date: plan for plan in plans}
    logs = db.query(MealLog).options(selectinload(MealLog.nutrients)).filter(
        MealLog.user_id == user.id, MealLog.status == "active",
        MealLog.log_date.between(start_date, end_date),
    ).all()
    snacks = db.query(ExtraFoodLog).options(selectinload(ExtraFoodLog.nutrients)).filter(
        ExtraFoodLog.user_id == user.id, ExtraFoodLog.log_date.between(start_date, end_date),
    ).all()
    entries_by_date = {}
    logged_items_by_plan = {}
    for log in logs:
        entries_by_date.setdefault(log.log_date, []).append(log)
        logged_items_by_plan.setdefault(log.meal_plan_id, set()).add(log.meal_plan_item_id)
    for snack in snacks:
        entries_by_date.setdefault(snack.log_date, []).append(snack)

    profile = db.query(UserProfile).filter_by(user_id=user.id).one_or_none()
    profile_targets = None
    if profile is not None:
        try:
            targets = calculate_nutrition_targets(
                age=profile.age, sex=profile.sex, height_cm=profile.height_cm,
                weight_kg=profile.weight_kg, activity_level=profile.activity_level,
                goal=profile.goal, target_rate=profile.target_rate,
            )
            profile_targets = {"calories": targets.target_calories, "protein_g": targets.macros.protein_g,
                               "carbs_g": targets.macros.carbs_g, "fat_g": targets.macros.fat_g}
        except NutritionCalculationError:
            pass

    def known_codes(entry):
        return {row.nutrient_code for row in entry.nutrients
                if row.nutrient_code in RECIPE_NUTRIENT_DEFINITION_BY_CODE
                and row.unit == RECIPE_NUTRIENT_DEFINITION_BY_CODE[row.nutrient_code].unit}

    days = []
    for actual in recorded_days:
        log_date = actual["date"]
        entries = entries_by_date.get(log_date, [])
        # A concurrent reset can remove intake after the history query.
        if not entries:
            continue
        plan = plans_by_date.get(log_date)
        targets = {"calories": plan.calorie_target, "protein_g": plan.protein_target,
                   "carbs_g": plan.carbohydrate_target, "fat_g": plan.fat_target} if plan else profile_targets
        code_sets = [known_codes(entry) for entry in entries]
        days.append(NutritionInsightDay(
            actual={field: actual[field] for field in TARGET_FIELDS}, targets=targets,
            planned_meals=len(plan.items) if plan else 0,
            logged_meals=len(logged_items_by_plan.get(plan.id, set()) & {item.id for item in plan.items}) if plan else 0,
            # Snacks store scoring inputs explicitly; meal logs need compatible macro snapshots.
            macro_data_complete=all(isinstance(entry, ExtraFoodLog)
                                    or {"calories", "protein", "carbohydrates", "fat"} <= codes
                                    for entry, codes in zip(entries, code_sets)),
            target_source="saved_plan" if plan else "current_profile" if profile_targets else None,
        ))
    return build_nutrition_summary(days, days_in_range)
