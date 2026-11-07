from datetime import time
from uuid import UUID, uuid4

import pytest

from app.meal_planning.solver import MAX_SERVING_AMOUNT, SolverNutritionTargets
from app.models.meal_plan import MealPlan, MealPlanItem
from app.models.recipe import Recipe
from app.models.user import User
from app.services import meal_solver_service
from app.services.recipe_candidate_service import get_recipe_candidates
from tests.test_meal_plan_persistence import (
    create_profile, create_recipe, meal_plan_db, register_and_login, unique_email,
)
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


@pytest.fixture
def portion_user(meal_plan_db, seeded_schedule_catalog):
    db, track_email, track_recipe = meal_plan_db
    email = track_email(unique_email("variable-serving"))
    token = register_and_login(email)
    create_profile(token, meals_per_day=4, usual_wake_time="11:00", usual_sleep_time="03:00",
                   equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    user = db.query(User).filter_by(email=email).one()
    eligible = get_recipe_candidates(db, user, meal_type="dinner", require_complete_nutrition=True)
    recipe_candidate = eligible.candidates[0]
    return db, token, user, recipe_candidate, track_recipe


def set_portion_targets(monkeypatch, recipe_candidate, multiplier):
    nutrition = {nutrient.code: nutrient.amount for nutrient in recipe_candidate.per_serving_nutrition}
    target = SolverNutritionTargets(
        calories=nutrition["calories"] * multiplier,
        protein_g=nutrition["protein"] * multiplier,
        carbohydrates_g=nutrition["carbohydrates"] * multiplier,
        fat_g=nutrition["fat"] * multiplier,
        micronutrients=[],
    )
    monkeypatch.setattr(meal_solver_service, "build_solver_targets_from_profile", lambda profile: target)
    return target


def only_recipes(db, recipe_ids):
    return [str(recipe.id) for recipe in db.query(Recipe).filter(Recipe.active.is_(True)).all()
            if recipe.id not in recipe_ids]


def assert_portion_snapshot(db, meal, expected_servings):
    db.expire_all()
    stored = db.get(MealPlanItem, UUID(meal["id"]))
    assert stored.servings == expected_servings
    assert stored.scheduled_time == time(12)
    quantities = {}
    for ingredient in db.get(Recipe, stored.recipe_id).ingredients:
        quantities[ingredient.food_id] = quantities.get(ingredient.food_id, 0) + float(ingredient.quantity_grams) * expected_servings
    assert {item.food_id: item.quantity_grams for item in stored.ingredient_snapshots} == pytest.approx(quantities)
    assert {item.nutrient_code: item.amount for item in stored.nutrients} == meal["nutrition"]


@pytest.mark.parametrize("servings", [1.5, 2.0, 3.5, 6.75])
def test_preview_persistence_ingredients_totals_and_get_use_selected_servings(portion_user, monkeypatch, servings):
    db, token, _, recipe_candidate, _ = portion_user
    target = set_portion_targets(monkeypatch, recipe_candidate, servings)
    body = {"plan_date": "2026-11-02", "meal_slots": [{"meal_type": "dinner", "required": True}],
            "excluded_recipe_ids": only_recipes(db, {recipe_candidate.recipe_id})}
    preview = request("POST", "/meal-plans/solve/preview", token, body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["meals"][0]["serving_amount"] == servings
    created = request("POST", "/meal-plans", token, body)
    assert created.status_code == 201, created.text
    plan = created.json()
    meal = plan["meals"][0]
    assert meal["servings"] == servings
    assert meal["scheduled_time"] == "12:00:00"
    assert meal["nutrition"] == preview.json()["meals"][0]["nutrition"]
    assert plan["daily_totals"] == meal["nutrition"] == preview.json()["daily_totals"]
    assert plan["daily_totals"]["calories"] == pytest.approx(target.calories, abs=0.001)
    assert_portion_snapshot(db, meal, servings)
    fetched = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token)
    assert fetched.status_code == 200
    assert fetched.json() == plan


@pytest.mark.parametrize("target_multiplier", [0.25, MAX_SERVING_AMOUNT * 2])
def test_outside_calorie_tolerance_is_not_persisted(portion_user, monkeypatch, target_multiplier):
    db, token, user, recipe_candidate, _ = portion_user
    set_portion_targets(monkeypatch, recipe_candidate, target_multiplier)
    body = {"plan_date": "2026-11-02", "meal_slots": [{"meal_type": "dinner", "required": True}],
            "excluded_recipe_ids": only_recipes(db, {recipe_candidate.recipe_id})}
    preview = request("POST", "/meal-plans/solve/preview", token, body)
    assert preview.status_code == 200
    assert preview.json()["status"] == "infeasible"
    assert preview.json()["infeasibility_reasons"] == ["calorie_target_outside_allowed_tolerance"]

    response = request("POST", "/meal-plans", token, body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MEAL_PLAN_INFEASIBLE"
    assert response.json()["error"]["details"]["infeasibility_reasons"] == ["calorie_target_outside_allowed_tolerance"]
    assert db.query(MealPlan).filter_by(user_id=user.id).count() == 0


@pytest.mark.parametrize("servings", [1.5, 3.5])
def test_swap_preserves_schedule_and_uses_scaled_servings_nutrition_and_ingredients(portion_user, monkeypatch, servings):
    db, token, _, recipe_candidate, track_recipe = portion_user
    set_portion_targets(monkeypatch, recipe_candidate, servings)
    original_recipe = db.get(Recipe, recipe_candidate.recipe_id)
    replacement = create_recipe(db, token, track_recipe, {
        "name": f"Portion replacement {uuid4().hex}", "servings": float(original_recipe.servings),
        "prep_time_minutes": 0, "cook_time_minutes": 0,
        "ingredients": [{"food_id": str(item.food_id), "quantity_grams": float(item.quantity_grams),
                         "position": item.position} for item in original_recipe.ingredients],
        "steps": [{"position": 1, "instruction": "Serve."}], "tags": ["dinner"], "equipment": [],
    })
    created = request("POST", "/meal-plans", token, {
        "plan_date": "2026-11-02", "meal_slots": [{"meal_type": "dinner", "required": True}],
        "excluded_recipe_ids": only_recipes(db, {recipe_candidate.recipe_id}),
    })
    assert created.status_code == 201, created.text
    original = created.json()
    item = original["meals"][0]

    response = request("POST", f"/meal-plans/{original['meal_plan_id']}/items/{item['id']}/swap", token,
                       {"recipe_id": replacement["id"]})

    assert response.status_code == 200, response.text
    plan = response.json()
    swapped = plan["meals"][0]
    assert swapped["id"] == item["id"]
    assert swapped["recipe_id"] == replacement["id"]
    assert swapped["servings"] == servings
    assert swapped["scheduled_time"] == item["scheduled_time"]
    assert swapped["nutrition"] == item["nutrition"]
    assert plan["daily_totals"] == original["daily_totals"]
    assert_portion_snapshot(db, swapped, servings)
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan
