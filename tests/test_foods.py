import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.main import app
from app.models.food import Food, FoodNutrient, FoodServing
from app.models.user import User
from app.seed_data.foods import DEV_FOOD_SEED_DATA
from app.services.food_seed_service import seed_development_foods


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_food_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {"users", "foods", "food_nutrients", "food_servings"}
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("food tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def food_db():
    db = SessionLocal()
    created_source_food_ids: list[str] = []
    created_emails: list[str] = []

    def track_food(source_food_id: str) -> str:
        created_source_food_ids.append(source_food_id)
        return source_food_id

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    yield db, track_food, track_email

    for source_food_id in created_source_food_ids:
        food = (
            db.query(Food)
            .filter(Food.source == FoodSource.INTERNAL, Food.source_food_id == source_food_id)
            .one_or_none()
        )
        if food is not None:
            db.delete(food)

    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)

    db.commit()
    db.close()


def unique_email(prefix: str = "foods") -> str:
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


def create_test_food(
    db,
    source_food_id: str,
    name: str = "Test Food",
    category: str = "test",
) -> Food:
    food = Food(
        name=name,
        source=FoodSource.INTERNAL,
        source_food_id=source_food_id,
        category=category,
        description="Test fixture food.",
    )
    db.add(food)
    db.flush()
    return food


def test_food_persists(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")

    food = create_test_food(db, source_food_id, name="Persistence Food")
    db.commit()

    persisted = db.get(Food, food.id)
    assert persisted is not None
    assert persisted.name == "Persistence Food"
    assert persisted.source == FoodSource.INTERNAL


def test_nutrient_records_persist(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")
    food = create_test_food(db, source_food_id)
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

    persisted = db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).one()
    assert persisted.nutrient_code == "calories"
    assert persisted.amount == 100


def test_serving_records_persist(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")
    food = create_test_food(db, source_food_id)
    db.add(FoodServing(food_id=food.id, serving_name="1 piece", grams=42))
    db.commit()

    persisted = db.query(FoodServing).filter(FoodServing.food_id == food.id).one()
    assert persisted.serving_name == "1 piece"
    assert persisted.grams == 42


def test_duplicate_nutrient_code_per_food_is_rejected(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")
    food = create_test_food(db, source_food_id)
    db.add_all(
        [
            FoodNutrient(
                food_id=food.id,
                nutrient_code="protein",
                nutrient_name="Protein",
                amount=10,
                unit="g",
            ),
            FoodNutrient(
                food_id=food.id,
                nutrient_code="protein",
                nutrient_name="Protein",
                amount=11,
                unit="g",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_nutrient_amount_is_rejected(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")
    food = create_test_food(db, source_food_id)
    db.add(
        FoodNutrient(
            food_id=food.id,
            nutrient_code="calories",
            nutrient_name="Calories",
            amount=-1,
            unit="kcal",
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_serving_grams_is_rejected(food_db) -> None:
    db, track_food, _ = food_db
    source_food_id = track_food(f"test_food_{uuid4().hex}")
    food = create_test_food(db, source_food_id)
    db.add(FoodServing(food_id=food.id, serving_name="bad serving", grams=0))

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_seed_operation_is_idempotent(food_db) -> None:
    db, _, _ = food_db

    seed_development_foods(db)
    first_seed_count = (
        db.query(Food)
        .filter(
            Food.source == FoodSource.INTERNAL,
            Food.source_food_id.in_([item["source_food_id"] for item in DEV_FOOD_SEED_DATA]),
        )
        .count()
    )
    second_result = seed_development_foods(db)
    second_seed_count = (
        db.query(Food)
        .filter(
            Food.source == FoodSource.INTERNAL,
            Food.source_food_id.in_([item["source_food_id"] for item in DEV_FOOD_SEED_DATA]),
        )
        .count()
    )

    assert first_seed_count == len(DEV_FOOD_SEED_DATA)
    assert second_seed_count == len(DEV_FOOD_SEED_DATA)
    assert second_result.total == len(DEV_FOOD_SEED_DATA)
    chicken = (
        db.query(Food)
        .filter(Food.source_food_id == "dev_chicken_breast")
        .one()
    )
    assert len(chicken.nutrients) == len(DEV_FOOD_SEED_DATA[0]["nutrients"])


def test_list_foods(food_db) -> None:
    db, _, track_email = food_db
    seed_development_foods(db)
    email = track_email(unique_email())
    token = register_and_login(email)

    response = run_async(api_request("GET", "/api/v1/foods", headers=auth_headers(token)))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= len(DEV_FOOD_SEED_DATA)
    assert body["items"]
    assert set(body["items"][0]) == {"id", "name", "category", "source"}


def test_food_search_by_name(food_db) -> None:
    db, _, track_email = food_db
    seed_development_foods(db)
    token = register_and_login(track_email(unique_email()))

    response = run_async(
        api_request(
            "GET",
            "/api/v1/foods?search=chicken",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Chicken Breast"


def test_food_category_filter(food_db) -> None:
    db, _, track_email = food_db
    seed_development_foods(db)
    token = register_and_login(track_email(unique_email()))

    response = run_async(
        api_request(
            "GET",
            "/api/v1/foods?category=protein",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {item["name"] for item in body["items"]} == {"Chicken Breast", "Egg", "Salmon"}


def test_food_pagination(food_db) -> None:
    db, _, track_email = food_db
    seed_development_foods(db)
    token = register_and_login(track_email(unique_email()))

    response = run_async(
        api_request(
            "GET",
            "/api/v1/foods?limit=2&offset=1",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2
    assert body["total"] >= len(DEV_FOOD_SEED_DATA)


def test_food_detail(food_db) -> None:
    db, _, track_email = food_db
    seed_development_foods(db)
    token = register_and_login(track_email(unique_email()))
    chicken = db.query(Food).filter(Food.source_food_id == "dev_chicken_breast").one()

    response = run_async(
        api_request(
            "GET",
            f"/api/v1/foods/{chicken.id}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Chicken Breast"
    assert body["category"] == "protein"
    assert body["source"] == "internal"
    nutrients = {item["code"]: item for item in body["nutrients_per_100g"]}
    assert nutrients["calories"]["amount"] == 165
    assert nutrients["protein"]["unit"] == "g"
    assert {"name": "100 g", "grams": 100.0} in body["servings"]


def test_unknown_food_returns_404(food_db) -> None:
    _, _, track_email = food_db
    token = register_and_login(track_email(unique_email()))

    response = run_async(
        api_request(
            "GET",
            f"/api/v1/foods/{uuid4()}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FOOD_NOT_FOUND"


def test_food_endpoints_require_authentication() -> None:
    response = run_async(api_request("GET", "/api/v1/foods"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
