import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.main import app
from app.models.food import Food
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
def require_swap_tables():
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
                pytest.skip("meal swap tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def swap_db():
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


def unique_email(prefix: str = "swap") -> str:
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


def update_profile(token: str, body: dict) -> None:
    response = run_async(
        api_request(
            "PATCH",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=body,
        )
    )
    assert response.status_code == 200, response.text


def setup_foods(db) -> None:
    seed_development_foods(db)


def food_id(db, source_food_id: str) -> str:
    db.expire_all()
    food = db.query(Food).filter(Food.source_food_id == source_food_id).one()
    return str(food.id)


def recipe_payload(
    db,
    name: str,
    tags: list[str],
    food_source_ids: list[str],
    equipment: list[str] | None = None,
    prep_time_minutes: int = 5,
    cook_time_minutes: int = 5,
) -> dict:
    return {
        "name": name,
        "description": "Meal swap test recipe.",
        "servings": 1,
        "prep_time_minutes": prep_time_minutes,
        "cook_time_minutes": cook_time_minutes,
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


def create_recipe(
    db,
    token: str,
    track_recipe,
    name: str,
    tags: list[str],
    food_source_ids: list[str],
    equipment: list[str] | None = None,
    prep_time_minutes: int = 5,
    cook_time_minutes: int = 5,
) -> dict:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/recipes",
            headers=auth_headers(token),
            json=recipe_payload(
                db,
                name=name,
                tags=tags,
                food_source_ids=food_source_ids,
                equipment=equipment,
                prep_time_minutes=prep_time_minutes,
                cook_time_minutes=cook_time_minutes,
            ),
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    track_recipe(body["id"])
    return body


def active_recipe_ids_except(db, keep_ids: set[str]) -> list[str]:
    db.expire_all()
    return [
        str(recipe.id)
        for recipe in db.query(Recipe).filter(Recipe.active.is_(True)).all()
        if str(recipe.id) not in keep_ids
    ]


def plan_body(db, selected_ids: set[str], plan_date: str = "2026-10-05") -> dict:
    return {
        "plan_date": plan_date,
        "meal_slots": [
            {"meal_type": "breakfast", "required": True},
            {"meal_type": "lunch", "required": True},
            {"meal_type": "dinner", "required": True},
        ],
        "max_total_time_minutes": 60,
        "require_complete_nutrition": True,
        "required_nutrient_codes": [],
        "excluded_recipe_ids": active_recipe_ids_except(db, selected_ids),
        "required_tags": [],
        "excluded_tags": [],
        "solver_time_limit_seconds": 3,
    }


def create_plan(token: str, body: dict):
    return run_async(
        api_request(
            "POST",
            "/api/v1/meal-plans",
            headers=auth_headers(token),
            json=body,
        )
    )


def get_plan(token: str, meal_plan_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/meal-plans/{meal_plan_id}",
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


def swap_item(token: str, meal_plan_id: str, item_id: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{meal_plan_id}/items/{item_id}/swap",
            headers=auth_headers(token),
            json=body if body is not None else {},
        )
    )


def create_standard_plan(
    db,
    token: str,
    track_recipe,
    plan_date: str = "2026-10-05",
) -> tuple[dict, dict[str, dict]]:
    suffix = uuid4().hex
    recipes = {
        "breakfast": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Swap Original Breakfast {suffix}",
            tags=["breakfast", "quick", "vegetarian"],
            food_source_ids=["dev_oats", "dev_banana"],
        ),
        "lunch": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Swap Original Lunch {suffix}",
            tags=["lunch", "quick", "high_protein"],
            food_source_ids=["dev_chicken_breast", "dev_cooked_rice"],
        ),
        "dinner": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Swap Original Dinner {suffix}",
            tags=["dinner", "high_protein"],
            food_source_ids=["dev_salmon", "dev_potato"],
        ),
    }
    selected_ids = {recipe["id"] for recipe in recipes.values()}
    response = create_plan(token, plan_body(db, selected_ids, plan_date=plan_date))
    assert response.status_code == 201, response.text
    return response.json(), recipes


def meal_by_type(plan: dict, meal_type: str) -> dict:
    return next(meal for meal in plan["meals"] if meal["meal_type"] == meal_type)


def totals_match_meals(plan: dict) -> None:
    for nutrient_code, total in plan["daily_totals"].items():
        expected = sum(meal["nutrition"].get(nutrient_code, 0) for meal in plan["meals"])
        assert total == pytest.approx(expected)


