from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import FoodSource, GroceryCategory
from app.core.exceptions import APIErrorException
from app.models.food import Food
from app.models.grocery import GroceryList
from app.models.meal_plan import MealPlan, MealPlanItem, MealPlanItemIngredientSnapshot
from app.models.recipe import Recipe
from app.models.user import User
from app.services.grocery_service import (
    category_for_food_category,
    create_grocery_list_from_weekly_plan,
)
from tests.test_weekly_meal_plans import (
    api_request,
    auth_headers,
    create_profile,
    create_recipe_set,
    create_week,
    food_id,
    grocery_preview,
    register_and_login,
    run_async,
    setup_foods,
    unique_email,
    weekly_body,
)


@pytest.fixture(autouse=True)
def require_grocery_tables():
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
                "meal_plan_item_ingredients",
                "weekly_meal_plans",
                "grocery_lists",
                "grocery_list_items",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("grocery list tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def grocery_db():
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

    db.query(Food).filter(Food.source_food_id.like("same_name_grocery_%")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def create_grocery_list(token: str, weekly_plan_id: str):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/weekly-meal-plans/{weekly_plan_id}/grocery-list",
            headers=auth_headers(token),
        )
    )


def get_grocery_list(token: str, grocery_list_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/grocery-lists/{grocery_list_id}",
            headers=auth_headers(token),
        )
    )


def list_grocery_lists(token: str, query: str = ""):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/grocery-lists{query}",
            headers=auth_headers(token),
        )
    )


def patch_grocery_item(token: str, grocery_list_id: str, item_id: str, body: dict):
    return run_async(
        api_request(
            "PATCH",
            f"/api/v1/grocery-lists/{grocery_list_id}/items/{item_id}",
            headers=auth_headers(token),
            json=body,
        )
    )


def add_grocery_item(token: str, grocery_list_id: str, body: dict):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/grocery-lists/{grocery_list_id}/items",
            headers=auth_headers(token),
            json=body,
        )
    )


def delete_grocery_item(token: str, grocery_list_id: str, item_id: str):
    return run_async(
        api_request(
            "DELETE",
            f"/api/v1/grocery-lists/{grocery_list_id}/items/{item_id}",
            headers=auth_headers(token),
        )
    )


def regenerate_grocery(token: str, grocery_list_id: str):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/grocery-lists/{grocery_list_id}/regenerate",
            headers=auth_headers(token),
        )
    )


def archive_grocery_list(token: str, grocery_list_id: str):
    return run_async(
        api_request(
            "DELETE",
            f"/api/v1/grocery-lists/{grocery_list_id}",
            headers=auth_headers(token),
        )
    )


def create_week_and_grocery_list(db, token: str, track_recipe, start_date: str = "2026-12-14"):
    recipes = create_recipe_set(db, token, track_recipe)
    week_response = create_week(
        token,
        weekly_body(
            db,
            {recipe["id"] for recipe in recipes.values()},
            start_date=start_date,
        ),
    )
    assert week_response.status_code == 201, week_response.text
    grocery_response = create_grocery_list(token, week_response.json()["weekly_plan_id"])
    assert grocery_response.status_code == 201, grocery_response.text
    return week_response.json(), grocery_response.json(), recipes


def item_by_food_id(grocery_list: dict, food_id: str) -> dict:
    return next(item for item in grocery_list["items"] if item["food_id"] == food_id)


