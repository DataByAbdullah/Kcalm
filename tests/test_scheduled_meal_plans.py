from datetime import time
from uuid import UUID

import pytest

from app.models.meal_plan import MealPlan, MealPlanItem
from app.meal_planning.solver import MAX_SERVING_AMOUNT, SolverNutritionTargets
from app.services.recipe_seed_service import seed_development_recipes
from tests.test_auth import auth_db
from tests.test_meal_plan_persistence import create_profile, register_and_login, unique_email
from tests.test_weight_logs import request


@pytest.fixture(scope="module")
def seeded_schedule_catalog():
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        seed_development_recipes(db)


@pytest.fixture
def plan_user(auth_db, seeded_schedule_catalog):
    db, track = auth_db
    token = register_and_login(track(unique_email("scheduled-plan")))
    create_profile(token, meals_per_day=4, usual_wake_time="11:00", usual_sleep_time="03:00",
                   timezone="Asia/Karachi", equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    return db, token


def assert_portions_and_calorie_tolerance(plan):
    assert all(0.75 <= meal["servings"] <= MAX_SERVING_AMOUNT and meal["servings"] * 4 == int(meal["servings"] * 4)
               for meal in plan["meals"])
    assert 0.9 * plan["targets"]["calories"] <= plan["daily_totals"]["calories"] <= 1.1 * plan["targets"]["calories"]
    for code, amount in plan["daily_totals"].items():
        assert amount == pytest.approx(sum(meal["nutrition"].get(code, 0) for meal in plan["meals"]))


@pytest.mark.parametrize("count,types,times", [
    (2, ["breakfast", "dinner"], ["12:00:00", "01:00:00"]),
    (3, ["breakfast", "lunch", "dinner"], ["12:00:00", "18:30:00", "01:00:00"]),
    (4, ["breakfast", "lunch", "pre_workout", "dinner"], ["12:00:00", "16:20:00", "20:40:00", "01:00:00"]),
    (5, ["breakfast", "lunch", "snack", "pre_workout", "dinner"],
     ["12:00:00", "15:15:00", "18:30:00", "21:45:00", "01:00:00"]),
])
def test_automatic_plan_slots_and_schedule_persist_and_round_trip(plan_user, count, types, times):
    db, token = plan_user
    assert request("PATCH", "/users/profile", token, {"meals_per_day": count}).status_code == 200
    preview = request("POST", "/meal-plans/solve/preview", token, {})
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] in {"optimal", "feasible"}
    assert [meal["meal_type"] for meal in preview.json()["meals"]] == types
    assert [meal["scheduled_time"] for meal in preview.json()["meals"]] == times
    created = request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    plan = created.json()
    assert_portions_and_calorie_tolerance(plan)
    assert [meal["meal_type"] for meal in plan["meals"]] == types
    assert [meal["scheduled_time"] for meal in plan["meals"]] == times
    for meal, expected_time in zip(plan["meals"], times, strict=True):
        assert db.get(MealPlanItem, UUID(meal["id"])).scheduled_time == time.fromisoformat(expected_time)
    fetched = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token)
    assert fetched.status_code == 200
    assert fetched.json()["meals"] == plan["meals"]


def test_explicit_slots_override_profile_count_and_preserve_request_order(plan_user):
    _, token = plan_user
    body = {"plan_date": "2026-11-02", "meal_slots": [
        {"meal_type": "dinner", "required": True}, {"meal_type": "breakfast", "required": True},
    ]}
    for endpoint, expected_status in (("/meal-plans/solve/preview", 200), ("/meal-plans", 201)):
        response = request("POST", endpoint, token, body)
        assert response.status_code == expected_status, response.text
        assert [meal["meal_type"] for meal in response.json()["meals"]] == ["dinner", "breakfast"]
        assert [meal["scheduled_time"] for meal in response.json()["meals"]] == ["12:00:00", "01:00:00"]


