from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.models.food import Food, FoodNutrient
from app.models.meal_log import MealLog
from app.models.meal_plan import MealPlan, MealPlanItem
from app.models.recipe import Recipe
from app.models.user import User
from app.services.meal_log_service import log_meal_plan_item
from app.schemas.meal_log import MealLogRequest
from tests.test_meal_plan_persistence import (
    api_request,
    archive_plan,
    auth_headers,
    create_plan,
    create_profile,
    create_recipe,
    plan_body,
    recipe_payload,
    register_and_login,
    run_async,
    setup_seed_data,
    unique_email,
)


@pytest.fixture(autouse=True)
def require_meal_log_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "foods",
                "recipes",
                "recipe_nutrients",
                "meal_plans",
                "meal_plan_items",
                "meal_plan_item_nutrients",
                "meal_logs",
                "meal_log_nutrients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("meal log tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def meal_log_db():
    db = SessionLocal()
    created_emails: list[str] = []
    created_recipe_ids: list[UUID] = []
    created_food_ids: list[UUID] = []

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    def track_recipe(recipe_id: str | UUID) -> UUID:
        parsed_id = UUID(str(recipe_id))
        created_recipe_ids.append(parsed_id)
        return parsed_id

    def track_food(food_id: UUID) -> UUID:
        created_food_ids.append(food_id)
        return food_id

    yield db, track_email, track_recipe, track_food

    db.rollback()
    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)
    db.commit()

    for recipe_id in created_recipe_ids:
        recipe = db.get(Recipe, recipe_id)
        if recipe is not None:
            db.delete(recipe)
    db.commit()

    for food_id in created_food_ids:
        food = db.get(Food, food_id)
        if food is not None:
            db.delete(food)
    db.commit()
    db.close()


def log_item(token: str, meal_plan_id: str, item_id: str, body: dict):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{meal_plan_id}/items/{item_id}/log",
            headers=auth_headers(token),
            json=body,
        )
    )


def reset_log(token: str, meal_plan_id: str, item_id: str):
    return run_async(
        api_request(
            "DELETE",
            f"/api/v1/meal-plans/{meal_plan_id}/items/{item_id}/log",
            headers=auth_headers(token),
        )
    )


def actual_summary(token: str, meal_plan_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/meal-plans/{meal_plan_id}/actual-summary",
            headers=auth_headers(token),
        )
    )


def create_user_plan(db, track_email, plan_date: str = "2027-03-01") -> tuple[str, dict]:
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("meal-log")))
    create_profile(token)
    response = create_plan(token, plan_body(plan_date=plan_date))
    assert response.status_code == 201, response.text
    return token, response.json()


def first_meal(plan: dict) -> dict:
    return plan["meals"][0]


def nutrient_amounts(log_body: dict) -> dict[str, float]:
    return {item["code"]: item["amount"] for item in log_body["nutrients"]}


def create_test_food(db, track_food, *, calories: float = 120, protein: float = 20) -> Food:
    food = Food(
        name=f"Logging Food {uuid4().hex}",
        source=FoodSource.INTERNAL,
        source_food_id=f"logging_food_{uuid4().hex}",
        category="test",
        description="Meal logging test food.",
    )
    db.add(food)
    db.flush()
    track_food(food.id)
    nutrients = [
        ("calories", "Calories", calories, "kcal"),
        ("protein", "Protein", protein, "g"),
        ("carbohydrates", "Carbohydrates", 10, "g"),
        ("fat", "Fat", 4, "g"),
        ("calcium", "Calcium", 50, "mg"),
    ]
    for code, name, amount, unit in nutrients:
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


def test_meal_log_endpoints_require_authentication() -> None:
    meal_plan_id = uuid4()
    item_id = uuid4()

    post_response = run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{meal_plan_id}/items/{item_id}/log",
            json={"type": "ate_as_planned"},
        )
    )
    summary_response = run_async(
        api_request("GET", f"/api/v1/meal-plans/{meal_plan_id}/actual-summary")
    )
    delete_response = run_async(
        api_request("DELETE", f"/api/v1/meal-plans/{meal_plan_id}/items/{item_id}/log")
    )

    assert post_response.status_code == 401
    assert summary_response.status_code == 401
    assert delete_response.status_code == 401


