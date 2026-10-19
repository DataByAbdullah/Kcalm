from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.foods import get_usda_client
from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.main import app
from app.models.food import Food
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.ai import NaturalLanguageMealConstraintLLMOutput
from app.services import ai_constraint_service
from tests.test_grocery_lists import (
    add_grocery_item,
    create_grocery_list,
    delete_grocery_item,
    get_grocery_list,
    patch_grocery_item,
)
from tests.test_meal_logs import actual_summary, log_item
from tests.test_meal_plan_persistence import (
    api_request,
    auth_headers,
    create_plan,
    create_profile,
    create_recipe,
    food_id,
    plan_body,
    recipe_payload,
    register_and_login,
    run_async,
    setup_seed_data,
    unique_email,
)
from tests.test_usda_integration import FakeUSDAClient, usda_food_payload
from tests.test_weekly_meal_plans import (
    create_recipe_set,
    create_week,
    grocery_preview,
    weekly_body,
)


@pytest.fixture(autouse=True)
def require_mvp_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "foods",
                "food_nutrients",
                "food_servings",
                "recipes",
                "recipe_ingredients",
                "recipe_steps",
                "recipe_nutrients",
                "meal_plans",
                "meal_plan_items",
                "meal_plan_item_nutrients",
                "meal_plan_item_ingredients",
                "meal_plan_micronutrient_targets",
                "weekly_meal_plans",
                "grocery_lists",
                "grocery_list_items",
                "meal_logs",
                "meal_log_nutrients",
                "meal_plan_adaptations",
                "recipe_execution_sessions",
                "recipe_execution_step_snapshots",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("MVP end-to-end test requires all migrated backend tables")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def mvp_db():
    db = SessionLocal()
    created_emails: list[str] = []
    created_recipe_ids: list[UUID] = []
    imported_fdc_ids: list[str] = []

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    def track_recipe(recipe_id: str | UUID) -> UUID:
        parsed_id = UUID(str(recipe_id))
        created_recipe_ids.append(parsed_id)
        return parsed_id

    def track_fdc_id(fdc_id: int) -> int:
        imported_fdc_ids.append(str(fdc_id))
        return fdc_id

    yield db, track_email, track_recipe, track_fdc_id

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

    for fdc_id in imported_fdc_ids:
        food = (
            db.query(Food)
            .filter(Food.source == FoodSource.USDA, Food.source_food_id == fdc_id)
            .one_or_none()
        )
        if food is not None:
            db.delete(food)
    db.commit()
    db.close()
    app.dependency_overrides.pop(get_usda_client, None)


class QueuedInterpreter:
    def __init__(self, outputs: list[NaturalLanguageMealConstraintLLMOutput]) -> None:
        self.outputs = outputs

    def interpret_constraints(self, text: str):
        if not self.outputs:
            raise AssertionError("No queued AI interpretation output remains.")
        return SimpleNamespace(
            output=self.outputs.pop(0),
            model="mock-e2e-model",
            latency_seconds=0.01,
        )


def api_get(path: str, token: str):
    return run_async(api_request("GET", path, headers=auth_headers(token)))


def api_post(path: str, token: str, body: dict):
    return run_async(api_request("POST", path, headers=auth_headers(token), json=body))


def api_patch(path: str, token: str, body: dict):
    return run_async(api_request("PATCH", path, headers=auth_headers(token), json=body))


def lunch_item(plan: dict) -> dict:
    return next(meal for meal in plan["meals"] if meal["meal_type"] == "lunch")


def create_extra_lunch_recipes(db, token: str, track_recipe) -> None:
    for source_food_ids in (
        ["dev_egg", "dev_potato"],
        ["dev_greek_yogurt", "dev_banana"],
    ):
        create_recipe(
            db,
            token,
            track_recipe,
            recipe_payload(
                db,
                name=f"MVP E2E Lunch {uuid4().hex}",
                tags=["lunch", "quick", "high_protein"],
                food_source_ids=source_food_ids,
                equipment=["stovetop"],
            ),
        )


