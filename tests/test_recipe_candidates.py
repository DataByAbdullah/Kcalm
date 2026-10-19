import asyncio
from collections import Counter
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
from app.services.food_seed_service import seed_development_foods


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_candidate_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "user_equipment",
                "user_dietary_restrictions",
                "user_allergies",
                "user_disliked_foods",
                "user_preferred_foods",
                "foods",
                "food_nutrients",
                "recipes",
                "recipe_ingredients",
                "recipe_tags",
                "recipe_tag_links",
                "recipe_equipment",
                "recipe_nutrients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("candidate tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def candidate_db():
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


def unique_email(prefix: str = "candidates") -> str:
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


def create_profile(
    token: str,
    equipment: list[str] | None = None,
    dietary_restrictions: list[str] | None = None,
    allergies: list[str] | None = None,
    disliked_foods: list[str] | None = None,
    preferred_foods: list[str] | None = None,
    max_cooking_minutes: int = 60,
) -> None:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json={
                "age": 29,
                "sex": "male",
                "height_cm": 178,
                "weight_kg": 82,
                "activity_level": "moderate",
                "goal": "fat_loss",
                "target_rate": 0.5,
                "max_cooking_minutes": max_cooking_minutes,
                "meals_per_day": 3,
                "allergies": allergies or [],
                "dietary_restrictions": dietary_restrictions or [],
                "preferred_foods": preferred_foods or [],
                "disliked_foods": disliked_foods or [],
                "equipment": equipment or [],
            },
        )
    )
    assert response.status_code == 201, response.text


def setup_foods(db) -> None:
    seed_development_foods(db)


def food_id(db, source_food_id: str) -> str:
    food = db.query(Food).filter(Food.source_food_id == source_food_id).one()
    return str(food.id)


def recipe_payload(
    db,
    name: str,
    tags: list[str],
    equipment: list[str] | None = None,
    prep_time_minutes: int = 5,
    cook_time_minutes: int = 5,
    food_source_ids: list[str] | None = None,
) -> dict:
    source_ids = food_source_ids or ["dev_chicken_breast", "dev_cooked_rice"]
    return {
        "name": name,
        "description": "Candidate test recipe.",
        "servings": 2,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
        "difficulty": "easy",
        "ingredients": [
            {
                "food_id": food_id(db, source_id),
                "quantity_grams": 100,
                "position": index,
            }
            for index, source_id in enumerate(source_ids, start=1)
        ],
        "steps": [
            {
                "position": 1,
                "instruction": "Combine ingredients.",
                "duration_seconds": 60,
                "timer": False,
            }
        ],
        "tags": tags,
        "equipment": equipment or [],
    }


def create_recipe(db, token: str, track_recipe, **kwargs) -> dict:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/recipes",
            headers=auth_headers(token),
            json=recipe_payload(db, **kwargs),
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    track_recipe(body["id"])
    return body


def preview_candidates(token: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/recipes/candidates/preview",
            headers=auth_headers(token),
            json=body or {},
        )
    )


def candidate_by_id(body: dict, recipe_id: str) -> dict | None:
    return next(
        (item for item in body["candidates"] if item["recipe_id"] == recipe_id),
        None,
    )


def excluded_by_id(body: dict, recipe_id: str) -> dict | None:
    return next(
        (item for item in body["excluded"] if item["recipe_id"] == recipe_id),
        None,
    )


def candidate_ids(body: dict) -> set[str]:
    return {item["recipe_id"] for item in body["candidates"]}


