from datetime import date
from uuid import UUID

from app.core.database import Base
from app.models.extra_food_log import ExtraFoodLog
from sqlalchemy import select, func
from tests.test_auth import auth_db, login_user
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import create_profile, register_and_login, setup_seed_data, unique_email


def test_delete_cascades_owned_data_and_invalidates_tokens(tracking_user, auth_db):
    db, token = tracking_user
    user_id = UUID(request("GET", "/auth/me", token).json()["id"])
    email = request("GET", "/auth/me", token).json()["email"]
    refresh = login_user(email).json()["refresh_token"]
    create_profile(token)
    setup_seed_data(db)
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    request("PUT", "/steps/2026-01-01", token, {"steps": 1000})
    habit = request("POST", "/habits", token, {"name": "Walk", "start_date": "2026-01-01"}).json()
    request("PUT", f"/habits/{habit['id']}/completions/2026-01-01", token, {"completed": True})
    request("POST", "/notifications/sync", token)
    db.add(ExtraFoodLog(user_id=user_id, log_date=date(2026, 1, 1), name="Snack", calories=100, protein_g=5, carbs_g=10, fat_g=4))
    db.commit()
    week = request("POST", "/weekly-meal-plans", token, {"start_date": "2026-01-05", "max_total_time_minutes": 60})
    assert week.status_code == 201, week.text
    week_id = week.json()["weekly_plan_id"]
    assert request("POST", f"/weekly-meal-plans/{week_id}/grocery-list", token).status_code == 201
    plan = week.json()["daily_plans"][0]
    item_id = plan["meals"][0]["id"]
    item_path = f"/meal-plans/{plan['meal_plan_id']}/items/{item_id}"
    assert request("POST", item_path + "/log", token, {"type": "ate_as_planned"}).status_code == 200
    execution = request("POST", item_path + "/execution-session", token)
    assert execution.status_code == 201
    execution_id = UUID(execution.json()["session_id"])
    export = request("GET", "/users/me/export", token)
    assert export.status_code == 200
    records = export.json()["records"]
    for table in ("meal_plans", "meal_plan_items", "meal_plan_item_nutrients", "meal_plan_item_ingredients",
                  "weekly_meal_plans", "grocery_list_items", "meal_log_nutrients", "recipe_execution_step_snapshots"):
        assert records[table], table
    _, track = auth_db
    other = register_and_login(track(unique_email("delete-other")))
    assert request("DELETE", "/users/me", token).status_code == 204
    assert request("GET", "/auth/me", token).status_code == 401
    assert request("POST", "/auth/refresh", body={"refresh_token": refresh}).status_code == 401
    assert request("GET", "/auth/me", other).status_code == 200
    for table in Base.metadata.tables.values():
        if "user_id" in table.c:
            assert db.scalar(select(func.count()).select_from(table).where(table.c.user_id == user_id)) == 0, table.name
    table = Base.metadata.tables["habit_completions"]
    assert db.scalar(select(func.count()).select_from(table).where(table.c.habit_id == UUID(habit["id"]))) == 0
    table = Base.metadata.tables["recipe_execution_step_snapshots"]
    assert db.scalar(select(func.count()).select_from(table).where(table.c.execution_session_id == execution_id)) == 0
    assert request("GET", "/recipes", other).json()["total"] > 0
    assert request("DELETE", "/users/me").status_code == 401
