from dataclasses import dataclass

from app.core.enums import Goal
from app.nutrition.constants import (
    CARBS_KCAL_PER_G,
    FAT_G_PER_KG,
    FAT_KCAL_PER_G,
    PROTEIN_G_PER_KG_BY_GOAL,
    PROTEIN_KCAL_PER_G,
)
from app.nutrition.errors import NutritionCalculationError


@dataclass(frozen=True)
class MacroTargets:
    protein_g: float
    carbs_g: float
    fat_g: float


def _coerce_goal(goal: Goal | str) -> Goal:
    try:
        return Goal(goal)
    except ValueError as exc:
        raise NutritionCalculationError(f"Unsupported goal: {goal}") from exc


def _validate_weight(weight_kg: float) -> None:
    if weight_kg <= 0:
        raise NutritionCalculationError("weight_kg must be greater than 0")


def calculate_protein_g(weight_kg: float, goal: Goal | str) -> float:
    _validate_weight(weight_kg)
    goal_value = _coerce_goal(goal)
    return weight_kg * PROTEIN_G_PER_KG_BY_GOAL[goal_value]


def calculate_fat_g(weight_kg: float) -> float:
    _validate_weight(weight_kg)
    return weight_kg * FAT_G_PER_KG


def calculate_macro_calories(macros: MacroTargets) -> float:
    return (
        (macros.protein_g * PROTEIN_KCAL_PER_G)
        + (macros.carbs_g * CARBS_KCAL_PER_G)
        + (macros.fat_g * FAT_KCAL_PER_G)
    )


def calculate_macros(target_calories: float, weight_kg: float, goal: Goal | str) -> MacroTargets:
    if target_calories <= 0:
        raise NutritionCalculationError("target_calories must be greater than 0")

    protein_g = calculate_protein_g(weight_kg=weight_kg, goal=goal)
    fat_g = calculate_fat_g(weight_kg=weight_kg)
    protein_calories = protein_g * PROTEIN_KCAL_PER_G
    fat_calories = fat_g * FAT_KCAL_PER_G
    remaining_calories = target_calories - protein_calories - fat_calories

    if remaining_calories < 0:
        raise NutritionCalculationError(
            "target calories are too low to support protein and fat minimums"
        )

    carbs_g = remaining_calories / CARBS_KCAL_PER_G
    if carbs_g < 0:
        raise NutritionCalculationError("carbs_g cannot be negative")

    return MacroTargets(
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
    )


def calculate_macros_with_fixed_protein_and_fat(
    target_calories: float,
    protein_g: float,
    fat_g: float,
) -> MacroTargets:
    if target_calories <= 0:
        raise NutritionCalculationError("target_calories must be greater than 0")
    if protein_g <= 0:
        raise NutritionCalculationError("protein_g must be greater than 0")
    if fat_g <= 0:
        raise NutritionCalculationError("fat_g must be greater than 0")

    remaining_calories = (
        target_calories
        - (protein_g * PROTEIN_KCAL_PER_G)
        - (fat_g * FAT_KCAL_PER_G)
    )
    if remaining_calories < 0:
        raise NutritionCalculationError(
            "target calories are too low to preserve protein and fat targets"
        )

    carbs_g = remaining_calories / CARBS_KCAL_PER_G
    return MacroTargets(protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)