def test_ate_as_planned_copies_planned_snapshot_and_summary_counts(meal_log_db) -> None:
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-03-02")
    meal = first_meal(plan)

    response = log_item(
        token,
        plan["meal_plan_id"],
        meal["id"],
        {"type": "ate_as_planned"},
    )
    summary = actual_summary(token, plan["meal_plan_id"])

    assert response.status_code == 200, response.text
    assert response.json()["type"] == "ate_as_planned"
    assert nutrient_amounts(response.json()) == meal["nutrition"]
    assert summary.status_code == 200
    body = summary.json()
    assert body["actual_totals"]["calories"] == pytest.approx(meal["nutrition"]["calories"])
    assert body["planned_totals"] == plan["daily_totals"]
    assert body["adherence"]["planned_meals_count"] == len(plan["meals"])
    assert body["adherence"]["logged_meals_count"] == 1
    assert body["adherence"]["unlogged_meals_count"] == len(plan["meals"]) - 1
    assert body["adherence"]["ate_as_planned_count"] == 1
    assert body["adherence"]["corrected_count"] == 0
    assert body["adherence"]["adherence_percent"] == pytest.approx(100 / len(plan["meals"]))


def test_corrected_food_calculates_from_food_per_100g_and_preserves_snapshot(meal_log_db) -> None:
    db, track_email, _, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-03-03")
    meal = first_meal(plan)
    original_plan_totals = plan["daily_totals"]
    food = create_test_food(db, track_food, calories=120, protein=20)

    response = log_item(
        token,
        plan["meal_plan_id"],
        meal["id"],
        {
            "type": "corrected",
            "source_type": "food",
            "food_id": str(food.id),
            "quantity_grams": 180,
        },
    )
    logged = response.json()
    calories_before_food_edit = nutrient_amounts(logged)["calories"]
    db.query(FoodNutrient).filter(
        FoodNutrient.food_id == food.id,
        FoodNutrient.nutrient_code == "calories",
    ).one().amount = 999
    db.commit()
    summary = actual_summary(token, plan["meal_plan_id"]).json()

    assert response.status_code == 200, response.text
    assert logged["type"] == "corrected"
    assert logged["source_type"] == "food"
    assert logged["quantity_grams"] == pytest.approx(180)
    assert nutrient_amounts(logged)["calories"] == pytest.approx(216)
    assert nutrient_amounts(logged)["protein"] == pytest.approx(36)
    assert nutrient_amounts(logged)["calcium"] == pytest.approx(90)
    assert calories_before_food_edit == pytest.approx(216)
    assert summary["actual_totals"]["calories"] == pytest.approx(216)
    assert summary["planned_totals"] == original_plan_totals


def test_corrected_recipe_uses_recipe_nutrients_and_survives_recipe_edit(meal_log_db) -> None:
    db, track_email, track_recipe, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-03-04")
    meal = first_meal(plan)
    food = create_test_food(db, track_food, calories=200, protein=30)
    recipe = create_recipe(
        db,
        token,
        track_recipe,
        recipe_payload(
            db,
            name=f"Logging Recipe {uuid4().hex}",
            tags=["lunch"],
            food_source_ids=[food.source_food_id],
        ),
    )

    response = log_item(
        token,
        plan["meal_plan_id"],
        meal["id"],
        {
            "type": "corrected",
            "source_type": "recipe",
            "recipe_id": recipe["id"],
            "servings": 1.5,
        },
    )
    calories_before_recipe_edit = nutrient_amounts(response.json())["calories"]
    patch_response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{recipe['id']}",
            headers=auth_headers(token),
            json={
                "ingredients": [
                    {
                        "food_id": str(food.id),
                        "quantity_grams": 10,
                        "position": 1,
                    }
                ],
            },
        )
    )
    summary = actual_summary(token, plan["meal_plan_id"]).json()

    assert response.status_code == 200, response.text
    assert patch_response.status_code == 200, patch_response.text
    assert response.json()["source_type"] == "recipe"
    assert response.json()["servings"] == pytest.approx(1.5)
    assert calories_before_recipe_edit == pytest.approx(300)
    assert summary["actual_totals"]["calories"] == pytest.approx(300)


