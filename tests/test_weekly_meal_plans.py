import asyncio
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.exceptions import APIErrorException
from app.main import app
from app.models.food import Food
from app.models.meal_plan import (
    MealPlan,
    MealPlanItem,
    MealPlanItemIngredientSnapshot,
    WeeklyMealPlan,
)
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.weekly_plan import WeeklyMealPlanCreateRequest
from app.services.food_seed_service import seed_development_foods
from app.services.weekly_plan_service import create_weekly_plan


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_weekly_tables():
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
                "weekly_meal_plans",
                "meal_plan_item_ingredients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("weekly meal plan tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def weekly_db():
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
    db.close()


def unique_email(prefix: str = "weekly") -> str:
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
        "equipment": [],
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
) -> dict:
    return {
        "name": name,
        "description": "Weekly plan test recipe.",
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
        "equipment": [],
    }


def create_recipe(
    db,
    token: str,
    track_recipe,
    name: str,
    tags: list[str],
    food_source_ids: list[str],
) -> dict:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/recipes",
            headers=auth_headers(token),
            json=recipe_payload(
                db=db,
                name=name,
                tags=tags,
                food_source_ids=food_source_ids,
            ),
        )
    )
    assert response.status_code == 201, response.text
    body = response.json()
    track_recipe(body["id"])
    return body


def create_recipe_set(db, token: str, track_recipe, *, alternatives: bool = True) -> dict[str, dict]:
    suffix = uuid4().hex
    recipes = {
        "breakfast_a": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Weekly Alpha Breakfast {suffix}",
            tags=["breakfast", "quick", "vegetarian"],
            food_source_ids=["dev_oats", "dev_banana"],
        ),
        "lunch_a": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Weekly Alpha Lunch {suffix}",
            tags=["lunch", "quick", "high_protein"],
            food_source_ids=["dev_chicken_breast", "dev_cooked_rice"],
        ),
        "dinner_a": create_recipe(
            db,
            token,
            track_recipe,
            name=f"Weekly Alpha Dinner {suffix}",
            tags=["dinner", "high_protein"],
            food_source_ids=["dev_salmon", "dev_potato"],
        ),
    }
    if alternatives:
        recipes.update(
            {
                "breakfast_b": create_recipe(
                    db,
                    token,
                    track_recipe,
                    name=f"Weekly Beta Breakfast {suffix}",
                    tags=["breakfast", "quick", "vegetarian"],
                    food_source_ids=["dev_greek_yogurt", "dev_banana"],
                ),
                "lunch_b": create_recipe(
                    db,
                    token,
                    track_recipe,
                    name=f"Weekly Beta Lunch {suffix}",
                    tags=["lunch", "quick", "high_protein"],
                    food_source_ids=["dev_egg", "dev_potato"],
                ),
                "dinner_b": create_recipe(
                    db,
                    token,
                    track_recipe,
                    name=f"Weekly Beta Dinner {suffix}",
                    tags=["dinner", "high_protein"],
                    food_source_ids=["dev_chicken_breast", "dev_broccoli"],
                ),
            }
        )
    return recipes


def active_recipe_ids_except(db, keep_ids: set[str]) -> list[str]:
    db.expire_all()
    return [
        str(recipe.id)
        for recipe in db.query(Recipe).filter(Recipe.active.is_(True)).all()
        if str(recipe.id) not in keep_ids
    ]


def weekly_body(db, selected_ids: set[str], start_date: str = "2026-10-12", **overrides) -> dict:
    body = {
        "start_date": start_date,
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
    body.update(overrides)
    return body


def create_week(token: str, body: dict):
    return run_async(
        api_request(
            "POST",
            "/api/v1/weekly-meal-plans",
            headers=auth_headers(token),
            json=body,
        )
    )


def get_week(token: str, weekly_plan_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/weekly-meal-plans/{weekly_plan_id}",
            headers=auth_headers(token),
        )
    )


def list_weeks(token: str, query: str = ""):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/weekly-meal-plans{query}",
            headers=auth_headers(token),
        )
    )


def archive_week(token: str, weekly_plan_id: str):
    return run_async(
        api_request(
            "DELETE",
            f"/api/v1/weekly-meal-plans/{weekly_plan_id}",
            headers=auth_headers(token),
        )
    )


