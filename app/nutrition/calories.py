from app.core.enums import Goal
from app.nutrition.constants import (
    CALORIE_ADJUSTMENT_KCAL_PER_TARGET_RATE,
    DEFAULT_TARGET_RATE_BY_GOAL,
    MAX_DAILY_CALORIE_ADJUSTMENT_BY_GOAL,
    MAX_TARGET_RATE,
)
from app.nutrition.errors import NutritionCalculationError


def _coerce_goal(goal: Goal | str) -> Goal:
    try:
        return Goal(goal)
    except ValueError as exc:
        raise NutritionCalculationError(f"Unsupported goal: {goal}") from exc


def _validate_tdee(tdee: float) -> None:
    if tdee <= 0:
        raise NutritionCalculationError("tdee must be greater than 0")


def _validate_target_rate(target_rate: float | None) -> None:
    if target_rate is None:
        return
    if target_rate <= 0:
        raise NutritionCalculationError("target_rate must be greater than 0")
    if target_rate > MAX_TARGET_RATE:
        raise NutritionCalculationError(f"target_rate must be less than or equal to {MAX_TARGET_RATE}")


def get_effective_target_rate(goal: Goal | str, target_rate: float | None = None) -> float:
    goal_value = _coerce_goal(goal)
    _validate_target_rate(target_rate)

    if goal_value in {Goal.MAINTENANCE, Goal.RECOMPOSITION}:
        return 0.0
    if target_rate is not None:
        return target_rate
    return DEFAULT_TARGET_RATE_BY_GOAL[goal_value]


def calculate_goal_calorie_adjustment(
    tdee: float,
    goal: Goal | str,
    target_rate: float | None = None,
) -> float:
    _validate_tdee(tdee)
    goal_value = _coerce_goal(goal)
    effective_rate = get_effective_target_rate(goal=goal_value, target_rate=target_rate)

    if goal_value in {Goal.MAINTENANCE, Goal.RECOMPOSITION}:
        return 0.0

    max_adjustment = MAX_DAILY_CALORIE_ADJUSTMENT_BY_GOAL[goal_value]
    adjustment = min(effective_rate * CALORIE_ADJUSTMENT_KCAL_PER_TARGET_RATE, max_adjustment)

    if goal_value == Goal.FAT_LOSS:
        return -adjustment
    if goal_value == Goal.MUSCLE_GAIN:
        return adjustment

    raise NutritionCalculationError(f"Unsupported goal: {goal}")


def calculate_target_calories(
    tdee: float,
    goal: Goal | str,
    target_rate: float | None = None,
) -> float:
    adjustment = calculate_goal_calorie_adjustment(
        tdee=tdee,
        goal=goal,
        target_rate=target_rate,
    )
    target_calories = tdee + adjustment

    if target_calories <= 0:
        raise NutritionCalculationError("target calories must be greater than 0")

    return target_calories