def test_existing_plan_schedule_is_a_snapshot_and_swap_retains_time(plan_user):
    db, token = plan_user
    created = request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    plan = created.json()
    original_times = [meal["scheduled_time"] for meal in plan["meals"]]
    assert request("PATCH", "/users/profile", token, {
        "usual_wake_time": "08:00", "usual_sleep_time": "22:00", "timezone": "Europe/London",
    }).status_code == 200
    path = f"/meal-plans/{plan['meal_plan_id']}"
    assert [meal["scheduled_time"] for meal in request("GET", path, token).json()["meals"]] == original_times
    item = plan["meals"][2]
    swapped = request("POST", f"{path}/items/{item['id']}/swap", token, {})
    assert swapped.status_code == 200, swapped.text
    assert [meal["scheduled_time"] for meal in swapped.json()["meals"]] == original_times
    db.expire_all()
    assert db.get(MealPlanItem, UUID(item["id"])).scheduled_time == time(20, 40)
    newer = request("POST", "/meal-plans", token, {"plan_date": "2026-11-03"})
    assert newer.status_code == 201, newer.text
    assert newer.json()["meals"][0]["scheduled_time"] == "09:00:00"
    assert newer.json()["meals"][-1]["scheduled_time"] == "20:00:00"


@pytest.mark.parametrize("required_types,expected_times", [
    (["dinner"], ["12:00:00"]),
    (["lunch", "dinner"], ["12:00:00", "01:00:00"]),
])
def test_omitted_optional_slots_do_not_delay_first_actual_meal(plan_user, required_types, expected_times, monkeypatch):
    from app.models.recipe import Recipe
    from app.services import meal_solver_service

    # Keep the single-meal scheduling case nutritionally attainable as well.
    monkeypatch.setattr(meal_solver_service, "build_solver_targets_from_profile",
                        lambda profile: SolverNutritionTargets(800, 60, 80, 25, []))

    db, token = plan_user
    snack_ids = [str(recipe.id) for recipe in db.query(Recipe).all()
                 if any(link.tag.name == "snack" for link in recipe.tag_links)]
    body = {"plan_date": "2026-11-02", "excluded_recipe_ids": snack_ids, "meal_slots": [
        {"meal_type": "snack", "required": False},
        *[{"meal_type": meal_type, "required": True} for meal_type in required_types],
    ]}
    for endpoint, expected_status in (("/meal-plans/solve/preview", 200), ("/meal-plans", 201)):
        response = request("POST", endpoint, token, body)
        assert response.status_code == expected_status, response.text
        assert [meal["meal_type"] for meal in response.json()["meals"]] == required_types
        assert [meal["scheduled_time"] for meal in response.json()["meals"]] == expected_times


def test_legacy_plan_item_can_return_null_schedule(plan_user):
    db, token = plan_user
    created = request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    meal = created.json()["meals"][0]
    db.get(MealPlanItem, UUID(meal["id"])).scheduled_time = None
    db.commit()
    detail = request("GET", f"/meal-plans/{created.json()['meal_plan_id']}", token)
    assert detail.status_code == 200
    assert detail.json()["meals"][0]["scheduled_time"] is None


def test_weekly_children_use_profile_slots_and_schedule(plan_user):
    db, token = plan_user
    response = request("POST", "/weekly-meal-plans", token, {"start_date": "2026-11-02"})
    assert response.status_code == 201, response.text
    week = response.json()
    assert len(week["daily_plans"]) == 7
    for day in week["daily_plans"]:
        assert_portions_and_calorie_tolerance(day)
        assert [meal["meal_type"] for meal in day["meals"]] == ["breakfast", "lunch", "pre_workout", "dinner"]
        assert [meal["scheduled_time"] for meal in day["meals"]] == ["12:00:00", "16:20:00", "20:40:00", "01:00:00"]
        stored = db.get(MealPlan, UUID(day["meal_plan_id"]))
        assert str(stored.weekly_plan_id) == week["weekly_plan_id"]
        assert all(item.scheduled_time is not None for item in stored.items)
        fetched = request("GET", f"/meal-plans/{day['meal_plan_id']}", token)
        assert fetched.status_code == 200
        assert fetched.json()["meals"] == day["meals"]