def test_logging_ownership_item_membership_and_archived_plan_behavior(meal_log_db) -> None:
    db, track_email, _, _ = meal_log_db
    owner_token, owner_plan = create_user_plan(db, track_email, plan_date="2027-03-05")
    other_token = register_and_login(track_email(unique_email("meal-log-other")))
    create_profile(other_token)
    _, second_plan = create_user_plan(db, track_email, plan_date="2027-03-06")
    owner_item = first_meal(owner_plan)
    other_plan_log = log_item(
        other_token,
        owner_plan["meal_plan_id"],
        owner_item["id"],
        {"type": "ate_as_planned"},
    )
    wrong_item_log = log_item(
        owner_token,
        owner_plan["meal_plan_id"],
        first_meal(second_plan)["id"],
        {"type": "ate_as_planned"},
    )
    archive_response = archive_plan(owner_token, owner_plan["meal_plan_id"])
    archived_log = log_item(
        owner_token,
        owner_plan["meal_plan_id"],
        owner_item["id"],
        {"type": "ate_as_planned"},
    )

    assert other_plan_log.status_code == 404
    assert other_plan_log.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"
    assert wrong_item_log.status_code == 404
    assert wrong_item_log.json()["error"]["code"] == "MEAL_PLAN_ITEM_NOT_FOUND"
    assert archive_response.status_code == 204
    assert archived_log.status_code == 409
    assert archived_log.json()["error"]["code"] == "MEAL_PLAN_ARCHIVED"