def grocery_preview(token: str, weekly_plan_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/weekly-meal-plans/{weekly_plan_id}/grocery/preview",
            headers=auth_headers(token),
        )
    )


def create_daily_plan(token: str, body: dict):
    return run_async(
        api_request(
            "POST",
            "/api/v1/meal-plans",
            headers=auth_headers(token),
            json=body,
        )
    )


def daily_body_from_weekly(body: dict, plan_date: str) -> dict:
    daily = {key: value for key, value in body.items() if key != "start_date"}
    daily["plan_date"] = plan_date
    return daily


def selected_recipe_sets(week: dict) -> list[set[str]]:
    return [
        {meal["recipe_id"] for meal in daily_plan["meals"]}
        for daily_plan in week["daily_plans"]
    ]


def expected_grocery_totals_from_snapshots(db, weekly_plan_id: str) -> dict[str, float]:
    rows = (
        db.query(MealPlanItemIngredientSnapshot)
        .join(MealPlanItem)
        .join(MealPlan)
        .filter(MealPlan.weekly_plan_id == UUID(weekly_plan_id))
        .all()
    )
    totals: dict[str, float] = {}
    for row in rows:
        key = str(row.food_id)
        totals[key] = totals.get(key, 0) + row.quantity_grams
    return totals


def test_weekly_endpoints_require_authentication() -> None:
    weekly_plan_id = uuid4()

    create_response = run_async(api_request("POST", "/api/v1/weekly-meal-plans", json={}))
    list_response = run_async(api_request("GET", "/api/v1/weekly-meal-plans"))
    detail_response = run_async(api_request("GET", f"/api/v1/weekly-meal-plans/{weekly_plan_id}"))
    archive_response = run_async(api_request("DELETE", f"/api/v1/weekly-meal-plans/{weekly_plan_id}"))
    grocery_response = run_async(
        api_request("GET", f"/api/v1/weekly-meal-plans/{weekly_plan_id}/grocery/preview")
    )

    assert create_response.status_code == 401
    assert list_response.status_code == 401
    assert detail_response.status_code == 401
    assert archive_response.status_code == 401
    assert grocery_response.status_code == 401


