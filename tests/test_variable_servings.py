from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP

import pytest

from app.meal_planning.solver import (
    DailyPlanSolverInput,
    MealSlot,
    MAX_SERVING_AMOUNT,
    SolverNutritionTargets,
    SolverStatus,
    ToleranceStatus,
    objective_coefficient,
    solve_daily_plan,
)
from app.meal_planning.scaling import scale_amount
from tests.test_meal_solver import candidate, nutrient_amounts, targets


@pytest.mark.parametrize("servings", [0.75, 1.0, 1.25, 1.5, 1.75, 2.0])
def test_solver_selects_discrete_servings_and_scales_all_nutrition(servings):
    nutrition = nutrient_amounts(calories=400, protein=30, carbohydrates=50, fat=10,
                                 fiber=4, calcium=200, sodium=1.2345)
    recipe = candidate("Portion", ["dinner"], nutrition)
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[recipe],
        targets=targets(calories=400 * servings, protein=30 * servings,
                        carbohydrates=50 * servings, fat=10 * servings,
                        fiber=4 * servings, calcium=200 * servings),
        meal_slots=[MealSlot("dinner")],
    ))

    assert result.status == SolverStatus.OPTIMAL
    assert len(result.meals) == 1
    meal = result.meals[0]
    assert meal.serving_amount == servings
    for code, per_serving in nutrition.items():
        expected = (Decimal(str(per_serving)) * Decimal(str(servings))).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
        assert meal.nutrition[code] == float(expected)
        assert result.daily_totals[code] == meal.nutrition[code]
    assert result.within_preferred_tolerance is True
    assert isinstance(result.objective_value, int)


def test_high_calorie_day_uses_two_servings_instead_of_returning_under_target():
    meal_types = ["breakfast", "lunch", "pre_workout", "dinner"]
    recipes = [candidate(name, [name], nutrient_amounts(
        calories=464.875, protein=25, carbohydrates=40, fat=20,
    )) for name in meal_types]
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=recipes,
        targets=SolverNutritionTargets(3719, 200, 320, 160, []),
        meal_slots=[MealSlot(name) for name in meal_types],
    ))

    assert result.status == SolverStatus.OPTIMAL
    assert len(result.meals) == 4
    assert all(0.75 <= meal.serving_amount <= MAX_SERVING_AMOUNT for meal in result.meals)
    assert result.daily_totals["calories"] == 3719
    assert result.daily_totals["calories"] == sum(meal.nutrition["calories"] for meal in result.meals)


@pytest.mark.parametrize("calories", [100, 2000])
def test_severely_under_or_over_target_is_infeasible(calories):
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Outside range", ["dinner"], nutrient_amounts(calories=calories))],
        targets=targets(calories=1000),
        meal_slots=[MealSlot("dinner")],
    ))

    assert result.status == SolverStatus.INFEASIBLE
    assert result.infeasibility_reasons == ["calorie_target_outside_allowed_tolerance"]
    assert result.meals == []
    assert result.objective_value is None


@pytest.mark.parametrize("calories,target_calories,servings", [(100, 880, MAX_SERVING_AMOUNT), (1400, 960, 0.75)])
def test_calories_outside_five_percent_but_within_ten_percent_are_allowed(calories, target_calories, servings):
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Fallback", ["dinner"], nutrient_amounts(
            calories=calories, protein=30, carbohydrates=50, fat=10,
        ))],
        targets=targets(calories=target_calories, protein=30 * servings,
                        carbohydrates=50 * servings, fat=10 * servings),
        meal_slots=[MealSlot("dinner")],
    ))

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.meals[0].serving_amount == servings
    assert 0.9 * target_calories <= result.daily_totals["calories"] <= 1.1 * target_calories
    assert result.deviations[0].status != ToleranceStatus.WITHIN
    assert result.within_preferred_tolerance is False


@pytest.mark.parametrize("calories,expected_status", [(112.499, SolverStatus.INFEASIBLE), (112.5, SolverStatus.OPTIMAL)])
def test_calorie_lower_limit_is_inclusive(calories, expected_status):
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Boundary", ["dinner"], nutrient_amounts(calories=calories))],
        targets=targets(calories=1000, protein=20, carbohydrates=20, fat=10),
        meal_slots=[MealSlot("dinner")],
    ))
    assert result.status == expected_status
    if result.meals:
        assert result.daily_totals["calories"] == 900


