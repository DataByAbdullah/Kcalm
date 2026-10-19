from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.meal_planning.solver import CARBOHYDRATES_CODE, FAT_CODE, PROTEIN_CODE
from app.models.adaptation import MealPlanAdaptationSnapshot
from app.models.food import Food, FoodNutrient
from app.models.meal_log import MealLog
from app.models.meal_plan import MealPlan
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.adaptive_planning import AdaptivePlanRequest
from app.services.adaptive_planning_service import (
    apply_compensation_policy,
    create_adaptive_next_day_plan,
)
from tests.test_meal_logs import log_item
from tests.test_meal_plan_persistence import (
    api_request,
    archive_plan,
    auth_headers,
    create_plan,
    create_profile,
    plan_body,
    register_and_login,
    run_async,
    setup_seed_data,
    unique_email,
)


@pytest.fixture(autouse=True)
def require_adaptive_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "foods",
                "recipes",
                "meal_plans",
                "meal_plan_items",
                "meal_plan_item_nutrients",
                "meal_plan_micronutrient_targets",
                "meal_logs",
                "meal_log_nutrients",
                "meal_plan_adaptations",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("adaptive planning tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def adaptive_db():
    db = SessionLocal()
    created_emails: list[str] = []
    created_food_ids: list[UUID] = []

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    def track_food(food_id: UUID) -> UUID:
        created_food_ids.append(food_id)
        return food_id

    yield db, track_email, track_food

    db.rollback()
    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)
    db.commit()

    for food_id in created_food_ids:
        food = db.get(Food, food_id)
        if food is not None:
            db.delete(food)
    db.commit()
    db.close()


NUTRIENT_META = {
    "calories": ("Calories", "kcal"),
    "protein": ("Protein", "g"),
    "carbohydrates": ("Carbohydrates", "g"),
    "fat": ("Fat", "g"),
    "calcium": ("Calcium", "mg"),
}


def adaptive_preview(token: str, source_plan_id: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{source_plan_id}/adaptive-preview",
            headers=auth_headers(token),
            json=body or {},
        )
    )


def generate_next_day(token: str, source_plan_id: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{source_plan_id}/generate-next-day",
            headers=auth_headers(token),
            json=body or {},
        )
    )


def create_source_plan(db, track_email, plan_date: str = "2027-04-01") -> tuple[str, dict]:
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("adaptive")))
    create_profile(token)
    response = create_plan(token, plan_body(plan_date=plan_date))
    assert response.status_code == 201, response.text
    return token, response.json()


def create_logged_food(
    db,
    track_food,
    *,
    nutrients: dict[str, float],
) -> Food:
    food = Food(
        name=f"Adaptive Food {uuid4().hex}",
        source=FoodSource.INTERNAL,
        source_food_id=f"adaptive_food_{uuid4().hex}",
        category="test",
        description="Adaptive planning test food.",
    )
    db.add(food)
    db.flush()
    track_food(food.id)
    for code, amount in nutrients.items():
        name, unit = NUTRIENT_META[code]
        db.add(
            FoodNutrient(
                food_id=food.id,
                nutrient_code=code,
                nutrient_name=name,
                amount=amount,
                unit=unit,
            )
        )
    db.commit()
    db.refresh(food)
    return food


def complete_logs_as_planned(token: str, plan: dict) -> None:
    for meal in plan["meals"]:
        response = log_item(
            token,
            plan["meal_plan_id"],
            meal["id"],
            {"type": "ate_as_planned"},
        )
        assert response.status_code == 200, response.text


def complete_logs_with_first_food(token: str, plan: dict, food: Food) -> None:
    first, *rest = plan["meals"]
    response = log_item(
        token,
        plan["meal_plan_id"],
        first["id"],
        {
            "type": "corrected",
            "source_type": "food",
            "food_id": str(food.id),
            "quantity_grams": 100,
        },
    )
    assert response.status_code == 200, response.text
    for meal in rest:
        response = log_item(
            token,
            plan["meal_plan_id"],
            meal["id"],
            {"type": "ate_as_planned"},
        )
        assert response.status_code == 200, response.text