def test_candidate_preview_requires_authentication() -> None:
    response = run_async(api_request("POST", "/api/v1/recipes/candidates/preview", json={}))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_candidate_preview_requires_saved_profile(candidate_db) -> None:
    _, _, _, track_email = candidate_db
    token = register_and_login(track_email(unique_email()))

    response = preview_candidates(token, {})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_active_recipe_included_and_archived_recipe_excluded(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, equipment=["stovetop"])
    active = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Active Candidate {uuid4().hex}",
        tags=["lunch", "quick"],
        equipment=["stovetop"],
    )
    archived = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Archived Candidate {uuid4().hex}",
        tags=["lunch", "quick"],
    )
    delete_response = run_async(
        api_request(
            "DELETE",
            f"/api/v1/recipes/{archived['id']}",
            headers=auth_headers(token),
        )
    )
    assert delete_response.status_code == 204

    response = preview_candidates(token, {"meal_type": "lunch"})

    assert response.status_code == 200
    body = response.json()
    assert candidate_by_id(body, active["id"]) is not None
    archived_exclusion = excluded_by_id(body, archived["id"])
    assert archived_exclusion is not None
    assert archived_exclusion["reasons"] == ["inactive"]


def test_meal_type_filters_breakfast_lunch_dinner_and_snack(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    breakfast = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Breakfast Candidate {uuid4().hex}",
        tags=["breakfast", "quick"],
        food_source_ids=["dev_oats", "dev_banana"],
    )
    lunch = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Lunch Candidate {uuid4().hex}",
        tags=["lunch", "quick"],
    )
    dinner = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Dinner Candidate {uuid4().hex}",
        tags=["dinner"],
    )
    snack = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Snack Candidate {uuid4().hex}",
        tags=["snack", "quick"],
        food_source_ids=["dev_banana"],
    )

    cases = {
        "breakfast": breakfast["id"],
        "lunch": lunch["id"],
        "dinner": dinner["id"],
        "snack": snack["id"],
    }
    for meal_type, expected_id in cases.items():
        response = preview_candidates(token, {"meal_type": meal_type})
        assert response.status_code == 200
        body = response.json()
        assert candidate_by_id(body, expected_id) is not None

    lunch_response = preview_candidates(token, {"meal_type": "lunch"})
    excluded_breakfast = excluded_by_id(lunch_response.json(), breakfast["id"])
    assert excluded_breakfast is not None
    assert excluded_breakfast["reasons"] == ["wrong_meal_type"]


def test_time_and_equipment_constraints(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, equipment=["stovetop"])
    fast_available = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Fast Available Candidate {uuid4().hex}",
        tags=["dinner"],
        equipment=["stovetop"],
        prep_time_minutes=5,
        cook_time_minutes=10,
    )
    no_equipment = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 No Equipment Candidate {uuid4().hex}",
        tags=["dinner"],
        equipment=[],
        prep_time_minutes=5,
        cook_time_minutes=10,
    )
    slow = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Slow Candidate {uuid4().hex}",
        tags=["dinner"],
        equipment=["stovetop"],
        prep_time_minutes=15,
        cook_time_minutes=20,
    )
    unavailable_equipment = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Blender Candidate {uuid4().hex}",
        tags=["dinner"],
        equipment=["blender"],
        prep_time_minutes=5,
        cook_time_minutes=5,
    )

    response = preview_candidates(
        token,
        {"meal_type": "dinner", "max_total_time_minutes": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert candidate_by_id(body, fast_available["id"]) is not None
    assert candidate_by_id(body, no_equipment["id"]) is not None
    assert excluded_by_id(body, slow["id"])["reasons"] == ["exceeds_time_limit"]
    assert excluded_by_id(body, unavailable_equipment["id"])["reasons"] == [
        "missing_required_equipment"
    ]


def test_profile_max_cooking_minutes_applies_when_request_omits_time(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, max_cooking_minutes=20)
    fast = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Profile Fast Candidate {uuid4().hex}",
        tags=["dinner"],
        prep_time_minutes=5,
        cook_time_minutes=10,
    )
    slow = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Profile Slow Candidate {uuid4().hex}",
        tags=["dinner"],
        prep_time_minutes=15,
        cook_time_minutes=20,
    )

    response = preview_candidates(token, {"meal_type": "dinner"})

    assert response.status_code == 200
    body = response.json()
    assert candidate_by_id(body, fast["id"]) is not None
    assert excluded_by_id(body, slow["id"])["reasons"] == ["exceeds_time_limit"]


