import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.main import app
from app.models.food import Food, FoodNutrient
from app.models.recipe import Recipe
from app.models.user import User
from app.seed_data.recipes import DEV_RECIPE_SEED_DATA, DEV_RECIPE_SEED_SOURCE
from app.services.food_seed_service import seed_development_foods
from app.services.recipe_seed_service import seed_development_recipes


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_recipe_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "foods",
                "food_nutrients",
                "recipes",
                "recipe_ingredients",
                "recipe_steps",
                "recipe_tags",
                "recipe_tag_links",
                "recipe_equipment",
                "recipe_nutrients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("recipe tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def recipe_db():
    db = SessionLocal()
    created_recipe_ids: list[UUID] = []
    created_food_ids: list[UUID] = []
    created_emails: list[str] = []

    def track_recipe(recipe_id: str | UUID) -> UUID:
        parsed_id = UUID(str(recipe_id))
        created_recipe_ids.append(parsed_id)
        return parsed_id

    def track_food(food_id: UUID) -> UUID:
        created_food_ids.append(food_id)
        return food_id

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    yield db, track_recipe, track_food, track_email

    for recipe_id in created_recipe_ids:
        recipe = db.get(Recipe, recipe_id)
        if recipe is not None:
            db.delete(recipe)
    db.commit()

    for food_id in created_food_ids:
        food = db.get(Food, food_id)
        if food is not None:
            db.delete(food)

    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)

    db.commit()
    db.close()


def unique_email(prefix: str = "recipes") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


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


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def food_id(db, source_food_id: str) -> str:
    food = db.query(Food).filter(Food.source_food_id == source_food_id).one()
    return str(food.id)


def recipe_payload(db, name: str | None = None) -> dict:
    return {
        "name": name or f"Recipe Test Bowl {uuid4().hex}",
        "description": "Test recipe.",
        "servings": 2,
        "prep_time_minutes": 5,
        "cook_time_minutes": 10,
        "difficulty": "easy",
        "instructions_summary": "Combine ingredients.",
        "ingredients": [
            {
                "food_id": food_id(db, "dev_chicken_breast"),
                "quantity_grams": 100,
                "display_quantity": "100",
                "display_unit": "g",
                "preparation_note": "cooked",
                "position": 1,
            },
            {
                "food_id": food_id(db, "dev_cooked_rice"),
                "quantity_grams": 100,
                "display_quantity": "100",
                "display_unit": "g",
                "preparation_note": "cooked",
                "position": 2,
            },
        ],
        "steps": [
            {
                "position": 1,
                "instruction": "Warm the chicken.",
                "duration_seconds": 120,
                "timer": True,
            },
            {
                "position": 2,
                "instruction": "Serve over rice.",
                "duration_seconds": 60,
                "timer": False,
            },
        ],
        "tags": ["lunch", "quick", "high_protein"],
        "equipment": ["stovetop"],
    }


def create_recipe_via_api(db, token: str, track_recipe, payload: dict | None = None) -> dict:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/recipes",
            headers=auth_headers(token),
            json=payload or recipe_payload(db),
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    track_recipe(body["id"])
    return body


def setup_seed_foods(db) -> None:
    seed_development_foods(db)


def nutrient(body: dict, scope: str, code: str) -> dict:
    return {item["code"]: item for item in body["nutrition"][scope]}[code]


def test_create_recipe_success(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))

    body = create_recipe_via_api(db, token, track_recipe)

    assert body["servings"] == 2.0
    assert body["total_time_minutes"] == 15
    assert body["tags"] == ["high_protein", "lunch", "quick"]
    assert body["equipment"] == ["stovetop"]


def test_recipe_endpoints_require_authentication(recipe_db) -> None:
    db, _, _, _ = recipe_db
    setup_seed_foods(db)

    list_response = run_async(api_request("GET", "/api/v1/recipes"))
    create_response = run_async(api_request("POST", "/api/v1/recipes", json=recipe_payload(db)))

    assert list_response.status_code == 401
    assert create_response.status_code == 401
    assert list_response.json()["error"]["code"] == "INVALID_TOKEN"


def test_invalid_food_id_rejected(recipe_db) -> None:
    db, _, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    payload = recipe_payload(db)
    payload["ingredients"][0]["food_id"] = str(uuid4())

    response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=payload)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RECIPE_FOOD"