def test_duplicate_logging_updates_existing_log_and_reset_removes_it(meal_log_db) -> None:
    db, track_email, _, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-03-07")
    meal = first_meal(plan)
    food = create_test_food(db, track_food, calories=150, protein=10)

    first = log_item(token, plan["meal_plan_id"], meal["id"], {"type": "ate_as_planned"})
    second = log_item(
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
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["meal_log_id"] == first.json()["meal_log_id"]
    assert second.json()["type"] == "corrected"
    assert db.query(MealLog).filter(MealLog.meal_plan_item_id == UUID(meal["id"])).count() == 1
    reset = reset_log(token, plan["meal_plan_id"], meal["id"])
    after_reset_summary = actual_summary(token, plan["meal_plan_id"]).json()
    assert reset.status_code == 204
    assert after_reset_summary["adherence"]["logged_meals_count"] == 0
    assert "calories" not in after_reset_summary["actual_totals"]


def test_actual_summary_combines_logged_meals_and_reports_differences(meal_log_db) -> None:
    db, track_email, _, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-03-08")
    first, second = plan["meals"][0], plan["meals"][1]
    food = create_test_food(db, track_food, calories=100, protein=10)

    log_item(token, plan["meal_plan_id"], first["id"], {"type": "ate_as_planned"})
    log_item(
        token,
        plan["meal_plan_id"],
        second["id"],
        {
            "type": "corrected",
            "source_type": "food",
            "food_id": str(food.id),
            "quantity_grams": 200,
        },
    )
    summary = actual_summary(token, plan["meal_plan_id"]).json()
    expected_calories = first["nutrition"]["calories"] + 200
    expected_protein = first["nutrition"]["protein"] + 20

    assert summary["actual_totals"]["calories"] == pytest.approx(expected_calories)
    assert summary["actual_totals"]["protein"] == pytest.approx(expected_protein)
    assert summary["actual_totals"]["calcium"] >= 100
    assert summary["difference_actual_vs_planned"]["calories"] == pytest.approx(
        expected_calories - plan["daily_totals"]["calories"]
    )
    assert summary["difference_actual_vs_target"]["calories"] == pytest.approx(
        expected_calories - summary["targets"]["calories"]
    )
    assert summary["adherence"]["logged_meals_count"] == 2
    assert summary["adherence"]["ate_as_planned_count"] == 1
    assert summary["adherence"]["corrected_count"] == 1
    assert summary["adherence"]["adherence_percent"] == pytest.approx(100 / len(plan["meals"]))


def test_logging_rolls_back_when_snapshot_persistence_fails(meal_log_db, monkeypatch) -> None:
    from app.services import meal_log_service

    db, track_email, _, _ = meal_log_db
    setup_seed_data(db)
    email = track_email(unique_email("meal-log"))
    token = register_and_login(email)
    create_profile(token)
    created = create_plan(token, plan_body(plan_date="2027-03-09"))
    assert created.status_code == 201, created.text
    plan = created.json()
    user = db.query(User).filter(User.email == email).one()
    meal = first_meal(plan)

    def fail_snapshots(*args, **kwargs):
        raise RuntimeError("forced log snapshot failure")

    monkeypatch.setattr(meal_log_service, "replace_log_nutrients", fail_snapshots)

    with pytest.raises(RuntimeError):
        log_meal_plan_item(
            db=db,
            user=user,
            meal_plan_id=UUID(plan["meal_plan_id"]),
            meal_plan_item_id=UUID(meal["id"]),
            payload=MealLogRequest(type="ate_as_planned"),
        )

    assert db.query(MealLog).filter(MealLog.meal_plan_item_id == UUID(meal["id"])).count() == 0


def intake_history(token: str, start_date: str, end_date: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/nutrition/intake?from={start_date}&to={end_date}",
            headers=auth_headers(token),
        )
    )


def test_daily_intake_history_uses_only_logged_food(meal_log_db) -> None:
    db, track_email, _, _ = meal_log_db
    token, plan = create_user_plan(
        db,
        track_email,
        plan_date="2027-03-10",
    )
    meal = first_meal(plan)

    log_response = log_item(
        token,
        plan["meal_plan_id"],
        meal["id"],
        {"type": "ate_as_planned"},
    )

    assert log_response.status_code == 200

    response = intake_history(
        token,
        "2027-03-09",
        "2027-03-11",
    )

    assert response.status_code == 200
    body = response.json()

    assert len(body) == 3

    assert body[0] == {
        "date": "2027-03-09",
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
        "added_sugar_g": 0.0,
    }

    logged_day = body[1]

    assert logged_day["date"] == "2027-03-10"
    assert logged_day["calories"] == pytest.approx(
        meal["nutrition"]["calories"]
    )
    assert logged_day["protein_g"] == pytest.approx(
        meal["nutrition"]["protein"]
    )
    assert logged_day["carbs_g"] == pytest.approx(
        meal["nutrition"]["carbohydrates"]
    )
    assert logged_day["fat_g"] == pytest.approx(
        meal["nutrition"]["fat"]
    )

    assert logged_day["calories"] != pytest.approx(
        plan["daily_totals"]["calories"]
    )

    assert body[2] == {
        "date": "2027-03-11",
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
        "added_sugar_g": 0.0,
    }


