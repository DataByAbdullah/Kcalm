import asyncio
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.main import app
from app.models.food import Food
from app.models.meal_plan import MealPlan, MealPlanItem
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.meal_plan import MealPlanCreateRequest
from app.services.food_seed_service import seed_development_foods
from app.services.meal_plan_service import create_daily_meal_plan
from app.services.recipe_seed_service import seed_development_recipes


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_meal_plan_tables():
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
                "meal_plan_micronutrient_targets",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("meal plan tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def meal_plan_db():
    db = SessionLocal()
    created_emails: list[str] = []
    created_recipe_ids: list[UUID] = []

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    def track_recipe(recipe_id: str | UUID) -> UUID:
        parsed_id = UUID(str(recipe_id))
        created_recipe_ids.append(parsed_id)
        return parsed_id

    yield db, track_email, track_recipe

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
    db.close()


def unique_email(prefix: str = "meal-plan") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_and_login(email: str) -> str:
    register_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert register_response.status_code == 201

    login_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def create_profile(token: str, **overrides) -> None:
    payload = {
        "age": 29,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "activity_level": "moderate",
        "goal": "fat_loss",
        "target_rate": 0.5,
        "max_cooking_minutes": 60,
        "meals_per_day": 4,
        "allergies": [],
        "dietary_restrictions": [],
        "preferred_foods": [],
        "disliked_foods": [],
        "equipment": ["stovetop", "oven", "blender"],
    }
    payload.update(overrides)
    response = run_async(
        api_request(
            "POST",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=payload,
        )
    )
    assert response.status_code == 201, response.text


def setup_seed_data(db) -> None:
    seed_development_foods(db)
    seed_development_recipes(db)


def create_plan(token: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/meal-plans",
            headers=auth_headers(token),
            json=body or plan_body(),
        )
    )


def preview_plan(token: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/meal-plans/solve/preview",
            headers=auth_headers(token),
            json=body or {},
        )
    )


def plan_body(plan_date: str = "2026-10-03", **overrides) -> dict:
    body = {
        "plan_date": plan_date,
        "meal_slots": [
            {"meal_type": "breakfast", "required": True},
            {"meal_type": "lunch", "required": True},
            {"meal_type": "dinner", "required": True},
            {"meal_type": "snack", "required": False},
        ],
        "max_total_time_minutes": 60,
        "require_complete_nutrition": True,
        "required_nutrient_codes": [],
        "excluded_recipe_ids": [],
        "required_tags": [],
        "excluded_tags": [],
        "solver_time_limit_seconds": 3,
    }
    body.update(overrides)
    return body


def get_plan(token: str, meal_plan_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/meal-plans/{meal_plan_id}",
            headers=auth_headers(token),
        )
    )


def list_plans(token: str, query: str = ""):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/meal-plans{query}",
            headers=auth_headers(token),
        )
    )


def archive_plan(token: str, meal_plan_id: str):
    return run_async(
        api_request(
            "DELETE",
            f"/api/v1/meal-plans/{meal_plan_id}",
            headers=auth_headers(token),
        )
    )


def food_id(db, source_food_id: str) -> str:
    food = db.query(Food).filter(Food.source_food_id == source_food_id).one()
    return str(food.id)


def recipe_payload(
    db,
    name: str,
    tags: list[str],
    food_source_ids: list[str],
    equipment: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "description": "Meal plan persistence test recipe.",
        "servings": 1,
        "prep_time_minutes": 5,
        "cook_time_minutes": 5,
        "difficulty": "easy",
        "ingredients": [
            {
                "food_id": food_id(db, source_food_id),
                "quantity_grams": 100,
                "position": index,
            }
            for index, source_food_id in enumerate(food_source_ids, start=1)
        ],
        "steps": [{"position": 1, "instruction": "Serve."}],
        "tags": tags,
        "equipment": equipment or [],
    }


def create_recipe(db, token: str, track_recipe, payload: dict) -> dict:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/recipes",
            headers=auth_headers(token),
            json=payload,
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    track_recipe(body["id"])
    return body


def assert_totals_match_meals(body: dict) -> None:
    for nutrient_code, total in body["daily_totals"].items():
        expected = sum(
            meal["nutrition"].get(nutrient_code, 0)
            for meal in body["meals"]
        )
        assert total == pytest.approx(expected)


def test_meal_plan_endpoints_require_authentication() -> None:
    create_response = run_async(api_request("POST", "/api/v1/meal-plans", json={}))
    list_response = run_async(api_request("GET", "/api/v1/meal-plans"))
    detail_response = run_async(api_request("GET", f"/api/v1/meal-plans/{uuid4()}"))

    assert create_response.status_code == 401
    assert list_response.status_code == 401
    assert detail_response.status_code == 401