def assert_deviation_and_coverage_recalculated(plan: dict) -> None:
    totals = plan["daily_totals"]
    for deviation in plan["deviations"]:
        code = deviation["nutrient_code"]
        assert deviation["actual"] == pytest.approx(totals[code])
    for coverage in plan["micronutrient_coverage"]:
        code = coverage["nutrient_code"]
        assert coverage["actual"] == pytest.approx(totals[code])


def test_swap_endpoint_requires_authentication() -> None:
    response = run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{uuid4()}/items/{uuid4()}/swap",
            json={},
        )
    )

    assert response.status_code == 401


def test_successful_lunch_swap_preserves_locked_snapshots_and_recalculates(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, original_recipes = create_standard_plan(db, token, track_recipe)
    original_targets = plan["targets"]
    original_breakfast = meal_by_type(plan, "breakfast")
    original_dinner = meal_by_type(plan, "dinner")
    original_lunch = meal_by_type(plan, "lunch")
    alternative = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Swap Alt Lunch {uuid4().hex}",
        tags=["lunch", "quick", "high_protein"],
        food_source_ids=["dev_salmon", "dev_potato"],
    )

    response = swap_item(
        token,
        plan["meal_plan_id"],
        original_lunch["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {alternative["id"]})},
    )

    assert response.status_code == 200, response.text
    swapped = response.json()
    swapped_lunch = meal_by_type(swapped, "lunch")
    assert swapped_lunch["recipe_id"] == alternative["id"]
    assert swapped_lunch["recipe_id"] != original_recipes["lunch"]["id"]
    assert meal_by_type(swapped, "breakfast") == original_breakfast
    assert meal_by_type(swapped, "dinner") == original_dinner
    assert swapped["targets"] == original_targets
    assert swapped["daily_totals"] != plan["daily_totals"]
    totals_match_meals(swapped)
    assert_deviation_and_coverage_recalculated(swapped)


def test_breakfast_and_dinner_swaps_preserve_meal_type(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-06")
    breakfast_alt = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Swap Alt Breakfast {uuid4().hex}",
        tags=["breakfast", "quick", "vegetarian"],
        food_source_ids=["dev_greek_yogurt", "dev_banana"],
    )
    breakfast_response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "breakfast")["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {breakfast_alt["id"]})},
    )
    assert breakfast_response.status_code == 200, breakfast_response.text
    breakfast_swapped = meal_by_type(breakfast_response.json(), "breakfast")
    assert breakfast_swapped["recipe_id"] == breakfast_alt["id"]
    assert breakfast_swapped["meal_type"] == "breakfast"

    dinner_alt = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Swap Alt Dinner {uuid4().hex}",
        tags=["dinner", "high_protein"],
        food_source_ids=["dev_chicken_breast", "dev_broccoli"],
    )
    dinner_response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(breakfast_response.json(), "dinner")["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {dinner_alt["id"]})},
    )
    assert dinner_response.status_code == 200, dinner_response.text
    dinner_swapped = meal_by_type(dinner_response.json(), "dinner")
    assert dinner_swapped["recipe_id"] == dinner_alt["id"]
    assert dinner_swapped["meal_type"] == "dinner"