def test_calorie_guard_keeps_macronutrient_objective_inside_allowed_band():
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Macro-heavy", ["dinner"], nutrient_amounts(
            calories=550, protein=100, carbohydrates=100, fat=100,
        ))],
        targets=targets(calories=1000, protein=100, carbohydrates=100, fat=100),
        meal_slots=[MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert 900 <= result.daily_totals["calories"] <= 1100
    assert result.meals[0].serving_amount in {1.75, 2.0}


def test_recipe_uniqueness_covers_all_variants_and_repeated_candidate_ids():
    flexible = candidate("Flexible", ["breakfast", "lunch"], nutrient_amounts(calories=400))
    lunch = candidate("Lunch", ["lunch"], nutrient_amounts(calories=400))
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[flexible, replace(flexible), lunch],
        targets=targets(calories=1400, protein=35, carbohydrates=35, fat=17.5),
        meal_slots=[MealSlot("breakfast"), MealSlot("lunch")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert len(result.meals) == 2
    assert {meal.recipe_id for meal in result.meals} == {flexible.recipe_id, lunch.recipe_id}
    assert all(meal.serving_amount * 4 == int(meal.serving_amount * 4) for meal in result.meals)


@pytest.mark.parametrize("first_calcium,upper_limit", [(100, None), (1000, 400)])
def test_scaled_micronutrient_shortfall_and_upper_excess_affect_selection(first_calcium, upper_limit):
    first = candidate("First", ["dinner"], nutrient_amounts(
        calories=400, protein=30, carbohydrates=50, fat=10, calcium=first_calcium,
    ))
    preferred = candidate("Preferred", ["dinner"], nutrient_amounts(
        calories=400, protein=30, carbohydrates=50, fat=10, calcium=200,
    ))
    nutrition_targets = targets(calories=600, protein=45, carbohydrates=75, fat=15, calcium=300)
    nutrition_targets = replace(nutrition_targets, micronutrients=[
        replace(target, upper_limit=upper_limit) if target.code == "calcium" else target
        for target in nutrition_targets.micronutrients
    ])
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[first, preferred], targets=nutrition_targets, meal_slots=[MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert result.meals[0].recipe_id == preferred.recipe_id
    assert result.meals[0].serving_amount == 1.5
    assert result.daily_totals["calcium"] == 300


def test_swap_solver_scales_replacement_against_locked_meal_nutrition():
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Replacement", ["dinner"], nutrient_amounts(
            calories=400, protein=30, carbohydrates=50, fat=10, fiber=4, calcium=200,
        ))],
        targets=targets(calories=1000, protein=65, carbohydrates=115, fat=25, fiber=10, calcium=500),
        meal_slots=[MealSlot("dinner")],
        locked_nutrition={"calories": 400, "protein": 20, "carbohydrates": 40,
                          "fat": 10, "fiber": 4, "calcium": 200},
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert result.meals[0].serving_amount == 1.5
    assert result.meals[0].nutrition["calories"] == 600
    assert result.daily_totals["calories"] == 1000


def test_five_percent_calorie_band_is_preferred_over_better_macro_match():
    macro_match = candidate("Macro match", ["dinner"], nutrient_amounts(
        calories=920, protein=100, carbohydrates=100, fat=100,
    ))
    preferred = candidate("Preferred calories", ["dinner"], nutrient_amounts(
        calories=1000, protein=95, carbohydrates=95, fat=95,
    ))
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[macro_match, preferred], targets=SolverNutritionTargets(1000, 100, 100, 100, []),
        meal_slots=[MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert result.meals[0].recipe_id == preferred.recipe_id
    assert result.daily_totals["calories"] == 1000


def test_large_objective_is_reported_as_an_exact_integer():
    nutrition_targets = targets(calories=400, protein=30, carbohydrates=50, fat=10, calcium=1)
    nutrition_targets = replace(nutrition_targets, micronutrients=[
        replace(target, upper_limit=1) for target in nutrition_targets.micronutrients if target.code == "calcium"
    ])
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Large excess", ["dinner"], nutrient_amounts(
            calories=400, protein=30, carbohydrates=50, fat=10, calcium=100_000_000,
        ))],
        targets=nutrition_targets, meal_slots=[MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    expected = (scale_amount(100_000_000) - scale_amount(1)) * objective_coefficient(500, 1) + 2
    assert expected > 2**53
    assert result.objective_value == expected