def test_successful_weekly_plan_generates_seven_associated_days(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    body = weekly_body(db, {recipe["id"] for recipe in recipes.values()})

    response = create_week(token, body)

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["start_date"] == "2026-10-12"
    assert created["end_date"] == "2026-10-18"
    assert created["status"] == "generated"
    assert [day["plan_date"] for day in created["daily_plans"]] == [
        "2026-10-12",
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
        "2026-10-17",
        "2026-10-18",
    ]
    assert len(created["daily_plans"]) == 7
    assert all(len(day["meals"]) == 3 for day in created["daily_plans"])
    assert all(day["meal_plan_id"] for day in created["daily_plans"])

    recipe_sets = selected_recipe_sets(created)
    for current, following in zip(recipe_sets, recipe_sets[1:], strict=False):
        assert current.isdisjoint(following)

    weekly_plan_id = UUID(created["weekly_plan_id"])
    persisted_week = db.get(WeeklyMealPlan, weekly_plan_id)
    assert persisted_week is not None
    assert (
        db.query(MealPlan)
        .filter(MealPlan.weekly_plan_id == weekly_plan_id)
        .count()
    ) == 7
    assert (
        db.query(MealPlanItemIngredientSnapshot)
        .join(MealPlanItem)
        .join(MealPlan)
        .filter(MealPlan.weekly_plan_id == weekly_plan_id)
        .count()
    ) > 0


def test_weekly_list_and_detail_are_owned_and_structured(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    create_response = create_week(token, weekly_body(db, {recipe["id"] for recipe in recipes.values()}))
    assert create_response.status_code == 201

    weekly_plan_id = create_response.json()["weekly_plan_id"]
    list_response = list_weeks(token)
    detail_response = get_week(token, weekly_plan_id)

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] >= 1
    assert weekly_plan_id in {item["weekly_plan_id"] for item in listed["items"]}
    summary = next(item for item in listed["items"] if item["weekly_plan_id"] == weekly_plan_id)
    assert summary["daily_plan_count"] == 7
    assert detail_response.status_code == 200
    assert detail_response.json()["daily_plans"][0]["targets"]["micronutrients"]


def test_duplicate_weekly_plan_is_blocked(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    body = weekly_body(db, {recipe["id"] for recipe in recipes.values()})

    first = create_week(token, body)
    second = create_week(token, body)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "WEEKLY_PLAN_ALREADY_EXISTS"


def test_weekly_ownership_is_non_leaking(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    owner_token = register_and_login(track_email(unique_email("owner")))
    other_token = register_and_login(track_email(unique_email("other")))
    create_profile(owner_token)
    create_profile(other_token)
    recipes = create_recipe_set(db, owner_token, track_recipe)
    created = create_week(
        owner_token,
        weekly_body(db, {recipe["id"] for recipe in recipes.values()}),
    )
    assert created.status_code == 201
    weekly_plan_id = created.json()["weekly_plan_id"]

    other_detail = get_week(other_token, weekly_plan_id)
    other_archive = archive_week(other_token, weekly_plan_id)
    other_grocery = grocery_preview(other_token, weekly_plan_id)

    assert other_detail.status_code == 404
    assert other_detail.json()["error"]["code"] == "WEEKLY_PLAN_NOT_FOUND"
    assert other_archive.status_code == 404
    assert other_archive.json()["error"]["code"] == "WEEKLY_PLAN_NOT_FOUND"
    assert other_grocery.status_code == 404
    assert other_grocery.json()["error"]["code"] == "WEEKLY_PLAN_NOT_FOUND"


def test_archive_weekly_plan_archives_member_daily_plans(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    created = create_week(token, weekly_body(db, {recipe["id"] for recipe in recipes.values()}))
    assert created.status_code == 201
    weekly_plan_id = created.json()["weekly_plan_id"]

    archive_response = archive_week(token, weekly_plan_id)
    detail_response = get_week(token, weekly_plan_id)
    default_list = list_weeks(token)
    archived_list = list_weeks(token, "?status=archived")

    assert archive_response.status_code == 204
    assert detail_response.json()["status"] == "archived"
    assert all(day["status"] == "archived" for day in detail_response.json()["daily_plans"])
    assert weekly_plan_id not in {item["weekly_plan_id"] for item in default_list.json()["items"]}
    assert weekly_plan_id in {item["weekly_plan_id"] for item in archived_list.json()["items"]}


def test_existing_daily_plan_conflict_is_controlled(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    selected_ids = {recipe["id"] for recipe in recipes.values()}
    body = weekly_body(db, selected_ids, start_date="2026-10-19")
    daily_response = create_daily_plan(token, daily_body_from_weekly(body, "2026-10-19"))

    response = create_week(token, body)

    assert daily_response.status_code == 201
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK"
    assert response.json()["error"]["details"]["conflict_dates"] == ["2026-10-19"]


def test_infeasible_week_returns_controlled_error_and_no_partial_week(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    email = track_email(unique_email())
    token = register_and_login(email)
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    response = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-10-26",
            required_tags=["vegan"],
        ),
    )

    user = db.query(User).filter(User.email == email).one()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WEEKLY_PLAN_INFEASIBLE"
    assert response.json()["error"]["details"]["failed_date"] == "2026-10-26"
    assert db.query(WeeklyMealPlan).filter(WeeklyMealPlan.user_id == user.id).count() == 0
    assert db.query(MealPlan).filter(MealPlan.user_id == user.id).count() == 0


def test_weekly_creation_rolls_back_when_later_day_fails(weekly_db, monkeypatch) -> None:
    from app.services import weekly_plan_service

    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    email = track_email(unique_email())
    token = register_and_login(email)
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    user = db.query(User).filter(User.email == email).one()
    payload = WeeklyMealPlanCreateRequest(
        **weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-11-02",
        )
    )
    real_create_daily = weekly_plan_service.create_daily_meal_plan
    def fail_on_fifth_day(*args, **kwargs):
        if kwargs["payload"].plan_date == date(2026, 11, 6):
            raise APIErrorException(
                status_code=422,
                code="MEAL_PLAN_INFEASIBLE",
                message="forced later-day failure",
                details={"infeasibility_reasons": ["forced_failure"]},
            )
        return real_create_daily(*args, **kwargs)

    monkeypatch.setattr(weekly_plan_service, "create_daily_meal_plan", fail_on_fifth_day)

    with pytest.raises(APIErrorException) as exc_info:
        create_weekly_plan(db=db, user=user, payload=payload)

    assert exc_info.value.code == "WEEKLY_PLAN_INFEASIBLE"
    assert exc_info.value.details["failed_date"] == "2026-11-06"
    assert (
        db.query(WeeklyMealPlan)
        .filter(WeeklyMealPlan.user_id == user.id)
        .count()
    ) == 0
    assert db.query(MealPlan).filter(MealPlan.user_id == user.id).count() == 0


def test_limited_candidate_variety_fallback_still_succeeds(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe, alternatives=False)

    response = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-11-09",
        ),
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert len(created["daily_plans"]) == 7
    assert selected_recipe_sets(created)[0] == selected_recipe_sets(created)[1]


def test_grocery_preview_aggregates_snapshot_food_quantities(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    created = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-11-16",
        ),
    )
    assert created.status_code == 201
    weekly_plan_id = created.json()["weekly_plan_id"]

    response = grocery_preview(token, weekly_plan_id)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    expected = expected_grocery_totals_from_snapshots(db, weekly_plan_id)
    assert {item["food_id"] for item in items} == set(expected)
    for item in items:
        assert item["total_grams"] == pytest.approx(expected[item["food_id"]])
        assert item["source"] == "internal"
        assert item["source_food_id"]
        assert item["category"]
    banana_items = [item for item in items if item["food_name"] == "Banana"]
    assert len(banana_items) == 1
    assert banana_items[0]["total_grams"] > 100


def test_grocery_quantities_use_recipe_grams_and_item_servings(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    created = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-11-23",
        ),
    )
    assert created.status_code == 201
    weekly_plan_id = UUID(created.json()["weekly_plan_id"])

    snapshots = (
        db.query(MealPlanItemIngredientSnapshot)
        .join(MealPlanItem)
        .join(MealPlan)
        .filter(MealPlan.weekly_plan_id == weekly_plan_id)
        .all()
    )
    assert snapshots
    for snapshot in snapshots:
        item = db.get(MealPlanItem, snapshot.meal_plan_item_id)
        recipe = db.get(Recipe, item.recipe_id)
        ingredient = next(
            ingredient
            for ingredient in recipe.ingredients
            if ingredient.food_id == snapshot.food_id
        )
        assert snapshot.quantity_grams == pytest.approx(
            float(ingredient.quantity_grams) * item.servings
        )