def test_swap_candidate_filtering_constraints_are_honored(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, equipment=["stovetop"])
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-07")
    allowed = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Allowed Quick Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_egg", "dev_potato"],
    )
    slow = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Slow Lunch {uuid4().hex}",
        tags=["lunch"],
        food_source_ids=["dev_chicken_breast", "dev_potato"],
        prep_time_minutes=15,
        cook_time_minutes=20,
    )
    unavailable_equipment = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Air Fryer Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_chicken_breast", "dev_broccoli"],
        equipment=["air_fryer"],
    )
    excluded_tag = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Gluten Free Lunch {uuid4().hex}",
        tags=["lunch", "quick", "gluten_free"],
        food_source_ids=["dev_oats", "dev_banana"],
    )
    explicitly_excluded = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Explicitly Excluded Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_salmon", "dev_potato"],
    )
    candidate_ids = {
        allowed["id"],
        slow["id"],
        unavailable_equipment["id"],
        excluded_tag["id"],
        explicitly_excluded["id"],
    }

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {
            "max_total_time_minutes": 20,
            "required_tags": ["quick"],
            "excluded_tags": ["gluten_free"],
            "excluded_recipe_ids": [
                *active_recipe_ids_except(db, candidate_ids),
                explicitly_excluded["id"],
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert meal_by_type(response.json(), "lunch")["recipe_id"] == allowed["id"]


def test_swap_excludes_dietary_mismatch_and_disliked_foods(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(
        token,
        dietary_restrictions=["vegetarian"],
        disliked_foods=["salmon"],
        equipment=[],
    )
    suffix = uuid4().hex
    breakfast = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Veg Breakfast {suffix}",
        tags=["breakfast", "vegetarian"],
        food_source_ids=["dev_oats", "dev_banana"],
    )
    lunch = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Veg Lunch {suffix}",
        tags=["lunch", "vegetarian"],
        food_source_ids=["dev_broccoli", "dev_potato"],
    )
    dinner = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Veg Dinner {suffix}",
        tags=["dinner", "vegetarian"],
        food_source_ids=["dev_spinach", "dev_potato"],
    )
    plan_response = create_plan(
        token,
        plan_body(db, {breakfast["id"], lunch["id"], dinner["id"]}, plan_date="2026-10-08"),
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    meat_alt = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Meat Lunch {uuid4().hex}",
        tags=["lunch"],
        food_source_ids=["dev_chicken_breast", "dev_cooked_rice"],
    )
    disliked_alt = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Salmon Lunch {uuid4().hex}",
        tags=["lunch", "vegetarian"],
        food_source_ids=["dev_salmon", "dev_potato"],
    )

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {
            "excluded_recipe_ids": active_recipe_ids_except(
                db,
                {meat_alt["id"], disliked_alt["id"]},
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_SWAP_CANDIDATE"
    assert get_plan(token, plan["meal_plan_id"]).json()["meals"] == plan["meals"]


def test_profile_change_does_not_change_swap_targets(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-09")
    original_targets = plan["targets"]
    update_profile(token, {"weight_kg": 120, "goal": "muscle_gain", "target_rate": 0.25})
    alternative = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Target Stable Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_egg", "dev_cooked_rice"],
    )

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {alternative["id"]})},
    )

    assert response.status_code == 200, response.text
    assert response.json()["targets"] == original_targets


def test_archived_plan_cannot_be_swapped(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-10")
    alternative = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Archived Alt Lunch {uuid4().hex}",
        tags=["lunch"],
        food_source_ids=["dev_egg", "dev_potato"],
    )
    assert archive_plan(token, plan["meal_plan_id"]).status_code == 204

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {alternative["id"]})},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MEAL_PLAN_ARCHIVED"


def test_swap_ownership_and_item_validation_are_non_leaking(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    owner_token = register_and_login(track_email(unique_email("owner")))
    other_token = register_and_login(track_email(unique_email("other")))
    create_profile(owner_token)
    create_profile(other_token)
    owner_plan, _ = create_standard_plan(db, owner_token, track_recipe, plan_date="2026-10-11")
    other_plan, _ = create_standard_plan(db, other_token, track_recipe, plan_date="2026-10-11")
    owner_lunch_id = meal_by_type(owner_plan, "lunch")["id"]
    other_lunch_id = meal_by_type(other_plan, "lunch")["id"]

    other_user_response = swap_item(
        other_token,
        owner_plan["meal_plan_id"],
        owner_lunch_id,
    )
    missing_item_response = swap_item(
        owner_token,
        owner_plan["meal_plan_id"],
        str(uuid4()),
    )
    wrong_plan_item_response = swap_item(
        owner_token,
        owner_plan["meal_plan_id"],
        other_lunch_id,
    )

    assert other_user_response.status_code == 404
    assert other_user_response.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"
    assert missing_item_response.status_code == 404
    assert missing_item_response.json()["error"]["code"] == "MEAL_PLAN_ITEM_NOT_FOUND"
    assert wrong_plan_item_response.status_code == 404
    assert wrong_plan_item_response.json()["error"]["code"] == "MEAL_PLAN_ITEM_NOT_FOUND"


def test_swap_is_deterministic_for_equal_nutrition_candidates(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-12")
    alpha = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Alpha Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_egg", "dev_potato"],
    )
    zulu = create_recipe(
        db,
        token,
        track_recipe,
        name=f"Zulu Lunch {uuid4().hex}",
        tags=["lunch", "quick"],
        food_source_ids=["dev_egg", "dev_potato"],
    )

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {"excluded_recipe_ids": active_recipe_ids_except(db, {alpha["id"], zulu["id"]})},
    )

    assert response.status_code == 200, response.text
    assert meal_by_type(response.json(), "lunch")["recipe_id"] == alpha["id"]


def test_unsupported_swap_constraints_are_controlled(swap_db) -> None:
    db, track_email, track_recipe = swap_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    plan, _ = create_standard_plan(db, token, track_recipe, plan_date="2026-10-13")

    response = swap_item(
        token,
        plan["meal_plan_id"],
        meal_by_type(plan, "lunch")["id"],
        {"different_protein": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_SWAP_CONSTRAINT"