def test_dietary_restriction_filtering_uses_explicit_tags(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, dietary_restrictions=["vegetarian"])
    vegetarian = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Vegetarian Candidate {uuid4().hex}",
        tags=["lunch", "vegetarian"],
        food_source_ids=["dev_oats", "dev_banana"],
    )
    untagged = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Untagged Meat Candidate {uuid4().hex}",
        tags=["lunch"],
    )

    response = preview_candidates(token, {"meal_type": "lunch"})

    assert response.status_code == 200
    body = response.json()
    assert candidate_by_id(body, vegetarian["id"]) is not None
    assert excluded_by_id(body, untagged["id"])["reasons"] == [
        "dietary_restriction_mismatch"
    ]


def test_explicit_recipe_exclusion_required_tag_and_excluded_tag(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    quick = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Quick Candidate {uuid4().hex}",
        tags=["snack", "quick"],
        food_source_ids=["dev_banana"],
    )
    plain = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Plain Candidate {uuid4().hex}",
        tags=["snack"],
        food_source_ids=["dev_banana"],
    )

    required_response = preview_candidates(
        token,
        {"meal_type": "snack", "required_tags": ["quick"]},
    )
    excluded_response = preview_candidates(
        token,
        {"meal_type": "snack", "excluded_tags": ["quick"]},
    )
    explicit_response = preview_candidates(
        token,
        {"excluded_recipe_ids": [quick["id"]]},
    )

    assert candidate_by_id(required_response.json(), quick["id"]) is not None
    assert excluded_by_id(required_response.json(), plain["id"])["reasons"] == [
        "missing_required_tag"
    ]
    assert excluded_by_id(excluded_response.json(), quick["id"])["reasons"] == [
        "excluded_tag"
    ]
    assert excluded_by_id(explicit_response.json(), quick["id"])["reasons"] == [
        "explicitly_excluded"
    ]


def test_nutrition_completeness_filter_strict_and_non_strict(candidate_db) -> None:
    db, track_recipe, track_food, track_email = candidate_db
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    food = Food(
        name=f"Minimal Candidate Food {uuid4().hex}",
        source=FoodSource.INTERNAL,
        source_food_id=f"minimal_candidate_{uuid4().hex}",
        category="test",
        description="Intentionally incomplete candidate food.",
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

    payload = {
        "name": f"000 Incomplete Nutrition Candidate {uuid4().hex}",
        "description": "Incomplete nutrition candidate.",
        "servings": 1,
        "prep_time_minutes": 5,
        "cook_time_minutes": 0,
        "ingredients": [{"food_id": str(food.id), "quantity_grams": 100, "position": 1}],
        "steps": [{"position": 1, "instruction": "Serve."}],
        "tags": ["snack", "quick"],
        "equipment": [],
    }
    create_response = run_async(
        api_request("POST", "/api/v1/recipes", headers=auth_headers(token), json=payload)
    )
    assert create_response.status_code == 201, create_response.text
    recipe = create_response.json()
    track_recipe(recipe["id"])

    non_strict_response = preview_candidates(
        token,
        {
            "meal_type": "snack",
            "required_nutrient_codes": ["calories", "protein"],
        },
    )
    strict_response = preview_candidates(
        token,
        {
            "meal_type": "snack",
            "require_complete_nutrition": True,
            "required_nutrient_codes": ["calories", "protein"],
        },
    )

    assert candidate_by_id(non_strict_response.json(), recipe["id"]) is not None
    strict_body = strict_response.json()
    assert excluded_by_id(strict_body, recipe["id"])["reasons"] == [
        "incomplete_nutrition"
    ]


def test_disliked_food_filtering_exact_match_and_allergy_limitation(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(
        token,
        allergies=["chicken breast"],
        disliked_foods=["Chicken Breast"],
    )
    chicken_recipe = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Disliked Chicken Candidate {uuid4().hex}",
        tags=["lunch"],
    )

    response = preview_candidates(token, {"meal_type": "lunch"})

    assert response.status_code == 200
    body = response.json()
    assert body["allergy_filtering_supported"] is False
    assert excluded_by_id(body, chicken_recipe["id"])["reasons"] == ["disliked_food"]


def test_allergy_metadata_limitation_does_not_claim_allergy_safe_filtering(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, allergies=["chicken breast"])
    chicken_recipe = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Allergy Limitation Candidate {uuid4().hex}",
        tags=["lunch"],
    )

    response = preview_candidates(token, {"meal_type": "lunch"})

    assert response.status_code == 200
    body = response.json()
    assert body["allergy_filtering_supported"] is False
    assert candidate_by_id(body, chicken_recipe["id"]) is not None


