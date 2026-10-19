from dataclasses import dataclass

from app.core.enums import ActivityLevel, Goal, Sex
from app.nutrition.bmr import calculate_bmr
from app.nutrition.calories import calculate_target_calories
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.macros import MacroTargets, calculate_macros
from app.nutrition.tdee import calculate_tdee


@dataclass(frozen=True)
class NutritionTargets:
    bmr: float
    tdee: float
    target_calories: float
    macros: MacroTargets


def calculate_nutrition_targets(
    age: int,
    sex: Sex | str,
    height_cm: float,
    weight_kg: float,
    activity_level: ActivityLevel | str,
    goal: Goal | str,
    target_rate: float | None = None,
) -> NutritionTargets:
    try:
        bmr = calculate_bmr(
            age=age,
            sex=sex,
            height_cm=height_cm,
            weight_kg=weight_kg,
        )
        tdee = calculate_tdee(bmr=bmr, activity_level=activity_level)
        target_calories = calculate_target_calories(
            tdee=tdee,
            goal=goal,
            target_rate=target_rate,
        )
        macros = calculate_macros(
            target_calories=target_calories,
            weight_kg=weight_kg,
            goal=goal,
        )
    except ValueError as exc:
        raise NutritionCalculationError(str(exc)) from exc

    return NutritionTargets(
        bmr=bmr,
        tdee=tdee,
        target_calories=target_calories,
        macros=macros,
    )

