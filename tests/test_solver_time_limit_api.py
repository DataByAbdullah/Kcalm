import pytest
from ortools.sat.python import cp_model

from app.models.meal_plan import MealPlan, WeeklyMealPlan
from app.models.user import User
from tests.test_meal_plan_persistence import (
    create_profile, meal_plan_db, register_and_login, unique_email,
)
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


@pytest.fixture
def timeout_user(meal_plan_db, seeded_schedule_catalog):
    db, track_email, _ = meal_plan_db
    email = track_email(unique_email("solver-timeout"))
    token = register_and_login(email)
    create_profile(token, equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    user_id = db.query(User.id).filter_by(email=email).scalar()
    return db, token, user_id


def assert_timeout(response):
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "MEAL_SOLVER_TIME_LIMIT_EXCEEDED"
    assert response.json()["error"]["details"] == {"reason": "solver_time_limit_exceeded"}


def test_timeout_preview_is_unknown_and_daily_creation_persists_nothing(timeout_user, monkeypatch):
    db, token, user_id = timeout_user
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda *args, **kwargs: cp_model.UNKNOWN)
    preview = request("POST", "/meal-plans/solve/preview", token, {})
    assert preview.status_code == 200
    assert preview.json()["status"] == "unknown"
    assert preview.json()["infeasibility_reasons"] == ["solver_time_limit_exceeded"]
    assert preview.json()["meals"] == []
    assert_timeout(request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"}))
    assert db.query(MealPlan).filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize("operation", ["swap", "adaptive"])
def test_timeout_does_not_mutate_a_swap_or_save_an_adaptive_plan(timeout_user, monkeypatch, operation):
    db, token, user_id = timeout_user
    created = request("POST", "/meal-plans", token, {"plan_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    plan = created.json()
    plan_id = plan["meal_plan_id"]
    if operation == "adaptive":
        for meal in plan["meals"]:
            logged = request("POST", f"/meal-plans/{plan_id}/items/{meal['id']}/log", token,
                             {"type": "ate_as_planned"})
            assert logged.status_code == 200, logged.text
    before = request("GET", f"/meal-plans/{plan_id}", token).json()
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda *args, **kwargs: cp_model.UNKNOWN)
    endpoint = (f"/meal-plans/{plan_id}/items/{plan['meals'][0]['id']}/swap" if operation == "swap"
                else f"/meal-plans/{plan_id}/generate-next-day")

    assert_timeout(request("POST", endpoint, token, {}))

    assert request("GET", f"/meal-plans/{plan_id}", token).json() == before
    assert db.query(MealPlan).filter_by(user_id=user_id).count() == 1


def test_weekly_timeout_rolls_back_previously_generated_children(timeout_user, monkeypatch):
    db, token, user_id = timeout_user
    solve = cp_model.CpSolver.Solve
    first_day_finished = False

    def timeout_after_first_day(self, model, *args, **kwargs):
        nonlocal first_day_finished
        if first_day_finished:
            return cp_model.UNKNOWN
        status = solve(self, model, *args, **kwargs)
        if model.HasObjective():
            first_day_finished = True
        return status

    monkeypatch.setattr(cp_model.CpSolver, "Solve", timeout_after_first_day)
    assert_timeout(request("POST", "/weekly-meal-plans", token, {"start_date": "2026-11-02"}))
    assert first_day_finished
    assert db.query(MealPlan).filter_by(user_id=user_id).count() == 0
    assert db.query(WeeklyMealPlan).filter_by(user_id=user_id).count() == 0