def test_successful_plan_creation_persists_snapshots(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)

    response = create_plan(token)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["meal_plan_id"]
    assert body["plan_date"] == "2026-10-03"
    assert body["status"] == "generated"
    assert body["solver_status"] in {"optimal", "feasible"}
    assert {meal["meal_type"] for meal in body["meals"]}.issuperset(
        {"breakfast", "lunch", "dinner"}
    )
    assert body["targets"]["calories"] == pytest.approx(2278.375)
    assert body["targets"]["protein_g"] == pytest.approx(164.0)
    assert body["targets"]["carbohydrates_g"] == pytest.approx(257.99375)
    assert body["targets"]["fat_g"] == pytest.approx(65.6)
    assert body["targets"]["micronutrients"]
    assert body["deviations"]
    assert body["micronutrient_coverage"]
    assert_totals_match_meals(body)

    meal_plan_id = UUID(body["meal_plan_id"])
    persisted = db.get(MealPlan, meal_plan_id)
    assert persisted is not None
    assert len(persisted.items) == len(body["meals"])
    assert (
        db.query(MealPlanItem)
        .filter(MealPlanItem.meal_plan_id == meal_plan_id)
        .count()
    ) == len(body["meals"])


def test_get_plan_detail_matches_create_response(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    create_response = create_plan(token, plan_body(plan_date="2026-10-04"))
    assert create_response.status_code == 201

    detail_response = get_plan(token, create_response.json()["meal_plan_id"])

    assert detail_response.status_code == 200
    created = create_response.json()
    fetched = detail_response.json()
    assert fetched["meal_plan_id"] == created["meal_plan_id"]
    assert fetched["plan_date"] == created["plan_date"]
    assert fetched["daily_totals"] == created["daily_totals"]
    assert fetched["targets"] == created["targets"]


def test_plan_list_date_and_status_filters(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    first = create_plan(token, plan_body(plan_date="2026-10-05"))
    second = create_plan(token, plan_body(plan_date="2026-10-06"))
    assert first.status_code == 201
    assert second.status_code == 201
    archive_response = archive_plan(token, second.json()["meal_plan_id"])
    assert archive_response.status_code == 204

    default_list = list_plans(token)
    date_list = list_plans(token, "?plan_date=2026-10-05")
    archived_list = list_plans(token, "?status=archived")

    assert default_list.status_code == 200
    assert {item["meal_plan_id"] for item in default_list.json()["items"]} == {
        first.json()["meal_plan_id"]
    }
    assert date_list.json()["total"] == 1
    assert date_list.json()["items"][0]["meal_plan_id"] == first.json()["meal_plan_id"]
    assert archived_list.json()["total"] == 1
    assert archived_list.json()["items"][0]["meal_plan_id"] == second.json()["meal_plan_id"]


def test_plan_ownership_is_isolated(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    owner_token = register_and_login(track_email(unique_email("owner")))
    other_token = register_and_login(track_email(unique_email("other")))
    create_profile(owner_token)
    create_profile(other_token)
    create_response = create_plan(owner_token, plan_body(plan_date="2026-10-07"))
    assert create_response.status_code == 201

    other_detail = get_plan(other_token, create_response.json()["meal_plan_id"])
    other_archive = archive_plan(other_token, create_response.json()["meal_plan_id"])

    assert other_detail.status_code == 404
    assert other_detail.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"
    assert other_archive.status_code == 404
    assert other_archive.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"


def test_duplicate_same_date_plan_is_blocked(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    first = create_plan(token, plan_body(plan_date="2026-10-08"))
    second = create_plan(token, plan_body(plan_date="2026-10-08"))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PLAN_ALREADY_EXISTS"


def test_infeasible_solver_does_not_persist_plan(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    email = track_email(unique_email())
    token = register_and_login(email)
    create_profile(token, equipment=[])
    response = create_plan(
        token,
        plan_body(
            plan_date="2026-10-09",
            meal_slots=[{"meal_type": "dinner", "required": True}],
            required_tags=["vegetarian"],
        ),
    )

    user = db.query(User).filter(User.email == email).one()
    persisted_count = (
        db.query(MealPlan)
        .filter(MealPlan.user_id == user.id, MealPlan.plan_date == date(2026, 10, 9))
        .count()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MEAL_PLAN_INFEASIBLE"
    assert persisted_count == 0


def test_archive_endpoint_soft_archives_plan(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    create_response = create_plan(token, plan_body(plan_date="2026-10-10"))
    meal_plan_id = create_response.json()["meal_plan_id"]

    archive_response = archive_plan(token, meal_plan_id)
    detail_response = get_plan(token, meal_plan_id)
    default_list = list_plans(token)

    assert archive_response.status_code == 204
    assert detail_response.json()["status"] == "archived"
    assert meal_plan_id not in {
        item["meal_plan_id"] for item in default_list.json()["items"]
    }


def test_recipe_edit_does_not_change_saved_plan_snapshots(meal_plan_db) -> None:
    db, track_email, track_recipe = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    breakfast = create_recipe(
        db,
        token,
        track_recipe,
        recipe_payload(
            db,
            name=f"Snapshot Breakfast {uuid4().hex}",
            tags=["breakfast"],
            food_source_ids=["dev_oats", "dev_banana"],
        ),
    )
    lunch = create_recipe(
        db,
        token,
        track_recipe,
        recipe_payload(
            db,
            name=f"Snapshot Lunch {uuid4().hex}",
            tags=["lunch"],
            food_source_ids=["dev_chicken_breast", "dev_cooked_rice"],
        ),
    )
    dinner = create_recipe(
        db,
        token,
        track_recipe,
        recipe_payload(
            db,
            name=f"Snapshot Dinner {uuid4().hex}",
            tags=["dinner"],
            food_source_ids=["dev_salmon", "dev_potato"],
        ),
    )
    selected_ids = {breakfast["id"], lunch["id"], dinner["id"]}
    excluded_ids = [
        str(recipe.id)
        for recipe in db.query(Recipe).filter(Recipe.active.is_(True)).all()
        if str(recipe.id) not in selected_ids
    ]
    create_response = create_plan(
        token,
        plan_body(
            plan_date="2026-10-11",
            meal_slots=[
                {"meal_type": "breakfast", "required": True},
                {"meal_type": "lunch", "required": True},
                {"meal_type": "dinner", "required": True},
            ],
            excluded_recipe_ids=excluded_ids,
        ),
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    original_totals = created["daily_totals"]
    original_breakfast_name = next(
        meal["recipe_name"] for meal in created["meals"] if meal["recipe_id"] == breakfast["id"]
    )

    patch_response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{breakfast['id']}",
            headers=auth_headers(token),
            json={
                "name": "Changed Snapshot Breakfast",
                "ingredients": [
                    {
                        "food_id": food_id(db, "dev_olive_oil"),
                        "quantity_grams": 100,
                        "position": 1,
                    }
                ],
            },
        )
    )
    assert patch_response.status_code == 200, patch_response.text

    fetched = get_plan(token, created["meal_plan_id"]).json()
    fetched_breakfast_name = next(
        meal["recipe_name"] for meal in fetched["meals"] if meal["recipe_id"] == breakfast["id"]
    )
    assert fetched["daily_totals"] == original_totals
    assert fetched_breakfast_name == original_breakfast_name


def test_profile_change_does_not_change_target_snapshot(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    create_response = create_plan(token, plan_body(plan_date="2026-10-12"))
    original_targets = create_response.json()["targets"]

    profile_update = run_async(
        api_request(
            "PATCH",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json={"weight_kg": 120, "goal": "muscle_gain", "target_rate": 0.25},
        )
    )
    assert profile_update.status_code == 200

    fetched = get_plan(token, create_response.json()["meal_plan_id"]).json()
    assert fetched["targets"] == original_targets


def test_transaction_rolls_back_when_item_persistence_fails(meal_plan_db, monkeypatch) -> None:
    from app.services import meal_plan_service

    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    email = track_email(unique_email())
    token = register_and_login(email)
    create_profile(token)
    user = db.query(User).filter(User.email == email).one()

    def fail_items(*args, **kwargs):
        raise RuntimeError("forced item persistence failure")

    monkeypatch.setattr(meal_plan_service, "persist_meal_plan_items", fail_items)

    with pytest.raises(RuntimeError):
        create_daily_meal_plan(
            db=db,
            user=user,
            payload=MealPlanCreateRequest(**plan_body(plan_date="2026-10-13")),
        )

    persisted_count = (
        db.query(MealPlan)
        .filter(MealPlan.user_id == user.id, MealPlan.plan_date == date(2026, 10, 13))
        .count()
    )
    assert persisted_count == 0


def test_solver_preview_still_does_not_persist(meal_plan_db) -> None:
    db, track_email, _ = meal_plan_db
    setup_seed_data(db)
    email = track_email(unique_email())
    token = register_and_login(email)
    create_profile(token)

    response = preview_plan(token, {})

    user = db.query(User).filter(User.email == email).one()
    assert response.status_code == 200
    assert db.query(MealPlan).filter(MealPlan.user_id == user.id).count() == 0
