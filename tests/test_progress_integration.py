from datetime import date
from uuid import UUID

from app.models.extra_food_log import ExtraFoodLog
from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import create_profile, setup_seed_data


def test_progress_uses_intake_snapshots_and_completed_execution(tracking_user):
    db, token = tracking_user
    setup_seed_data(db)
    create_profile(token)
    plan_response = request("POST", "/meal-plans", token, {"plan_date": "2026-01-03", "max_total_time_minutes": 60})
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    meal = plan["meals"][0]
    item_path = f"/meal-plans/{plan['meal_plan_id']}/items/{meal['id']}"
    assert request("POST", item_path + "/log", token, {"type": "ate_as_planned"}).status_code == 200
    user_id = UUID(request("GET", "/auth/me", token).json()["id"])
    db.add(ExtraFoodLog(user_id=user_id, log_date=date(2026, 1, 3), name="Manual snack",
                        calories=300, protein_g=20, carbs_g=40, fat_g=5))
    db.commit()
    started = request("POST", item_path + "/execution-session", token)
    assert started.status_code == 201
    session_id = started.json()["session_id"]
    assert request("POST", f"/recipe-execution-sessions/{session_id}/complete", token).status_code == 200
    achievements = {item["code"]: item for item in request("GET", "/achievements", token).json()["items"]}
    assert achievements["nutrition_days_7"]["current"] == 1
    assert achievements["first_recipe_completed"]["current"] == 1
    insights = request("GET", "/insights?start_date=2026-01-01&end_date=2026-01-03", token).json()
    assert insights["logged_nutrition_days"] == 1
    nutrition = next(item for item in insights["items"] if item["code"] == "recorded_nutrition")
    assert nutrition["values"]["average_calories"] == round(meal["nutrition"]["calories"] + 300, 2)
