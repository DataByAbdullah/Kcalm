from uuid import UUID

import pytest

from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email
from app.models.extra_food_log import ExtraFoodLog
from app.models.food import Food
from app.models.meal_log import MealLogNutrientSnapshot
from app.models.meal_plan import MealPlan
from app.services import insight_service
from tests.test_meal_logs import create_user_plan, intake_history, log_item, meal_log_db


def test_insights_use_real_data_and_do_not_invent_missing_intake(tracking_user, auth_db):
    db, token = tracking_user
    path = "/insights?start_date=2026-01-01&end_date=2026-01-03"
    empty = request("GET", path, token).json()
    assert empty["logged_nutrition_days"] == 0
    assert empty["nutrition_summary"]["nutrition_score"] is None
    assert empty["nutrition_summary"]["unavailable_reason"] == "no_recorded_nutrition"
    user_id = request("GET", "/auth/me", token).json()["id"]
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
    assert result["nutrition_summary"]["unavailable_reason"] == "targets_unavailable"
    _, track = auth_db
    other = register_and_login(track(unique_email("insight-other")))
    assert request("GET", path, other).json()["logged_nutrition_days"] == 0
    assert request("GET", path, other).json()["nutrition_summary"]["nutrition_score"] is None


def test_insight_validation_and_auth(tracking_user):
    _, token = tracking_user
    assert request("GET", "/insights").status_code == 401
    assert request("GET", "/insights?start_date=2026-02-01&end_date=2026-01-01", token).status_code == 422
    assert request("GET", "/insights?start_date=2020-01-01&end_date=2026-01-01", token).status_code == 422


def test_nutrition_insights_use_saved_targets_and_penalize_partial_logging(meal_log_db):
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-10")
    meal = plan["meals"][0]
    assert log_item(token, plan["meal_plan_id"], meal["id"], {"type": "ate_as_planned"}).status_code == 200
    # Later profile edits must not rewrite the plan's original target evidence.
    assert request("PATCH", "/users/profile", token, {"weight_kg": 120}).status_code == 200
    response = request("GET", "/insights?start_date=2026-10-10&end_date=2026-10-12", token)
    assert response.status_code == 200, response.text
    summary = response.json()["nutrition_summary"]
    targets = plan["targets"]
    expected = max(0, 100 * (1 - abs(meal["nutrition"]["calories"] - targets["calories"]) / targets["calories"]))
    assert summary["calorie_adherence"]["score"] == round(expected / len(plan["meals"]) / 3, 2)
    assert summary["calorie_adherence"]["average_target_calories"] == round(targets["calories"], 2)
    assert summary["calorie_adherence"]["average_actual_calories"] == round(meal["nutrition"]["calories"], 2)
    assert summary["target_sources"] == ["saved_plan"]
    assert summary["data_completeness"]["logged_days"] == 1
    assert summary["data_completeness"]["days_in_range"] == 3
    assert summary["data_completeness"]["percentage"] == 33.33
    assert summary["data_completeness"]["meal_logging_percentage"] == round(100 / len(plan["meals"]), 2)
    for item in plan["meals"][1:]:
        assert log_item(token, plan["meal_plan_id"], item["id"], {"type": "ate_as_planned"}).status_code == 200
    single_day = request("GET", "/insights?start_date=2026-10-10&end_date=2026-10-10", token).json()["nutrition_summary"]
    expected = max(0, 100 * (1 - abs(plan["daily_totals"]["calories"] - targets["calories"]) / targets["calories"]))
    assert single_day["calorie_adherence"]["score"] == round(expected, 2)
    assert single_day["data_completeness"]["meal_logging_percentage"] == 100
    assert single_day["nutrition_score"] is not None


def test_unplanned_nutrition_exposes_calculated_targets_but_not_fake_completeness(meal_log_db):
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-11")
    food = db.query(Food).filter_by(source_food_id="dev_banana").one()
    snack = request("POST", "/nutrition/snacks", token,
                    {"log_date": "2026-10-12", "food_id": str(food.id), "quantity_grams": 100})
    assert snack.status_code == 201
    result = request("GET", "/insights?start_date=2026-10-12&end_date=2026-10-12", token)
    assert result.status_code == 200, result.text
    summary = result.json()["nutrition_summary"]
    assert summary["nutrition_score"] is None and summary["unavailable_reason"] == "meal_logging_unverified"
    assert summary["calorie_adherence"]["average_actual_calories"] == 89
    assert summary["calorie_adherence"]["average_target_calories"] == round(plan["targets"]["calories"], 2)
    assert summary["target_sources"] == ["current_profile"]
    assert summary["data_completeness"]["meal_logging_percentage"] is None