def test_grocery_list_endpoints_require_authentication() -> None:
    grocery_list_id = uuid4()
    item_id = uuid4()
    weekly_plan_id = uuid4()

    generate = run_async(
        api_request("POST", f"/api/v1/weekly-meal-plans/{weekly_plan_id}/grocery-list")
    )
    list_response = run_async(api_request("GET", "/api/v1/grocery-lists"))
    detail = run_async(api_request("GET", f"/api/v1/grocery-lists/{grocery_list_id}"))
    patch = run_async(
        api_request(
            "PATCH",
            f"/api/v1/grocery-lists/{grocery_list_id}/items/{item_id}",
            json={"checked": True},
        )
    )
    add = run_async(
        api_request(
            "POST",
            f"/api/v1/grocery-lists/{grocery_list_id}/items",
            json={"name": "Water", "quantity": 1, "unit": "bottle"},
        )
    )
    remove = run_async(
        api_request("DELETE", f"/api/v1/grocery-lists/{grocery_list_id}/items/{item_id}")
    )
    regenerate = run_async(api_request("POST", f"/api/v1/grocery-lists/{grocery_list_id}/regenerate"))
    archive = run_async(api_request("DELETE", f"/api/v1/grocery-lists/{grocery_list_id}"))

    assert generate.status_code == 401
    assert list_response.status_code == 401
    assert detail.status_code == 401
    assert patch.status_code == 401
    assert add.status_code == 401
    assert remove.status_code == 401
    assert regenerate.status_code == 401
    assert archive.status_code == 401