def test_zero_and_negative_ingredient_grams_rejected(recipe_db) -> None:
    db, _, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))

    zero_payload = recipe_payload(db)
    zero_payload["ingredients"][0]["quantity_grams"] = 0
    negative_payload = recipe_payload(db)
    negative_payload["ingredients"][0]["quantity_grams"] = -1

    zero_response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=zero_payload)
    )
    negative_response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=negative_payload)
    )

    assert zero_response.status_code == 422
    assert negative_response.status_code == 422


def test_servings_validation(recipe_db) -> None:
    db, _, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    payload = recipe_payload(db)
    payload["servings"] = 0

    response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=payload)
    )

    assert response.status_code == 422


def test_recipe_child_records_persist(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))

    body = create_recipe_via_api(db, token, track_recipe)

    assert len(body["ingredients"]) == 2
    assert body["ingredients"][0]["food_name"] == "Chicken Breast"
    assert body["ingredients"][0]["quantity_grams"] == 100.0
    assert len(body["steps"]) == 2
    assert body["steps"][0]["position"] == 1
    assert body["steps"][1]["position"] == 2
    assert "quick" in body["tags"]
    assert body["equipment"] == ["stovetop"]


def test_duplicate_step_position_rejected(recipe_db) -> None:
    db, _, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    payload = recipe_payload(db)
    payload["steps"][1]["position"] = 1

    response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=payload)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DUPLICATE_RECIPE_STEP_POSITION"


def test_recipe_total_and_per_serving_nutrition_calculation(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))

    body = create_recipe_via_api(db, token, track_recipe)

    assert nutrient(body, "total", "calories")["amount"] == 295.0
    assert nutrient(body, "per_serving", "calories")["amount"] == 147.5
    assert nutrient(body, "total", "protein")["amount"] == 33.7
    assert nutrient(body, "total", "carbohydrates")["amount"] == 28.0
    assert nutrient(body, "total", "fat")["amount"] == 3.9
    assert nutrient(body, "total", "calcium")["amount"] == 25.0
    assert nutrient(body, "total", "calories")["unit"] == "kcal"
    assert nutrient(body, "total", "protein")["unit"] == "g"
    assert nutrient(body, "total", "calcium")["unit"] == "mg"
    assert nutrient(body, "total", "vitamin_a")["unit"] == "mcg RAE"


def test_missing_nutrient_behavior(recipe_db) -> None:
    db, track_recipe, track_food, track_email = recipe_db
    token = register_and_login(track_email(unique_email()))
    food = Food(
        name="Minimal Food",
        source=FoodSource.INTERNAL,
        source_food_id=f"minimal_{uuid4().hex}",
        category="test",
        description="Food with intentionally incomplete nutrients.",
    )
    db.add(food)
    db.flush()
    track_food(food.id)
    db.add(
        FoodNutrient(
            food_id=food.id,
            nutrient_code="calories",
            nutrient_name="Calories",
            amount=100,
            unit="kcal",
        )
    )
    db.commit()
    payload = recipe_payload_with_one_food(str(food.id))

    response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=payload)
    )

    assert response.status_code == 201
    body = response.json()
    track_recipe(body["id"])
    fiber = nutrient(body, "total", "fiber")
    assert fiber["amount"] == 0.0
    assert fiber["complete"] is False
    assert fiber["missing_ingredient_count"] == 1


def recipe_payload_with_one_food(food_id_value: str) -> dict:
    return {
        "name": f"Minimal Recipe {uuid4().hex}",
        "description": "Missing nutrient test.",
        "servings": 1,
        "prep_time_minutes": 2,
        "cook_time_minutes": 0,
        "ingredients": [
            {
                "food_id": food_id_value,
                "quantity_grams": 50,
                "position": 1,
            }
        ],
        "steps": [{"position": 1, "instruction": "Serve.", "duration_seconds": 0}],
        "tags": ["snack", "quick"],
        "equipment": [],
    }


def test_update_ingredient_recalculates_nutrition(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    body = create_recipe_via_api(db, token, track_recipe)

    payload = {
        "ingredients": [
            {
                "food_id": food_id(db, "dev_chicken_breast"),
                "quantity_grams": 200,
                "position": 1,
            },
            {
                "food_id": food_id(db, "dev_cooked_rice"),
                "quantity_grams": 100,
                "position": 2,
            },
        ]
    }
    response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{body['id']}",
            headers=auth_headers(token),
            json=payload,
        )
    )

    assert response.status_code == 200
    updated = response.json()
    assert nutrient(updated, "total", "calories")["amount"] == 460.0
    assert nutrient(updated, "total", "protein")["amount"] == 64.7


