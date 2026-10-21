from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email
from app.models.extra_food_log import ExtraFoodLog


def test_insights_use_real_data_and_do_not_invent_missing_intake(tracking_user, auth_db):
    db, token = tracking_user
    path = "/insights?start_date=2026-01-01&end_date=2026-01-03"
    empty = request("GET", path, token).json()
    assert empty["logged_nutrition_days"] == 0
    user_id = request("GET", "/auth/me", token).json()["id"]
    from uuid import UUID
    from datetime import date
    db.add(ExtraFoodLog(user_id=UUID(user_id), log_date=date(2026, 1, 2), name="Test snack",
                        calories=300, protein_g=20, carbs_g=40, fat_g=5))
    db.commit()
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    request("PUT", "/weight-logs/2026-01-03", token, {"weight_kg": 79})
    request("PUT", "/steps/2026-01-02", token, {"steps": 8000})
    result = request("GET", path, token).json()
    assert result["logged_nutrition_days"] == 1
    facts = {item["code"]: item["values"] for item in result["items"]}
    assert facts["recorded_nutrition"]["average_calories"] == 300
    assert facts["recorded_weight_change"]["change_kg"] == -1
    assert facts["recorded_steps"]["average_steps"] == 8000
    _, track = auth_db
    other = register_and_login(track(unique_email("insight-other")))
    assert request("GET", path, other).json()["logged_nutrition_days"] == 0


def test_insight_validation_and_auth(tracking_user):
    _, token = tracking_user
    assert request("GET", "/insights").status_code == 401
    assert request("GET", "/insights?start_date=2026-02-01&end_date=2026-01-01", token).status_code == 422
    assert request("GET", "/insights?start_date=2020-01-01&end_date=2026-01-01", token).status_code == 422
