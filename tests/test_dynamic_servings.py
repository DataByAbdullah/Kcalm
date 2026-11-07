import pytest

from app.meal_planning.solver import (
    DailyPlanSolverInput, MAX_SERVING_AMOUNT, MealSlot, SERVING_AMOUNTS,
    SolverNutritionTargets, SolverStatus, build_candidate_options, solve_daily_plan,
)
from tests.test_meal_solver import candidate, nutrient_amounts


def test_dynamic_options_include_base_quarters_and_are_bounded_by_calorie_budget():
    recipe = candidate("Portion", ["dinner"], nutrient_amounts(calories=400))
    options, malformed = build_candidate_options([recipe], [MealSlot("dinner")],
                                                ("calories", "protein", "carbohydrates", "fat"), 1400)
    amounts = [option.serving_amount for option in options]
    assert not malformed
    assert set(SERVING_AMOUNTS) <= set(amounts)
    assert amounts == [step / 4 for step in range(3, 17)]  # 1540 / 400 rounds up to 4.0.
    assert max(amounts) < MAX_SERVING_AMOUNT


@pytest.mark.parametrize("calories", [0, 1e-12, float("inf"), float("nan")])
def test_zero_tiny_or_malformed_calories_do_not_create_unbounded_options(calories):
    recipe = candidate("Malformed energy", ["dinner"], nutrient_amounts(calories=calories))
    options, _ = build_candidate_options([recipe], [MealSlot("dinner")],
                                         ("calories", "protein", "carbohydrates", "fat"), 3719)
    assert len(options) <= int((MAX_SERVING_AMOUNT - 0.75) / 0.25) + 1
    assert all(0.75 <= option.serving_amount <= MAX_SERVING_AMOUNT for option in options)
    result = solve_daily_plan(DailyPlanSolverInput(
        [recipe], SolverNutritionTargets(3719, 200, 400, 100, []), [MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.INFEASIBLE


def test_larger_meal_can_compensate_when_another_cannot_supply_equal_share():
    recipes = [
        candidate("Small breakfast", ["breakfast"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5)),
        candidate("Large dinner", ["dinner"], nutrient_amounts(calories=1000, protein=100, carbohydrates=100, fat=50)),
    ]
    result = solve_daily_plan(DailyPlanSolverInput(
        recipes, SolverNutritionTargets(4000, 400, 400, 200, []), [MealSlot("breakfast"), MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert result.daily_totals["calories"] == 4000
    assert result.meals[1].serving_amount > 2
    assert len({meal.recipe_id for meal in result.meals}) == 2


def test_truly_impossible_target_retains_calorie_guard():
    recipes = [candidate(name, [name], nutrient_amounts(calories=400)) for name in ("breakfast", "dinner")]
    result = solve_daily_plan(DailyPlanSolverInput(
        recipes, SolverNutritionTargets(100_000, 200, 400, 100, []), [MealSlot("breakfast"), MealSlot("dinner")],
    ))
    assert result.status == SolverStatus.INFEASIBLE
    assert result.infeasibility_reasons == ["calorie_target_outside_allowed_tolerance"]
    assert result.meals == []


def test_swap_options_use_remaining_calories_after_locked_meals():
    recipe = candidate("Replacement", ["dinner"], nutrient_amounts(calories=400, protein=30, carbohydrates=50, fat=10))
    options, _ = build_candidate_options([recipe], [MealSlot("dinner")],
                                         ("calories", "protein", "carbohydrates", "fat"), 3719, 2819)
    assert max(option.serving_amount for option in options) == 3.25
    result = solve_daily_plan(DailyPlanSolverInput(
        [recipe], SolverNutritionTargets(3719, 167.5, 312.5, 92.5, []), [MealSlot("dinner")],
        locked_nutrition={"calories": 2819, "protein": 100, "carbohydrates": 200, "fat": 70},
    ))
    assert result.status == SolverStatus.OPTIMAL
    assert result.meals[0].serving_amount == 2.25
    assert result.daily_totals["calories"] == 3719
