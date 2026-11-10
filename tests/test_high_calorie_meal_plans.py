from datetime import time
from uuid import UUID

import pytest
from ortools.sat.python import cp_model

from app.meal_planning.solver import MAX_SERVING_AMOUNT
from app.models.meal_plan import MealPlanItem
from app.models.recipe import Recipe
from tests.test_meal_plan_persistence import create_profile, create_recipe, meal_plan_db, register_and_login, unique_email
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


@pytest.fixture
def high_calorie_user(meal_plan_db, seeded_schedule_catalog):
    db, track_email, track_recipe = meal_plan_db
    token = register_and_login(track_email(unique_email("high-calorie")))
    # 2220 kcal BMR * 1.9 activity - 499 kcal deficit = 3719 kcal.
    create_profile(token, age=30, height_cm=180, weight_kg=124, activity_level="extra_active",
                   goal="fat_loss", target_rate=0.499, usual_wake_time="11:00", usual_sleep_time="03:00",
                   equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    return db, token, track_recipe


@pytest.mark.parametrize("optimization_times_out", [False, True], ids=["optimized", "feasibility-fallback"])
@pytest.mark.parametrize("count,meal_types,times,without_blender", [
    (2, ["breakfast", "dinner"], ["12:00:00", "01:00:00"], False),
    (3, ["breakfast", "lunch", "dinner"], ["12:00:00", "18:30:00", "01:00:00"], False),
    (4, ["breakfast", "lunch", "pre_workout", "dinner"], ["12:00:00", "16:20:00", "20:40:00", "01:00:00"], False),
    (5, ["breakfast", "lunch", "snack", "pre_workout", "dinner"],
     ["12:00:00", "15:15:00", "18:30:00", "21:45:00", "01:00:00"], False),
    pytest.param(5, ["breakfast", "lunch", "snack", "pre_workout", "dinner"],
                 ["12:00:00", "15:15:00", "18:30:00", "21:45:00", "01:00:00"], True,
                 id="five-meals-without-blender"),
])
def test_real_seeded_catalog_generates_3719_kcal_with_profile_meal_count(
    high_calorie_user, count, meal_types, times, without_blender, record_property, monkeypatch, optimization_times_out,
):
    if optimization_times_out:
        solve = cp_model.CpSolver.Solve

        def solve_or_timeout(self, model, *args, **kwargs):
            return cp_model.UNKNOWN if model.HasObjective() else solve(self, model, *args, **kwargs)

        monkeypatch.setattr(cp_model.CpSolver, "Solve", solve_or_timeout)
    db, token, track_recipe = high_calorie_user
    changes = {"meals_per_day": count}
    if without_blender:
        changes["equipment"] = ["stovetop", "oven", "air_fryer", "microwave", "slow_cooker"]
    updated = request("PATCH", "/users/profile", token, changes)
    assert updated.status_code == 200, updated.text
    if without_blender:
        assert "blender" not in updated.json()["equipment"]
    created = request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    plan = created.json()
    if optimization_times_out:
        assert plan["solver_status"] == "feasible"
    assert plan["targets"]["calories"] == pytest.approx(3719)
    # A forced optimization timeout may use the hard-feasible incumbent. Keep
    # the original optimized cases' stricter preferred-band regression intact.
    tolerance = 0.10 if optimization_times_out else 0.05
    assert (1 - tolerance) * 3719 <= plan["daily_totals"]["calories"] <= (1 + tolerance) * 3719
    record_property("daily_calories", plan["daily_totals"]["calories"])
    assert [meal["meal_type"] for meal in plan["meals"]] == meal_types
    assert [meal["scheduled_time"] for meal in plan["meals"]] == times
    assert len({meal["recipe_id"] for meal in plan["meals"]}) == count
    if count == 5:
        assert plan["meals"][2]["recipe_id"] != plan["meals"][3]["recipe_id"]
    if count <= 3:
        assert any(meal["servings"] > 2 for meal in plan["meals"])
    for meal in plan["meals"]:
        assert 0.75 <= meal["servings"] <= MAX_SERVING_AMOUNT
        assert meal["servings"] * 4 == int(meal["servings"] * 4)
        stored = db.get(MealPlanItem, UUID(meal["id"]))
        assert stored.servings == meal["servings"]
        assert stored.scheduled_time == time.fromisoformat(meal["scheduled_time"])
        if without_blender:
            assert "blender" not in {item.equipment for item in db.get(Recipe, stored.recipe_id).equipment}
        expected_quantities = {}
        for ingredient in db.get(Recipe, stored.recipe_id).ingredients:
            expected_quantities[ingredient.food_id] = expected_quantities.get(ingredient.food_id, 0) + float(ingredient.quantity_grams) * stored.servings
        assert {item.food_id: item.quantity_grams for item in stored.ingredient_snapshots} == pytest.approx(expected_quantities)
    for code, total in plan["daily_totals"].items():
        assert total == pytest.approx(sum(meal["nutrition"].get(code, 0) for meal in plan["meals"]))
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan

    if count == 2:
        # Swap a large portion while retaining the other meal's locked snapshots.
        item = max(plan["meals"], key=lambda meal: meal["servings"])
        original_recipe = db.get(Recipe, UUID(item["recipe_id"]))
        replacement = create_recipe(db, token, track_recipe, {
            "name": f"High calorie replacement {original_recipe.id}", "servings": float(original_recipe.servings),
            "prep_time_minutes": 0, "cook_time_minutes": 0,
            "ingredients": [{"food_id": str(ingredient.food_id), "quantity_grams": float(ingredient.quantity_grams),
                             "position": ingredient.position} for ingredient in original_recipe.ingredients],
            "steps": [{"position": 1, "instruction": "Serve."}], "tags": [item["meal_type"]], "equipment": [],
        })
        swapped_response = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{item['id']}/swap", token,
                                   {"recipe_id": replacement["id"]})
        assert swapped_response.status_code == 200, swapped_response.text
        swapped_plan = swapped_response.json()
        swapped_item = next(meal for meal in swapped_plan["meals"] if meal["id"] == item["id"])
        assert swapped_item["servings"] > 2
        assert swapped_item["servings"] * 4 == int(swapped_item["servings"] * 4)
        assert swapped_item["scheduled_time"] == item["scheduled_time"]
        db.expire_all()
        assert db.get(MealPlanItem, UUID(item["id"])).servings == swapped_item["servings"]
        assert 0.9 * 3719 <= swapped_plan["daily_totals"]["calories"] <= 1.1 * 3719
        assert next(meal for meal in swapped_plan["meals"] if meal["id"] != item["id"]) == next(
            meal for meal in plan["meals"] if meal["id"] != item["id"]
        )