def test_grocery_list_creation_uses_weekly_snapshot_aggregation(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    week, grocery_list, _ = create_week_and_grocery_list(db, token, track_recipe)
    preview = grocery_preview(token, week["weekly_plan_id"]).json()

    assert grocery_list["weekly_plan_id"] == week["weekly_plan_id"]
    assert grocery_list["status"] == "active"
    assert grocery_list["items"]
    preview_totals = {item["food_id"]: item["total_grams"] for item in preview["items"]}
    generated_items = [item for item in grocery_list["items"] if not item["manually_added"]]
    assert {item["food_id"] for item in generated_items} == set(preview_totals)
    for item in generated_items:
        assert item["quantity"] == pytest.approx(preview_totals[item["food_id"]])
        assert item["quantity_grams"] == pytest.approx(preview_totals[item["food_id"]])
        assert item["unit"] == "g"
    assert len([item for item in generated_items if item["food_name"] == "Banana"]) == 1
    assert {item["category"] for item in generated_items}.issubset(
        {"produce", "meat_seafood", "dairy", "grains", "pantry", "frozen", "other"}
    )


def test_duplicate_active_grocery_list_is_blocked(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    week_response = create_week(
        token,
        weekly_body(db, {recipe["id"] for recipe in recipes.values()}, start_date="2026-12-21"),
    )
    assert week_response.status_code == 201

    first = create_grocery_list(token, week_response.json()["weekly_plan_id"])
    second = create_grocery_list(token, week_response.json()["weekly_plan_id"])

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "GROCERY_LIST_ALREADY_EXISTS"


def test_grocery_ownership_and_weekly_ownership_are_non_leaking(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    owner_token = register_and_login(track_email(unique_email("owner")))
    other_token = register_and_login(track_email(unique_email("other")))
    create_profile(owner_token)
    create_profile(other_token)
    week, grocery_list, _ = create_week_and_grocery_list(
        db,
        owner_token,
        track_recipe,
        start_date="2026-12-28",
    )
    first_item_id = grocery_list["items"][0]["id"]

    other_generate = create_grocery_list(other_token, week["weekly_plan_id"])
    other_detail = get_grocery_list(other_token, grocery_list["grocery_list_id"])
    other_patch = patch_grocery_item(
        other_token,
        grocery_list["grocery_list_id"],
        first_item_id,
        {"checked": True},
    )
    other_archive = archive_grocery_list(other_token, grocery_list["grocery_list_id"])

    assert other_generate.status_code == 404
    assert other_generate.json()["error"]["code"] == "WEEKLY_PLAN_NOT_FOUND"
    assert other_detail.status_code == 404
    assert other_detail.json()["error"]["code"] == "GROCERY_LIST_NOT_FOUND"
    assert other_patch.status_code == 404
    assert other_patch.json()["error"]["code"] == "GROCERY_LIST_NOT_FOUND"
    assert other_archive.status_code == 404
    assert other_archive.json()["error"]["code"] == "GROCERY_LIST_NOT_FOUND"


def test_list_get_check_uncheck_and_generated_quantity_edit(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    _, grocery_list, _ = create_week_and_grocery_list(
        db,
        token,
        track_recipe,
        start_date="2027-01-04",
    )
    grocery_list_id = grocery_list["grocery_list_id"]
    item_id = grocery_list["items"][0]["id"]

    listed = list_grocery_lists(token)
    detail = get_grocery_list(token, grocery_list_id)
    checked = patch_grocery_item(token, grocery_list_id, item_id, {"checked": True})
    unchecked_and_edited = patch_grocery_item(
        token,
        grocery_list_id,
        item_id,
        {"checked": False, "quantity": 123, "unit": "g", "category": "pantry"},
    )

    assert listed.status_code == 200
    assert grocery_list_id in {item["grocery_list_id"] for item in listed.json()["items"]}
    assert detail.status_code == 200
    assert checked.status_code == 200
    assert next(item for item in checked.json()["items"] if item["id"] == item_id)["checked"] is True
    edited_item = next(item for item in unchecked_and_edited.json()["items"] if item["id"] == item_id)
    assert edited_item["checked"] is False
    assert edited_item["quantity"] == pytest.approx(123)
    assert edited_item["quantity_grams"] == pytest.approx(123)
    assert edited_item["category"] == "pantry"


def test_manual_item_add_and_remove(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    _, grocery_list, _ = create_week_and_grocery_list(
        db,
        token,
        track_recipe,
        start_date="2027-01-11",
    )
    grocery_list_id = grocery_list["grocery_list_id"]

    added = add_grocery_item(
        token,
        grocery_list_id,
        {"name": "Sparkling Water", "quantity": 2, "unit": "bottle", "category": "other"},
    )
    manual_item = next(item for item in added.json()["items"] if item["food_name"] == "Sparkling Water")
    removed = delete_grocery_item(token, grocery_list_id, manual_item["id"])
    after_remove = get_grocery_list(token, grocery_list_id).json()

    assert added.status_code == 201
    assert manual_item["manually_added"] is True
    assert manual_item["food_id"] is None
    assert manual_item["quantity_grams"] is None
    assert removed.status_code == 204
    assert "Sparkling Water" not in {item["food_name"] for item in after_remove["items"]}


def test_different_foods_with_same_snapshot_name_do_not_merge(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    week_response = create_week(
        token,
        weekly_body(db, {recipe["id"] for recipe in recipes.values()}, start_date="2027-01-15"),
    )
    assert week_response.status_code == 201, week_response.text
    weekly_plan_id = UUID(week_response.json()["weekly_plan_id"])
    existing_snapshot = (
        db.query(MealPlanItemIngredientSnapshot)
        .join(MealPlanItem)
        .join(MealPlan)
        .filter(MealPlan.weekly_plan_id == weekly_plan_id)
        .order_by(MealPlan.plan_date, MealPlanItem.position)
        .first()
    )
    assert existing_snapshot is not None
    duplicate_named_food = Food(
        name=existing_snapshot.food_name_snapshot,
        source=FoodSource.INTERNAL,
        source_food_id=f"same_name_grocery_{uuid4().hex}",
        category="fruit",
        description="Test fixture food with same display name as another food.",
    )
    db.add(duplicate_named_food)
    db.flush()
    db.add(
        MealPlanItemIngredientSnapshot(
            meal_plan_item_id=existing_snapshot.meal_plan_item_id,
            food_id=duplicate_named_food.id,
            food_name_snapshot=existing_snapshot.food_name_snapshot,
            quantity_grams=42,
        )
    )
    db.commit()

    grocery_response = create_grocery_list(token, str(weekly_plan_id))

    assert grocery_response.status_code == 201, grocery_response.text
    same_name_items = [
        item
        for item in grocery_response.json()["items"]
        if item["food_name"] == existing_snapshot.food_name_snapshot
    ]
    assert len({item["food_id"] for item in same_name_items}) >= 2
    duplicate_item = item_by_food_id(grocery_response.json(), str(duplicate_named_food.id))
    assert duplicate_item["quantity"] == pytest.approx(42)


def test_regenerate_rebuilds_automatic_items_and_preserves_manual_items(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    week, grocery_list, _ = create_week_and_grocery_list(
        db,
        token,
        track_recipe,
        start_date="2027-01-18",
    )
    grocery_list_id = grocery_list["grocery_list_id"]
    preview_totals = {
        item["food_id"]: item["total_grams"]
        for item in grocery_preview(token, week["weekly_plan_id"]).json()["items"]
    }
    edited_item = grocery_list["items"][0]
    patch_grocery_item(
        token,
        grocery_list_id,
        edited_item["id"],
        {"checked": True, "quantity": 999, "unit": "g"},
    )
    add_grocery_item(
        token,
        grocery_list_id,
        {"name": "Sparkling Water", "quantity": 2, "unit": "bottle", "category": "other"},
    )

    regenerated = regenerate_grocery(token, grocery_list_id)

    assert regenerated.status_code == 200, regenerated.text
    body = regenerated.json()
    regenerated_auto = item_by_food_id(body, edited_item["food_id"])
    assert regenerated_auto["checked"] is True
    assert regenerated_auto["quantity"] == pytest.approx(preview_totals[edited_item["food_id"]])
    assert "Sparkling Water" in {
        item["food_name"] for item in body["items"] if item["manually_added"]
    }


def test_recipe_edit_does_not_change_existing_grocery_list(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    week, grocery_list, _ = create_week_and_grocery_list(
        db,
        token,
        track_recipe,
        start_date="2027-01-25",
    )
    original_items = grocery_list["items"]
    selected_recipe_id = week["daily_plans"][0]["meals"][0]["recipe_id"]

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
    fetched = get_grocery_list(token, grocery_list["grocery_list_id"]).json()

    assert patch_response.status_code == 200, patch_response.text
    assert fetched["items"] == original_items


def test_archive_hides_grocery_list_from_default_listing(grocery_db) -> None:
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery")))
    create_profile(token)
    _, grocery_list, _ = create_week_and_grocery_list(
        db,
        token,
        track_recipe,
        start_date="2027-02-01",
    )
    grocery_list_id = grocery_list["grocery_list_id"]

    archive_response = archive_grocery_list(token, grocery_list_id)
    default_list = list_grocery_lists(token)
    archived_list = list_grocery_lists(token, "?status=archived")

    assert archive_response.status_code == 204
    assert grocery_list_id not in {
        item["grocery_list_id"] for item in default_list.json()["items"]
    }
    assert grocery_list_id in {
        item["grocery_list_id"] for item in archived_list.json()["items"]
    }


def test_unknown_food_category_falls_back_to_other() -> None:
    assert category_for_food_category("unknown_category") == GroceryCategory.OTHER
    assert category_for_food_category(None) == GroceryCategory.OTHER


def test_generation_rolls_back_when_item_persistence_fails(grocery_db, monkeypatch) -> None:
    from app.services import grocery_service

    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    email = track_email(unique_email("grocery"))
    token = register_and_login(email)
    create_profile(token)
    recipes = create_recipe_set(db, token, track_recipe)
    week_response = create_week(
        token,
        weekly_body(db, {recipe["id"] for recipe in recipes.values()}, start_date="2027-02-08"),
    )
    assert week_response.status_code == 201
    user = db.query(User).filter(User.email == email).one()

    def fail_items(*args, **kwargs):
        raise RuntimeError("forced grocery item persistence failure")

    monkeypatch.setattr(grocery_service, "persist_automatic_grocery_items", fail_items)

    with pytest.raises(RuntimeError):
        create_grocery_list_from_weekly_plan(
            db=db,
            user=user,
            weekly_plan_id=UUID(week_response.json()["weekly_plan_id"]),
        )

    assert db.query(GroceryList).filter(GroceryList.user_id == user.id).count() == 0