def test_macro_only_snack_prevents_false_perfect_nutrition_score(meal_log_db):
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-13")
    for meal in plan["meals"]:
        assert log_item(token, plan["meal_plan_id"], meal["id"], {"type": "ate_as_planned"}).status_code == 200

    path = "/insights?start_date=2026-10-13&end_date=2026-10-13"
    baseline = intake_history(token, "2026-10-13", "2026-10-13").json()[0]
    # Align fixture targets exactly so added snack macros must reduce a perfect baseline.
    saved_plan = db.get(MealPlan, UUID(plan["meal_plan_id"]))
    saved_plan.calorie_target = baseline["calories"]
    saved_plan.protein_target = baseline["protein_g"]
    saved_plan.carbohydrate_target = baseline["carbs_g"]
    saved_plan.fat_target = baseline["fat_g"]
    db.commit()
    assert request("GET", path, token).json()["nutrition_summary"]["nutrition_score"] == 100

    snack_macros = {"calories": 100, "protein_g": 2, "carbs_g": 20, "fat_g": 1}
    snack = request("POST", "/nutrition/snacks", token,
                    {"log_date": "2026-10-13", "name": "Only known macros", **snack_macros})
    assert snack.status_code == 201
    actual = intake_history(token, "2026-10-13", "2026-10-13").json()[0]
    for field, amount in snack_macros.items():
        assert actual[field] == pytest.approx(baseline[field] + amount)
    assert actual["fiber_g"] is None and actual["added_sugar_g"] is None

    response = request("GET", path, token)
    assert response.status_code == 200, response.text
    result = response.json()
    assert any(item["code"] == "recorded_nutrition" for item in result["items"])
    summary = result["nutrition_summary"]
    expected = {field: max(0, 100 * (1 - abs(actual[field] - baseline[field]) / baseline[field]))
                for field in snack_macros}
    macro_score = sum(expected[field] for field in ("protein_g", "carbs_g", "fat_g")) / 3
    assert summary["calorie_adherence"]["average_actual_calories"] == round(actual["calories"], 2)
    assert summary["calorie_adherence"]["score"] == round(expected["calories"], 2)
    assert summary["macro_balance"]["protein_adherence_percent"] == round(expected["protein_g"], 2)
    assert summary["macro_balance"]["carbs_adherence_percent"] == round(expected["carbs_g"], 2)
    assert summary["macro_balance"]["fat_adherence_percent"] == round(expected["fat_g"], 2)
    assert summary["macro_balance"]["score"] == round(macro_score, 2)
    assert summary["nutrition_score"] == round((expected["calories"] + macro_score) / 2, 2)
    assert summary["nutrition_score"] < 100
    assert summary["unavailable_reason"] is None
    assert summary["data_completeness"]["scored_days"] == 1
    assert summary["data_completeness"]["unscored_days"] == 0


@pytest.mark.parametrize("missing_code,scorable", [
    ("fiber", True), ("added_sugar", True), ("calcium", True),
    ("calories", False), ("protein", False), ("carbohydrates", False), ("fat", False),
])
def test_only_missing_formula_nutrient_snapshots_prevent_scoring(meal_log_db, missing_code, scorable):
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-15")
    for meal in plan["meals"]:
        logged = log_item(token, plan["meal_plan_id"], meal["id"], {"type": "ate_as_planned"})
        assert logged.status_code == 200, logged.text
    path = "/insights?start_date=2026-10-15&end_date=2026-10-15"
    baseline = request("GET", path, token).json()["nutrition_summary"]
    missing = db.query(MealLogNutrientSnapshot).filter_by(
        meal_log_id=UUID(logged.json()["meal_log_id"]), nutrient_code=missing_code,
    ).one()
    db.delete(missing)
    db.commit()
    response = request("GET", path, token)
    assert response.status_code == 200, response.text
    summary = response.json()["nutrition_summary"]
    for score_field in ("nutrition_score", "calorie_adherence", "macro_balance"):
        if scorable:
            assert summary[score_field] == baseline[score_field]
        else:
            value = summary[score_field] if score_field == "nutrition_score" else summary[score_field]["score"]
            assert value is None
    assert summary["unavailable_reason"] == (None if scorable else "nutrient_data_incomplete")
    assert summary["data_completeness"]["scored_days"] == int(scorable)


def test_insights_tolerate_intake_removed_between_reads(tracking_user, monkeypatch):
    db, token = tracking_user
    snack = request("POST", "/nutrition/snacks", token,
                    {"log_date": "2026-10-14", "name": "Removed during insight read",
                     "calories": 100, "protein_g": 2, "carbs_g": 20, "fat_g": 1}).json()
    original = insight_service.get_daily_intake_history

    def read_then_remove(*args, **kwargs):
        result = original(*args, **kwargs)
        db.delete(db.get(ExtraFoodLog, UUID(snack["id"])))
        db.commit()
        return result

    monkeypatch.setattr(insight_service, "get_daily_intake_history", read_then_remove)
    result = request("GET", "/insights?start_date=2026-10-14&end_date=2026-10-14", token)
    assert result.status_code == 200, result.text
    assert result.json()["nutrition_summary"]["nutrition_score"] is None