def complete_logs_with_food_for_every_meal(token: str, plan: dict, food: Food) -> None:
    for meal in plan["meals"]:
        response = log_item(
            token,
            plan["meal_plan_id"],
            meal["id"],
            {
                "type": "corrected",
                "source_type": "food",
                "food_id": str(food.id),
                "quantity_grams": 100,
            },
        )
        assert response.status_code == 200, response.text


def next_day(plan: dict) -> str:
    return (date.fromisoformat(plan["plan_date"]) + timedelta(days=1)).isoformat()


def calorie_deviation(body: dict) -> dict:
    return next(
        item for item in body["solver_preview"]["deviations"]
        if item["nutrient_code"] == "calories"
    )


def test_adaptive_endpoints_require_authentication() -> None:
    source_plan_id = uuid4()

    preview = run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{source_plan_id}/adaptive-preview",
            json={},
        )
    )
    generate = run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{source_plan_id}/generate-next-day",
            json={},
        )
    )

    assert preview.status_code == 401
    assert generate.status_code == 401


def test_no_logs_and_partial_logs_are_rejected(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-02")

    no_logs = adaptive_preview(token, plan["meal_plan_id"])
    assert no_logs.status_code == 409
    assert no_logs.json()["error"]["code"] == "INCOMPLETE_DAILY_LOG"
    assert no_logs.json()["error"]["details"]["logged_meals_count"] == 0

    first_meal = plan["meals"][0]
    log_response = log_item(
        token,
        plan["meal_plan_id"],
        first_meal["id"],
        {"type": "ate_as_planned"},
    )
    partial = adaptive_preview(token, plan["meal_plan_id"])

    assert log_response.status_code == 200
    assert partial.status_code == 409
    assert partial.json()["error"]["code"] == "INCOMPLETE_DAILY_LOG"
    assert partial.json()["error"]["details"]["logged_meals_count"] == 1
    assert len(partial.json()["error"]["details"]["unlogged_meal_item_ids"]) == len(plan["meals"]) - 1


def test_complete_logged_day_previews_overage_adjustment_without_persisting(adaptive_db) -> None:
    db, track_email, track_food = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-03")
    target_calories = plan["targets"]["calories"]
    planned_calories = plan["daily_totals"]["calories"]
    first_calories = plan["meals"][0]["nutrition"]["calories"]
    intended_deviation = 400.0
    replacement_calories = first_calories + target_calories + intended_deviation - planned_calories
    food = create_logged_food(
        db,
        track_food,
        nutrients={
            "calories": replacement_calories,
            "protein": 25,
            "carbohydrates": 15,
            "fat": 5,
            "calcium": 50,
        },
    )
    complete_logs_with_first_food(token, plan, food)

    response = adaptive_preview(token, plan["meal_plan_id"])
    repeat = adaptive_preview(token, plan["meal_plan_id"])
    body = response.json()
    adjusted = body["adjusted_targets"]

    assert response.status_code == 200, response.text
    assert repeat.status_code == 200, repeat.text
    assert body["next_day_date"] == next_day(plan)
    assert body["deviation"]["calories"] == pytest.approx(intended_deviation)
    assert adjusted == repeat.json()["adjusted_targets"]
    assert adjusted["raw_compensation_amount"] == pytest.approx(-100.0)
    assert adjusted["compensation_amount"] == pytest.approx(-100.0)
    assert adjusted["adjusted_calorie_target"] == pytest.approx(target_calories - 100.0)
    assert adjusted["base_macro_targets"][PROTEIN_CODE] == pytest.approx(plan["targets"]["protein_g"])
    assert adjusted["base_macro_targets"][FAT_CODE] == pytest.approx(plan["targets"]["fat_g"])
    assert adjusted["adjusted_macro_targets"][PROTEIN_CODE] == pytest.approx(plan["targets"]["protein_g"])
    assert adjusted["adjusted_macro_targets"][FAT_CODE] == pytest.approx(plan["targets"]["fat_g"])
    expected_carbs = (
        adjusted["adjusted_calorie_target"]
        - adjusted["adjusted_macro_targets"][PROTEIN_CODE] * 4
        - adjusted["adjusted_macro_targets"][FAT_CODE] * 9
    ) / 4
    assert adjusted["adjusted_macro_targets"][CARBOHYDRATES_CODE] == pytest.approx(expected_carbs)
    assert adjusted["micronutrient_strategy"] == "report_only_standard_targets_unchanged"
    assert body["solver_preview"]["targets"]["calories"] == pytest.approx(
        adjusted["adjusted_calorie_target"]
    )
    assert calorie_deviation(body)["tolerance_lower"] == pytest.approx(
        adjusted["adjusted_calorie_target"] * 0.95
    )
    assert db.query(MealPlan).filter(MealPlan.plan_date == date.fromisoformat(next_day(plan))).count() == 0


def test_compensation_policy_caps_positive_and_negative_adjustments(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    _, plan = create_source_plan(db, track_email, plan_date="2027-04-04")
    source_plan = db.get(MealPlan, UUID(plan["meal_plan_id"]))
    cap = min(250.0, source_plan.calorie_target * 0.10)

    overage = apply_compensation_policy(
        source_plan=source_plan,
        actual_totals={"calories": source_plan.calorie_target + 10_000},
        calorie_deviation=10_000,
    )
    underage = apply_compensation_policy(
        source_plan=source_plan,
        actual_totals={"calories": 1},
        calorie_deviation=-10_000,
    )

    assert overage.raw_compensation_amount == pytest.approx(-2500)
    assert overage.compensation_amount == pytest.approx(-cap)
    assert overage.adjusted_calorie_target == pytest.approx(source_plan.calorie_target - cap)
    assert overage.safety_caps_applied == ["max_adjustment_cap"]
    assert underage.raw_compensation_amount == pytest.approx(2500)
    assert underage.compensation_amount == pytest.approx(cap)
    assert underage.adjusted_calorie_target == pytest.approx(source_plan.calorie_target + cap)
    assert underage.safety_caps_applied == ["max_adjustment_cap"]


def test_generate_next_day_persists_plan_and_adaptation_metadata(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-05")
    complete_logs_as_planned(token, plan)
    source_plan = db.get(MealPlan, UUID(plan["meal_plan_id"]))
    source_target_before = source_plan.calorie_target
    source_log_count_before = db.query(MealLog).filter(
        MealLog.meal_plan_id == source_plan.id
    ).count()

    response = generate_next_day(token, plan["meal_plan_id"])
    body = response.json()
    persisted = db.query(MealPlanAdaptationSnapshot).filter(
        MealPlanAdaptationSnapshot.meal_plan_id == UUID(body["plan"]["meal_plan_id"])
    ).one_or_none()
    db.refresh(source_plan)
    source_log_count_after = db.query(MealLog).filter(
        MealLog.meal_plan_id == source_plan.id
    ).count()

    assert response.status_code == 201, response.text
    assert body["plan"]["plan_date"] == next_day(plan)
    assert body["plan"]["targets"]["calories"] == pytest.approx(
        body["adaptation"]["adjusted_calorie_target"]
    )
    assert persisted is not None
    assert persisted.source_meal_plan_id == UUID(plan["meal_plan_id"])
    assert persisted.policy_version == "adaptive_v1"
    assert persisted.adjusted_calorie_target == pytest.approx(
        body["adaptation"]["adjusted_calorie_target"]
    )
    assert source_plan.calorie_target == pytest.approx(source_target_before)
    assert source_log_count_after == source_log_count_before


def test_existing_next_day_plan_conflict_is_not_overwritten(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-06")
    complete_logs_as_planned(token, plan)
    existing = create_plan(token, plan_body(plan_date=next_day(plan)))
    assert existing.status_code == 201, existing.text

    response = generate_next_day(token, plan["meal_plan_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_ALREADY_EXISTS"


def test_missing_macro_snapshot_data_is_rejected(adaptive_db) -> None:
    db, track_email, track_food = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-08")
    food = create_logged_food(
        db,
        track_food,
        nutrients={"calories": 100, "protein": 10, "carbohydrates": 20},
    )
    complete_logs_with_food_for_every_meal(token, plan, food)

    response = adaptive_preview(token, plan["meal_plan_id"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTUAL_LOG_NUTRITION_INCOMPLETE"
    assert "fat" in response.json()["error"]["details"]["missing_or_invalid_codes"]


def test_ownership_is_enforced_without_leaking_source_plan(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    owner_token, plan = create_source_plan(db, track_email, plan_date="2027-04-09")
    complete_logs_as_planned(owner_token, plan)
    other_token = register_and_login(track_email(unique_email("adaptive-other")))
    create_profile(other_token)

    preview = adaptive_preview(other_token, plan["meal_plan_id"])
    generate = generate_next_day(other_token, plan["meal_plan_id"])

    assert preview.status_code == 404
    assert preview.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"
    assert generate.status_code == 404
    assert generate.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"


def test_excluded_recipe_constraints_are_passed_to_candidate_filter(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-10")
    complete_logs_as_planned(token, plan)
    excluded_recipe_id = plan["meals"][0]["recipe_id"]

    response = adaptive_preview(
        token,
        plan["meal_plan_id"],
        {"excluded_recipe_ids": [excluded_recipe_id]},
    )

    assert response.status_code == 200, response.text
    selected_recipe_ids = {
        meal["recipe_id"] for meal in response.json()["solver_preview"]["meals"]
    }
    assert excluded_recipe_id not in selected_recipe_ids


def test_infeasible_next_day_solver_returns_controlled_error(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-11")
    complete_logs_as_planned(token, plan)
    all_recipe_ids = [str(row[0]) for row in db.query(Recipe.id).filter(Recipe.active.is_(True)).all()]

    preview = adaptive_preview(
        token,
        plan["meal_plan_id"],
        {"excluded_recipe_ids": all_recipe_ids},
    )
    generate = generate_next_day(
        token,
        plan["meal_plan_id"],
        {"excluded_recipe_ids": all_recipe_ids},
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["solver_preview"]["status"] == "infeasible"
    assert generate.status_code == 422
    assert generate.json()["error"]["code"] == "ADAPTIVE_PLAN_INFEASIBLE"


def test_archived_source_plan_is_rejected(adaptive_db) -> None:
    db, track_email, _ = adaptive_db
    token, plan = create_source_plan(db, track_email, plan_date="2027-04-12")
    complete_logs_as_planned(token, plan)
    archive = archive_plan(token, plan["meal_plan_id"])

    response = adaptive_preview(token, plan["meal_plan_id"])

    assert archive.status_code == 204
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MEAL_PLAN_ARCHIVED"


def test_adaptive_plan_rolls_back_when_metadata_persistence_fails(adaptive_db, monkeypatch) -> None:
    from app.services import adaptive_planning_service

    db, track_email, _ = adaptive_db
    email = track_email(unique_email("adaptive-rollback"))
    setup_seed_data(db)
    token = register_and_login(email)
    create_profile(token)
    created = create_plan(token, plan_body(plan_date="2027-04-13"))
    assert created.status_code == 201, created.text
    plan = created.json()
    complete_logs_as_planned(token, plan)
    user = db.query(User).filter(User.email == email).one()

    def fail_metadata(*args, **kwargs):
        raise RuntimeError("forced adaptation metadata failure")

    monkeypatch.setattr(adaptive_planning_service, "persist_adaptation_snapshot", fail_metadata)

    with pytest.raises(RuntimeError):
        create_adaptive_next_day_plan(
            db=db,
            user=user,
            source_plan_id=UUID(plan["meal_plan_id"]),
            payload=AdaptivePlanRequest(),
        )

    assert db.query(MealPlan).filter(
        MealPlan.user_id == user.id,
        MealPlan.plan_date == date.fromisoformat(next_day(plan)),
    ).count() == 0