def test_preference_metadata_does_not_exclude_candidates(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, preferred_foods=["Chicken Breast"])
    chicken_recipe = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Preferred Chicken Candidate {uuid4().hex}",
        tags=["lunch"],
    )

    response = preview_candidates(token, {"meal_type": "lunch"})

    assert response.status_code == 200
    candidate = candidate_by_id(response.json(), chicken_recipe["id"])
    assert candidate is not None
    assert candidate["preference_match_count"] == 1
    assert candidate["matched_preference_food_names"] == ["Chicken Breast"]


def test_exclusion_summary_candidate_nutrition_and_deterministic_order(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, equipment=["stovetop"])
    first = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Alpha Candidate {uuid4().hex}",
        tags=["lunch", "quick"],
        equipment=["stovetop"],
    )
    second = create_recipe(
        db,
        token,
        track_recipe,
        name=f"001 Beta Candidate {uuid4().hex}",
        tags=["lunch", "quick"],
        equipment=["stovetop"],
    )
    slow = create_recipe(
        db,
        token,
        track_recipe,
        name=f"999 Slow Summary Candidate {uuid4().hex}",
        tags=["lunch"],
        equipment=["stovetop"],
        prep_time_minutes=15,
        cook_time_minutes=20,
    )

    response = preview_candidates(
        token,
        {"meal_type": "lunch", "max_total_time_minutes": 20},
    )

    assert response.status_code == 200
    body = response.json()
    ids = [item["recipe_id"] for item in body["candidates"]]
    assert len(ids) == len(set(ids))
    names = [item["name"] for item in body["candidates"]]
    assert names == sorted(names, key=str.lower)
    assert candidate_by_id(body, first["id"]) is not None
    assert candidate_by_id(body, second["id"]) is not None
    assert excluded_by_id(body, slow["id"])["reasons"] == ["exceeds_time_limit"]
    summary_from_excluded = Counter(item["reasons"][0] for item in body["excluded"])
    assert body["exclusion_summary"] == dict(summary_from_excluded)
    first_candidate = candidate_by_id(body, first["id"])
    total_nutrients = {item["code"]: item for item in first_candidate["total_nutrition"]}
    per_serving_nutrients = {
        item["code"]: item for item in first_candidate["per_serving_nutrition"]
    }
    assert total_nutrients["calories"]["amount"] == 295.0
    assert per_serving_nutrients["calories"]["amount"] == 147.5
    assert total_nutrients["protein"]["amount"] == 33.7


def test_unsupported_dietary_restriction_is_reported_not_fabricated(candidate_db) -> None:
    db, track_recipe, _, track_email = candidate_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, dietary_restrictions=["halal"])
    recipe = create_recipe(
        db,
        token,
        track_recipe,
        name=f"000 Unsupported Restriction Candidate {uuid4().hex}",
        tags=["dinner"],
    )

    response = preview_candidates(token, {"meal_type": "dinner"})

    assert response.status_code == 200
    body = response.json()
    assert "halal" in body["unsupported_dietary_restrictions"]
    assert candidate_by_id(body, recipe["id"]) is not None