def test_mvp_backend_user_journey(mvp_db, monkeypatch) -> None:
    db, track_email, track_recipe, track_fdc_id = mvp_db
    setup_seed_data(db)
    email = track_email(unique_email("mvp-e2e"))
    token = register_and_login(email)

    create_profile(token)
    profile_update = api_patch(
        "/api/v1/users/profile",
        token,
        {"preferred_foods": ["chicken", "rice"], "max_cooking_minutes": 60},
    )
    assert profile_update.status_code == 200, profile_update.text

    nutrition = api_post(
        "/api/v1/nutrition/calculate",
        token,
        {
            "age": 29,
            "sex": "male",
            "height_cm": 178,
            "weight_kg": 82,
            "activity_level": "moderate",
            "goal": "fat_loss",
            "target_rate": 0.5,
        },
    )
    assert nutrition.status_code == 200, nutrition.text
    assert nutrition.json()["target_calories"] == pytest.approx(2278.4)

    micronutrients = api_get("/api/v1/nutrition/micronutrients", token)
    assert micronutrients.status_code == 200, micronutrients.text
    assert {item["code"] for item in micronutrients.json()["micronutrients"]}.issuperset(
        {"fiber", "calcium", "iron", "vitamin_d"}
    )

    food_list = api_get("/api/v1/foods?search=chicken", token)
    assert food_list.status_code == 200, food_list.text
    assert food_list.json()["total"] >= 1

    fdc_id = track_fdc_id(990001)
    app.dependency_overrides[get_usda_client] = lambda: FakeUSDAClient(
        search_payload={
            "foods": [
                {
                    "fdcId": fdc_id,
                    "description": "Chicken breast, cooked",
                    "dataType": "Foundation",
                    "brandOwner": None,
                }
            ],
            "totalHits": 1,
        },
        food_payload=usda_food_payload(fdc_id),
    )
    usda_search = api_get("/api/v1/foods/usda/search?q=chicken&page_size=5&page=1", token)
    assert usda_search.status_code == 200, usda_search.text
    assert usda_search.json()["items"][0]["fdc_id"] == fdc_id
    usda_import = api_post(f"/api/v1/foods/usda/import/{fdc_id}", token, {})
    assert usda_import.status_code == 201, usda_import.text
    assert usda_import.json()["status"] == "imported"

    recipes = api_get("/api/v1/recipes", token)
    assert recipes.status_code == 200, recipes.text
    assert recipes.json()["total"] >= 1

    create_extra_lunch_recipes(db, token, track_recipe)
    candidate_preview = api_post(
        "/api/v1/recipes/candidates/preview",
        token,
        {
            "meal_type": "lunch",
            "max_total_time_minutes": 60,
            "require_complete_nutrition": True,
            "required_tags": ["quick"],
        },
    )
    assert candidate_preview.status_code == 200, candidate_preview.text
    assert candidate_preview.json()["total_eligible"] >= 1

    plan_response = create_plan(token, plan_body(plan_date="2028-01-03"))
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    assert {meal["meal_type"] for meal in plan["meals"]}.issuperset(
        {"breakfast", "lunch", "dinner"}
    )

    plan_detail = api_get(f"/api/v1/meal-plans/{plan['meal_plan_id']}", token)
    assert plan_detail.status_code == 200, plan_detail.text
    plan = plan_detail.json()

    swapped = api_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{lunch_item(plan)['id']}/swap",
        token,
        {"required_tags": ["quick"], "max_total_time_minutes": 60},
    )
    assert swapped.status_code == 200, swapped.text
    plan = swapped.json()

    weekly_recipes = create_recipe_set(db, token, track_recipe)
    selected_weekly_ids = {recipe["id"] for recipe in weekly_recipes.values()}
    week_response = create_week(
        token,
        weekly_body(db, selected_weekly_ids, start_date="2028-02-07"),
    )
    assert week_response.status_code == 201, week_response.text
    week = week_response.json()
    assert len(week["daily_plans"]) == 7

    grocery_preview_response = grocery_preview(token, week["weekly_plan_id"])
    assert grocery_preview_response.status_code == 200, grocery_preview_response.text
    grocery_list_response = create_grocery_list(token, week["weekly_plan_id"])
    assert grocery_list_response.status_code == 201, grocery_list_response.text
    grocery_list = grocery_list_response.json()
    generated_item = next(item for item in grocery_list["items"] if not item["manually_added"])
    checked = patch_grocery_item(
        token,
        grocery_list["grocery_list_id"],
        generated_item["id"],
        {"checked": True},
    )
    assert checked.status_code == 200, checked.text
    manual_item_response = add_grocery_item(
        token,
        grocery_list["grocery_list_id"],
        {"name": "Sparkling Water", "quantity": 2, "unit": "bottle", "category": "other"},
    )
    assert manual_item_response.status_code == 201, manual_item_response.text
    manual_item = next(
        item
        for item in manual_item_response.json()["items"]
        if item["food_name"] == "Sparkling Water"
    )
    removed = delete_grocery_item(
        token,
        grocery_list["grocery_list_id"],
        manual_item["id"],
    )
    assert removed.status_code == 204
    assert get_grocery_list(token, grocery_list["grocery_list_id"]).status_code == 200

    for meal in plan["meals"]:
        logged = log_item(
            token,
            plan["meal_plan_id"],
            meal["id"],
            {"type": "ate_as_planned"},
        )
        assert logged.status_code == 200, logged.text

    correction = log_item(
        token,
        plan["meal_plan_id"],
        plan["meals"][0]["id"],
        {
            "type": "corrected",
            "source_type": "food",
            "food_id": food_id(db, "dev_chicken_breast"),
            "quantity_grams": 180,
        },
    )
    assert correction.status_code == 200, correction.text
    summary = actual_summary(token, plan["meal_plan_id"])
    assert summary.status_code == 200, summary.text
    assert summary.json()["adherence"]["logged_meals_count"] == len(plan["meals"])

    adaptive_preview = api_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/adaptive-preview",
        token,
        {},
    )
    assert adaptive_preview.status_code == 200, adaptive_preview.text
    adaptive_generate = api_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/generate-next-day",
        token,
        {},
    )
    assert adaptive_generate.status_code == 201, adaptive_generate.text

    interpreter = QueuedInterpreter(
        [
            NaturalLanguageMealConstraintLLMOutput(
                requested_action="find_options",
                meal_type="dinner",
                required_tags=["quick"],
            ),
            NaturalLanguageMealConstraintLLMOutput(
                requested_action="find_options",
                meal_type="lunch",
                required_tags=["quick"],
            ),
            NaturalLanguageMealConstraintLLMOutput(
                requested_action="swap_meal",
                meal_type="lunch",
                required_tags=["quick"],
            ),
        ]
    )
    monkeypatch.setattr(ai_constraint_service, "get_ai_interpreter", lambda: interpreter)
    interpreted = api_post(
        "/api/v1/ai/constraints/interpret",
        token,
        {"text": "quick dinner"},
    )
    assert interpreted.status_code == 200, interpreted.text
    assert interpreted.json()["required_tags"] == ["quick"]
    options = api_post(
        "/api/v1/ai/meal-options",
        token,
        {"text": "show me quick lunch options"},
    )
    assert options.status_code == 200, options.text
    assert options.json()["candidate_preview"]["total_eligible"] >= 1
    ai_swapped = api_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{lunch_item(plan)['id']}/ai-swap",
        token,
        {"text": "swap this for a quick lunch"},
    )
    assert ai_swapped.status_code == 200, ai_swapped.text
    plan = ai_swapped.json()

    execution_start = api_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{plan['meals'][0]['id']}/execution-session",
        token,
        {},
    )
    assert execution_start.status_code == 201, execution_start.text
    session = execution_start.json()
    assert session["step_count"] >= 1
    progress = api_patch(
        f"/api/v1/recipe-execution-sessions/{session['session_id']}/progress",
        token,
        {"current_step_index": min(1, session["step_count"] - 1)},
    )
    assert progress.status_code == 200, progress.text
    completed = api_post(
        f"/api/v1/recipe-execution-sessions/{session['session_id']}/complete",
        token,
        {},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