def test_daily_intake_history_rejects_invalid_date_range(meal_log_db) -> None:
    db, track_email, _, _ = meal_log_db
    token, _ = create_user_plan(
        db,
        track_email,
        plan_date="2027-03-12",
    )

    response = intake_history(
        token,
        "2027-03-20",
        "2027-03-01",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_daily_intake_history_requires_authentication() -> None:
    response = run_async(
        api_request(
            "GET",
            "/api/v1/nutrition/intake?from=2027-03-01&to=2027-03-31",
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"

def test_custom_standalone_snack_is_added_to_daily_intake(meal_log_db) -> None:
    db, track_email, _, _ = meal_log_db
    token, _ = create_user_plan(
        db,
        track_email,
        plan_date="2027-03-20",
    )

    create_response = run_async(
        api_request(
            "POST",
            "/api/v1/nutrition/snacks",
            headers=auth_headers(token),
            json={
                "log_date": "2027-03-20",
                "name": "Protein Snack",
                "calories": 250,
                "protein_g": 20,
                "carbs_g": 30,
                "fat_g": 6,
            },
        )
    )

    assert create_response.status_code == 201

    snack = create_response.json()
    assert snack["name"] == "Protein Snack"
    assert snack["calories"] == 250
    assert snack["protein_g"] == 20
    assert snack["carbs_g"] == 30
    assert snack["fat_g"] == 6

    intake_response = intake_history(
        token,
        "2027-03-20",
        "2027-03-20",
    )

    assert intake_response.status_code == 200

    day = intake_response.json()[0]
    assert day["calories"] == pytest.approx(250)
    assert day["protein_g"] == pytest.approx(20)
    assert day["carbs_g"] == pytest.approx(30)
    assert day["fat_g"] == pytest.approx(6)

    delete_response = run_async(
        api_request(
            "DELETE",
            f"/api/v1/nutrition/snacks/{snack['id']}",
            headers=auth_headers(token),
        )
    )

    assert delete_response.status_code == 204

    intake_after_delete = intake_history(
        token,
        "2027-03-20",
        "2027-03-20",
    )

    assert intake_after_delete.status_code == 200
    assert intake_after_delete.json()[0] == {
        "date": "2027-03-20",
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
        "added_sugar_g": 0.0,
    }

def test_food_based_standalone_snack_calculates_macros(meal_log_db) -> None:
    db, track_email, _, track_food = meal_log_db

    token, _ = create_user_plan(
        db,
        track_email,
        plan_date="2027-03-21",
    )

    food = create_test_food(
        db,
        track_food,
        calories=120,
        protein=20,
    )

    response = run_async(
        api_request(
            "POST",
            "/api/v1/nutrition/snacks",
            headers=auth_headers(token),
            json={
                "log_date": "2027-03-21",
                "food_id": str(food.id),
                "quantity_grams": 200,
            },
        )
    )

    assert response.status_code == 201, response.text

    snack = response.json()

    assert snack["food_id"] == str(food.id)
    assert snack["quantity_grams"] == 200
    assert snack["calories"] == pytest.approx(240)
    assert snack["protein_g"] == pytest.approx(40)
    assert snack["carbs_g"] == pytest.approx(20)
    assert snack["fat_g"] == pytest.approx(8)

def test_actual_micronutrients_include_logged_snack_only(meal_log_db) -> None:
    db, track_email, _, track_food = meal_log_db

    token, _ = create_user_plan(
        db,
        track_email,
        plan_date="2027-03-22",
    )

    food = create_test_food(
        db,
        track_food,
        calories=120,
        protein=20,
    )

    snack_response = run_async(
        api_request(
            "POST",
            "/api/v1/nutrition/snacks",
            headers=auth_headers(token),
            json={
                "log_date": "2027-03-22",
                "food_id": str(food.id),
                "quantity_grams": 200,
            },
        )
    )

    assert snack_response.status_code == 201, snack_response.text

    response = run_async(
        api_request(
            "GET",
            "/api/v1/nutrition/micronutrients/actual?date=2027-03-22",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200, response.text

    body = response.json()
    assert body["date"] == "2027-03-22"

    calcium = next(
        item
        for item in body["micronutrients"]
        if item["code"] == "calcium"
    )

    assert calcium["actual"] == pytest.approx(100)
    assert calcium["target"] > 0
    assert calcium["unit"] == "mg"
    assert calcium["percentage"] == pytest.approx(
        (calcium["actual"] / calcium["target"]) * 100
    )
