import asyncio
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.foods import get_usda_client
from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource
from app.integrations.usda import (
    USDAAuthenticationError,
    USDAFoodDataCentralClient,
    USDANotFoundError,
    USDATimeoutError,
)
from app.integrations.usda_nutrients import (
    SUPPORTED_USDA_NUTRIENT_CODES,
    convert_unit,
    normalize_usda_nutrients,
)
from app.main import app
from app.models.food import Food, FoodNutrient, FoodServing
from app.models.user import User
from app.services.usda_food_service import normalize_usda_food


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
def usda_db():
    db = SessionLocal()
    imported_fdc_ids: list[str] = []
    created_emails: list[str] = []

    def track_fdc_id(fdc_id: int) -> int:
        imported_fdc_ids.append(str(fdc_id))
        return fdc_id

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    yield db, track_fdc_id, track_email

    for fdc_id in imported_fdc_ids:
        food = (
            db.query(Food)
            .filter(Food.source == FoodSource.USDA, Food.source_food_id == fdc_id)
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
    app.dependency_overrides.pop(get_usda_client, None)


def unique_email(prefix: str = "usda") -> str:
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


def usda_food_payload(fdc_id: int = 234567) -> dict:
    return {
        "fdcId": fdc_id,
        "description": "chicken breast, cooked",
        "dataType": "Foundation",
        "foodCategory": {"description": "Poultry Products"},
        "foodNutrients": [
            nutrient(1008, "Energy", "KCAL", 165),
            nutrient(1003, "Protein", "G", 31),
            nutrient(1005, "Carbohydrate, by difference", "G", 0),
            nutrient(1004, "Total lipid (fat)", "G", 3.6),
            nutrient(1079, "Fiber, total dietary", "G", 0),
            nutrient(1087, "Calcium, Ca", "MG", 15),
            nutrient(1089, "Iron, Fe", "MG", 1),
            nutrient(1090, "Magnesium, Mg", "MG", 29),
            nutrient(1092, "Potassium, K", "MG", 256),
            nutrient(1093, "Sodium, Na", "MG", 74),
            nutrient(1106, "Vitamin A, RAE", "UG", 13),
            nutrient(1162, "Vitamin C, total ascorbic acid", "MG", 0),
            nutrient(1114, "Vitamin D (D2 + D3)", "UG", 0.3),
            nutrient(1178, "Vitamin B-12", "UG", 0.3),
            nutrient(1190, "Folate, DFE", "UG", 4),
        ],
        "foodPortions": [
            {"amount": 1, "measureUnit": {"name": "cup"}, "gramWeight": 140},
            {"portionDescription": "1 piece", "gramWeight": 120},
        ],
    }


def nutrient(nutrient_id: int, name: str, unit: str, amount: float) -> dict:
    return {
        "nutrient": {
            "id": nutrient_id,
            "name": name,
            "unitName": unit,
        },
        "amount": amount,
    }


class FakeUSDAClient:
    def __init__(
        self,
        search_payload: dict | None = None,
        food_payload: dict | None = None,
    ) -> None:
        self.search_payload = search_payload
        self.food_payload = food_payload
        self.fetch_count = 0

    def search_foods(self, query: str, page_size: int, page_number: int) -> dict:
        return self.search_payload or {"foods": [], "totalHits": 0}

    def get_food(self, fdc_id: int) -> dict:
        self.fetch_count += 1
        return self.food_payload or usda_food_payload(fdc_id)


def override_usda_client(client) -> None:
    app.dependency_overrides[get_usda_client] = lambda: client


def mock_client(handler) -> USDAFoodDataCentralClient:
    return USDAFoodDataCentralClient(
        api_key="test-usda-key",
        base_url="https://example.test/fdc/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_usda_search_success(usda_db) -> None:
    _, _, track_email = usda_db
    token = register_and_login(track_email(unique_email()))
    override_usda_client(
        FakeUSDAClient(
            search_payload={
                "foods": [
                    {
                        "fdcId": 234567,
                        "description": "Chicken breast, cooked",
                        "dataType": "Foundation",
                        "brandOwner": "Example Brand",
                    }
                ],
                "totalHits": 1,
            }
        )
    )

    response = run_async(
        api_request(
            "GET",
            "/api/v1/foods/usda/search?q=chicken&page_size=10&page=1",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0] == {
        "fdc_id": 234567,
        "description": "Chicken breast, cooked",
        "data_type": "Foundation",
        "brand_owner": "Example Brand",
    }


def test_usda_search_empty(usda_db) -> None:
    _, _, track_email = usda_db
    token = register_and_login(track_email(unique_email()))
    override_usda_client(FakeUSDAClient(search_payload={"foods": [], "totalHits": 0}))

    response = run_async(
        api_request(
            "GET",
            "/api/v1/foods/usda/search?q=definitelynotfood",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_usda_timeout() -> None:
    def handler(request):
        raise httpx.TimeoutException("timeout", request=request)

    client = mock_client(handler)

    with pytest.raises(USDATimeoutError):
        client.search_foods(query="chicken", page_size=10, page_number=1)

    client.http_client.close()


def test_usda_invalid_api_key_upstream_auth_error() -> None:
    client = mock_client(lambda request: httpx.Response(403, json={"error": "forbidden"}))

    with pytest.raises(USDAAuthenticationError):
        client.search_foods(query="chicken", page_size=10, page_number=1)

    client.http_client.close()


def test_usda_food_fetch_success() -> None:
    payload = usda_food_payload(345678)
    client = mock_client(lambda request: httpx.Response(200, json=payload))

    response = client.get_food(345678)

    assert response["fdcId"] == 345678
    assert response["description"] == "chicken breast, cooked"
    client.http_client.close()


def test_usda_food_not_found() -> None:
    client = mock_client(lambda request: httpx.Response(404, json={"error": "missing"}))

    with pytest.raises(USDANotFoundError):
        client.get_food(999999)

    client.http_client.close()


def test_usda_nutrient_mapping() -> None:
    normalized = normalize_usda_nutrients(usda_food_payload())

    assert tuple(item["code"] for item in normalized) == SUPPORTED_USDA_NUTRIENT_CODES
    nutrients = {item["code"]: item for item in normalized}
    assert nutrients["calories"] == {
        "code": "calories",
        "name": "Calories",
        "amount": 165,
        "unit": "kcal",
    }
    assert nutrients["vitamin_a"]["unit"] == "mcg RAE"
    assert nutrients["folate"]["unit"] == "mcg DFE"


def test_usda_unit_conversion() -> None:
    assert convert_unit(amount=1000, source_unit="MG", target_unit="g") == 1
    assert convert_unit(amount=1, source_unit="G", target_unit="mg") == 1000
    assert convert_unit(amount=13, source_unit="UG", target_unit="mcg RAE") == 13
    assert convert_unit(amount=418.4, source_unit="KJ", target_unit="kcal") == pytest.approx(100, rel=0.001)
    assert convert_unit(amount=1, source_unit="IU", target_unit="mcg") is None


def test_usda_per_100g_normalization_uses_food_nutrients_without_serving_scaling() -> None:
    payload = usda_food_payload()
    payload["servingSize"] = 50
    payload["servingSizeUnit"] = "g"
    normalized = normalize_usda_food(payload)
    nutrients = {item["code"]: item for item in normalized["nutrients"]}

    assert nutrients["calories"]["amount"] == 165
    assert {"name": "50 g", "grams": 50.0} in normalized["servings"]


def test_usda_import_persists_food(usda_db) -> None:
    db, track_fdc_id, track_email = usda_db
    fdc_id = track_fdc_id(456001)
    token = register_and_login(track_email(unique_email()))
    override_usda_client(FakeUSDAClient(food_payload=usda_food_payload(fdc_id)))

    response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 201
    assert response.json()["status"] == "imported"
    food = (
        db.query(Food)
        .filter(Food.source == FoodSource.USDA, Food.source_food_id == str(fdc_id))
        .one()
    )
    assert food.name == "Chicken Breast, Cooked"
    assert food.category == "poultry_products"


def test_usda_import_persists_nutrients(usda_db) -> None:
    db, track_fdc_id, track_email = usda_db
    fdc_id = track_fdc_id(456002)
    token = register_and_login(track_email(unique_email()))
    override_usda_client(FakeUSDAClient(food_payload=usda_food_payload(fdc_id)))

    response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 201
    food = (
        db.query(Food)
        .filter(Food.source == FoodSource.USDA, Food.source_food_id == str(fdc_id))
        .one()
    )
    nutrients = {
        nutrient.nutrient_code: nutrient
        for nutrient in db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).all()
    }
    assert nutrients["protein"].amount == 31
    assert nutrients["vitamin_d"].unit == "mcg"
    assert len(nutrients) == len(SUPPORTED_USDA_NUTRIENT_CODES)


def test_usda_import_persists_servings(usda_db) -> None:
    db, track_fdc_id, track_email = usda_db
    fdc_id = track_fdc_id(456003)
    token = register_and_login(track_email(unique_email()))
    override_usda_client(FakeUSDAClient(food_payload=usda_food_payload(fdc_id)))

    response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 201
    food = (
        db.query(Food)
        .filter(Food.source == FoodSource.USDA, Food.source_food_id == str(fdc_id))
        .one()
    )
    servings = {
        serving.serving_name: serving.grams
        for serving in db.query(FoodServing).filter(FoodServing.food_id == food.id).all()
    }
    assert servings == {
        "100 g": 100.0,
        "1 cup": 140.0,
        "1 piece": 120.0,
    }


def test_usda_duplicate_import_does_not_duplicate_rows(usda_db) -> None:
    db, track_fdc_id, track_email = usda_db
    fdc_id = track_fdc_id(456004)
    token = register_and_login(track_email(unique_email()))
    fake_client = FakeUSDAClient(food_payload=usda_food_payload(fdc_id))
    override_usda_client(fake_client)

    first_response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )
    second_response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "existing"
    assert fake_client.fetch_count == 1
    assert (
        db.query(Food)
        .filter(Food.source == FoodSource.USDA, Food.source_food_id == str(fdc_id))
        .count()
    ) == 1
    food = (
        db.query(Food)
        .filter(Food.source == FoodSource.USDA, Food.source_food_id == str(fdc_id))
        .one()
    )
    assert db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).count() == len(
        SUPPORTED_USDA_NUTRIENT_CODES
    )


def test_usda_malformed_payload_returns_controlled_error(usda_db) -> None:
    _, track_fdc_id, track_email = usda_db
    fdc_id = track_fdc_id(456005)
    token = register_and_login(track_email(unique_email()))
    override_usda_client(FakeUSDAClient(food_payload={"fdcId": fdc_id, "description": "Bad food"}))

    response = run_async(
        api_request(
            "POST",
            f"/api/v1/foods/usda/import/{fdc_id}",
            headers=auth_headers(token),
        )
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "USDA_MALFORMED_RESPONSE"


def test_usda_endpoints_require_authentication() -> None:
    search_response = run_async(api_request("GET", "/api/v1/foods/usda/search?q=chicken"))
    import_response = run_async(api_request("POST", "/api/v1/foods/usda/import/456006"))

    assert search_response.status_code == 401
    assert search_response.json()["error"]["code"] == "INVALID_TOKEN"
    assert import_response.status_code == 401
    assert import_response.json()["error"]["code"] == "INVALID_TOKEN"