def test_update_serving_count_changes_per_serving_nutrition(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    body = create_recipe_via_api(db, token, track_recipe)

    response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{body['id']}",
            headers=auth_headers(token),
            json={"servings": 4},
        )
    )

    assert response.status_code == 200
    updated = response.json()
    assert nutrient(updated, "total", "calories")["amount"] == 295.0
    assert nutrient(updated, "per_serving", "calories")["amount"] == 73.75


def test_recipe_list_search_tag_filter_max_time_and_detail(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    unique_name = f"Chicken Searchable {uuid4().hex}"
    body = create_recipe_via_api(db, token, track_recipe, recipe_payload(db, name=unique_name))

    list_response = run_async(api_request("GET", "/api/v1/recipes", headers=auth_headers(token)))
    search_response = run_async(
        api_request("GET", f"/api/v1/recipes?search={unique_name}", headers=auth_headers(token))
    )
    tag_response = run_async(api_request("GET", "/api/v1/recipes?tag=quick", headers=auth_headers(token)))
    time_response = run_async(
        api_request("GET", "/api/v1/recipes?max_total_time_minutes=20", headers=auth_headers(token))
    )
    detail_response = run_async(
        api_request("GET", f"/api/v1/recipes/{body['id']}", headers=auth_headers(token))
    )

    assert list_response.status_code == 200
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 1
    assert search_response.json()["items"][0]["name"] == unique_name
    assert tag_response.status_code == 200
    assert any(item["id"] == body["id"] for item in tag_response.json()["items"])
    assert time_response.status_code == 200
    assert any(item["id"] == body["id"] for item in time_response.json()["items"])
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == body["id"]


def test_quick_recipe_time_rule(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    accepted_payload = recipe_payload(db)
    accepted_payload["prep_time_minutes"] = 10
    accepted_payload["cook_time_minutes"] = 10
    rejected_payload = recipe_payload(db)
    rejected_payload["prep_time_minutes"] = 10
    rejected_payload["cook_time_minutes"] = 11

    accepted_response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=accepted_payload)
    )
    rejected_response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=rejected_payload)
    )

    assert accepted_response.status_code == 201
    track_recipe(accepted_response.json()["id"])
    assert rejected_response.status_code == 422
    assert rejected_response.json()["error"]["code"] == "QUICK_RECIPE_TOO_LONG"


def test_transactional_rollback_on_failed_recipe_update(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    body = create_recipe_via_api(db, token, track_recipe)

    response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{body['id']}",
            headers=auth_headers(token),
            json={
                "name": "Should Not Persist",
                "steps": [
                    {"position": 1, "instruction": "First."},
                    {"position": 1, "instruction": "Duplicate."},
                ],
            },
        )
    )
    detail_response = run_async(
        api_request("GET", f"/api/v1/recipes/{body['id']}", headers=auth_headers(token))
    )

    assert response.status_code == 422
    assert detail_response.json()["name"] == body["name"]


def test_delete_archives_recipe(recipe_db) -> None:
    db, track_recipe, _, track_email = recipe_db
    setup_seed_foods(db)
    token = register_and_login(track_email(unique_email()))
    body = create_recipe_via_api(db, token, track_recipe)

    delete_response = run_async(
        api_request("DELETE", f"/api/v1/recipes/{body['id']}", headers=auth_headers(token))
    )
    detail_response = run_async(
        api_request("GET", f"/api/v1/recipes/{body['id']}", headers=auth_headers(token))
    )

    assert delete_response.status_code == 204
    assert detail_response.status_code == 404


def test_development_recipe_seed_data_is_idempotent(recipe_db) -> None:
    db, _, _, _ = recipe_db

    first_result = seed_development_recipes(db)
    second_result = seed_development_recipes(db)
    seeded_count = (
        db.query(Recipe)
        .filter(Recipe.source == DEV_RECIPE_SEED_SOURCE, Recipe.active.is_(True))
        .count()
    )

    assert first_result.total == len(DEV_RECIPE_SEED_DATA)
    assert second_result.total == len(DEV_RECIPE_SEED_DATA)
    assert seeded_count >= len(DEV_RECIPE_SEED_DATA)