def test_recipe_edit_does_not_change_grocery_preview_snapshots(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    created = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-11-30",
        ),
    )
    assert created.status_code == 201
    weekly_plan_id = created.json()["weekly_plan_id"]
    original_preview = grocery_preview(token, weekly_plan_id).json()
    selected_recipe_id = created.json()["daily_plans"][0]["meals"][0]["recipe_id"]

    patch_response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{selected_recipe_id}",
            headers=auth_headers(token),
            json={
                "ingredients": [
                    {
                        "food_id": food_id(db, "dev_olive_oil"),
                        "quantity_grams": 100,
                        "position": 1,
                    }
                ]
            },
        )
    )
    assert patch_response.status_code == 200, patch_response.text

    updated_preview = grocery_preview(token, weekly_plan_id).json()
    assert updated_preview == original_preview


def test_missing_ingredient_snapshots_return_controlled_grocery_error(weekly_db) -> None:
    db, track_email, track_recipe = weekly_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    created = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date="2026-12-07",
        ),
    )
    assert created.status_code == 201
    first_item_id = UUID(created.json()["daily_plans"][0]["meals"][0]["id"])
    db.query(MealPlanItemIngredientSnapshot).filter(
        MealPlanItemIngredientSnapshot.meal_plan_item_id == first_item_id
    ).delete(synchronize_session=False)
    db.commit()

    response = grocery_preview(token, created.json()["weekly_plan_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GROCERY_SNAPSHOT_MISSING"
    assert str(first_item_id) in response.json()["error"]["details"]["meal_plan_item_ids"]
