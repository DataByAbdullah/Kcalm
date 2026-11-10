from uuid import UUID

import pytest
from sqlalchemy import event, inspect

from app.core.database import engine
from app.models.meal_plan import MealPlanItem
from app.models.recipe import Recipe
from app.services.recipe_seed_service import seed_development_recipes
from tests.admin_helpers import promote_admin
from tests.test_meal_plan_persistence import create_profile, meal_plan_db, register_and_login, unique_email
from tests.test_recipe_images import IMAGE_FIELDS, image_boundaries, image_recipe, image_settings
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


@pytest.fixture
def image_user(meal_plan_db, image_recipe):
    db, track_email, _ = meal_plan_db
    token = register_and_login(track_email(unique_email("recipe-images")))
    create_profile(token, equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    names = [
        "Banana Egg Breakfast Pancakes", "Spinach Scrambled Eggs and Rice", "Chicken Spinach Rice Skillet",
        "Banana Rice Energy Bowl", "Chicken Spinach Potato Skillet",
    ]
    recipes = db.query(Recipe).filter(Recipe.source == "development_fixture", Recipe.name.in_(names)).all()
    assert len(recipes) == len(names)
    original = {recipe.id: {field: getattr(recipe, field) for field in IMAGE_FIELDS}
                for recipe in db.query(Recipe).filter_by(source="development_fixture", active=True).all()}
    allowed = {recipe.id for recipe in recipes}
    excluded = [str(recipe.id) for recipe in db.query(Recipe).all() if recipe.id not in allowed]
    yield db, token, {recipe.name: recipe.id for recipe in recipes}, excluded
    db.rollback()
    db.expire_all()
    for recipe_id, values in original.items():
        recipe = db.get(Recipe, recipe_id)
        for field, value in values.items():
            setattr(recipe, field, value)
    db.commit()


def make_plan(token, excluded, **overrides):
    result = request("POST", "/meal-plans", token, {
        "plan_date": "2026-11-02", "excluded_recipe_ids": excluded, **overrides,
    })
    assert result.status_code == 201, result.text
    return result.json()


def test_generation_endpoint_requires_admin_and_authentication(image_user, image_boundaries):
    _, token, recipes, _ = image_user
    path = f"/recipes/{next(iter(recipes.values()))}/image/generate"
    assert request("POST", path, body={}).status_code == 401
    assert request("POST", path, token, {}).status_code == 403
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()


def test_admin_generation_endpoint_returns_only_public_metadata(image_user, image_boundaries):
    db, token, recipes, _ = image_user
    promote_admin(token)
    recipe_id = next(iter(recipes.values()))
    response = request("POST", f"/recipes/{recipe_id}/image/generate", token, {})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"recipe_id", "image_url", "image_status", "image_model", "image_generated_at"}
    assert response.json()["image_status"] == "ready"
    assert response.json()["recipe_id"] == str(recipe_id)
    db.expire_all()
    assert db.get(Recipe, recipe_id).image_status == "ready"
    assert "test-secret" not in response.text and "test-image-api-key" not in response.text
    image_boundaries.sdk.images.generate.assert_called_once()


def test_admin_missing_configuration_returns_controlled_error(image_user, image_boundaries, image_settings):
    _, token, recipes, _ = image_user
    promote_admin(token)
    image_settings.image_storage_secret_access_key = ""
    response = request("POST", f"/recipes/{next(iter(recipes.values()))}/image/generate", token, {"force": True})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RECIPE_IMAGE_CONFIGURATION_MISSING"
    image_boundaries.sdk_factory.assert_not_called()


def test_recipe_list_detail_candidate_and_solver_preview_include_images(image_user, image_boundaries):
    db, token, recipes, excluded = image_user
    urls = {}
    for recipe_id in recipes.values():
        recipe = db.get(Recipe, recipe_id)
        recipe.image_url = f"https://images.example.test/{recipe_id}.webp"
        recipe.image_status = "ready"
        urls[str(recipe_id)] = recipe.image_url
    db.commit()
    listed = request("GET", "/recipes?limit=100", token)
    assert listed.status_code == 200
    assert all("image_url" in item for item in listed.json()["items"])
    for item in listed.json()["items"]:
        if item["id"] in urls:
            assert item["image_url"] == urls[item["id"]]
    for recipe_id, url in urls.items():
        assert request("GET", f"/recipes/{recipe_id}", token).json()["image_url"] == url
    candidates = request("POST", "/recipes/candidates/preview", token, {"excluded_recipe_ids": excluded})
    assert candidates.status_code == 200
    assert {item["recipe_id"]: item["image_url"] for item in candidates.json()["candidates"]} == urls
    preview = request("POST", "/meal-plans/solve/preview", token, {"excluded_recipe_ids": excluded})
    assert preview.status_code == 200 and preview.json()["meals"], preview.text
    assert all(item["image_url"] == urls[item["recipe_id"]] for item in preview.json()["meals"])
    created = make_plan(token, excluded)
    assert all(item["image_url"] == urls[item["recipe_id"]] for item in created["meals"])
    assert request("GET", f"/meal-plans/{created['meal_plan_id']}", token).json() == created
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()


def test_existing_plan_get_receives_image_generated_after_plan_creation(image_user):
    db, token, _, excluded = image_user
    plan = make_plan(token, excluded)
    assert all(item["image_url"] is None for item in plan["meals"])
    item = plan["meals"][0]
    before = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json()
    promote_admin(token)
    generated = request("POST", f"/recipes/{item['recipe_id']}/image/generate", token, {})
    assert generated.status_code == 200, generated.text

    after = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token)

    assert after.status_code == 200
    changed = after.json()
    assert changed["meals"][0]["image_url"] == generated.json()["image_url"]
    changed["meals"][0]["image_url"] = None
    assert changed == before  # All saved nutrition, times, targets and timestamps remain unchanged.
    assert "image_url" not in {column["name"] for column in inspect(engine).get_columns("meal_plan_items")}
    db.expire_all()
    assert db.get(MealPlanItem, UUID(item["id"])).recipe.image_url == generated.json()["image_url"]


def test_archived_plan_resolves_image_from_archived_recipe(image_user):
    db, token, _, excluded = image_user
    plan = make_plan(token, excluded)
    item = plan["meals"][0]
    recipe = db.get(Recipe, UUID(item["recipe_id"]))
    recipe.image_url = "https://images.example.test/archived.webp"
    recipe.image_status = "ready"
    recipe.active = False
    db.commit()
    try:
        archived = request("DELETE", f"/meal-plans/{plan['meal_plan_id']}", token)
        assert archived.status_code == 204
        result = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token)
        assert result.status_code == 200
        assert result.json()["status"] == "archived"
        assert result.json()["meals"][0]["image_url"] == recipe.image_url
    finally:
        recipe.active = True
        db.commit()


def test_swap_response_uses_replacement_recipe_image(image_user):
    db, token, recipes, excluded = image_user
    plan = make_plan(token, excluded)
    breakfast = plan["meals"][0]
    replacement_id = next(recipe_id for name, recipe_id in recipes.items()
                          if "Breakfast Pancakes" in name or "Scrambled Eggs" in name
                          if str(recipe_id) != breakfast["recipe_id"])
    replacement = db.get(Recipe, replacement_id)
    replacement.image_url = "https://images.example.test/replacement.webp"
    replacement.image_status = "ready"
    db.commit()
    swapped = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{breakfast['id']}/swap", token,
                      {"recipe_id": str(replacement_id)})
    assert swapped.status_code == 200, swapped.text
    item = next(item for item in swapped.json()["meals"] if item["id"] == breakfast["id"])
    assert item["image_url"] == replacement.image_url
    assert item["recipe_id"] == str(replacement_id)
    assert item["scheduled_time"] == breakfast["scheduled_time"]


def test_weekly_plans_resolve_images_in_a_batch_without_n_plus_one(image_user, image_boundaries):
    db, token, recipes, excluded = image_user
    for recipe in db.query(Recipe).filter_by(source="development_fixture", active=True).all():
        recipe.image_status = "ready"
        recipe.image_url = f"https://images.example.test/{recipe.id}.webp"
    db.commit()
    # Permit the full real catalog so the existing adjacent-day rotation can run.
    created = request("POST", "/weekly-meal-plans", token, {"start_date": "2026-11-02"})
    assert created.status_code == 201, created.text
    queries = []

    def record_recipe_select(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM recipes" in statement:
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", record_recipe_select)
    try:
        fetched = request("GET", f"/weekly-meal-plans/{created.json()['weekly_plan_id']}", token)
    finally:
        event.remove(engine, "before_cursor_execute", record_recipe_select)
    assert fetched.status_code == 200 and fetched.json() == created.json()
    assert len(queries) == 1
    for day in fetched.json()["daily_plans"]:
        for item in day["meals"]:
            assert "image_url" in item
            assert item["image_url"] == f"https://images.example.test/{item['recipe_id']}.webp"
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()


def test_reseeding_preserves_recipe_id_and_all_image_metadata(image_recipe):
    db, recipe_id = image_recipe
    from app.services.recipe_image_service import generate_recipe_image

    generate_recipe_image(db, recipe_id)
    saved = {field: getattr(db.get(Recipe, recipe_id), field) for field in IMAGE_FIELDS}
    seed_development_recipes(db)
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe.id == recipe_id
    assert {field: getattr(recipe, field) for field in IMAGE_FIELDS} == saved


def test_adaptive_preview_and_generated_plan_include_current_images(image_user, image_boundaries):
    db, token, _, excluded = image_user
    for recipe in db.query(Recipe).filter_by(source="development_fixture", active=True).all():
        recipe.image_url = f"https://images.example.test/{recipe.id}.webp"
        recipe.image_status = "ready"
    db.commit()
    plan = make_plan(token, excluded)
    for item in plan["meals"]:
        logged = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{item['id']}/log", token,
                         {"type": "ate_as_planned"})
        assert logged.status_code == 200, logged.text
    preview = request("POST", f"/meal-plans/{plan['meal_plan_id']}/adaptive-preview", token, {})
    assert preview.status_code == 200 and preview.json()["solver_preview"]["meals"], preview.text
    assert all(item["image_url"] == f"https://images.example.test/{item['recipe_id']}.webp"
               for item in preview.json()["solver_preview"]["meals"])
    generated = request("POST", f"/meal-plans/{plan['meal_plan_id']}/generate-next-day", token, {})
    assert generated.status_code == 201, generated.text
    assert all(item["image_url"] == f"https://images.example.test/{item['recipe_id']}.webp"
               for item in generated.json()["plan"]["meals"])
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()


@pytest.mark.parametrize("failure_mode", ["missing_openai_key", "missing_storage_key", "openai_error", "storage_error", "failed_status"])
def test_image_failures_never_block_preview_create_read_or_swap(
    image_user, image_settings, image_boundaries, failure_mode,
):
    db, token, recipes, excluded = image_user
    if failure_mode == "missing_openai_key":
        image_settings.openai_api_key = ""
    elif failure_mode == "missing_storage_key":
        image_settings.image_storage_secret_access_key = ""
    elif failure_mode == "openai_error":
        image_boundaries.sdk.images.generate.side_effect = RuntimeError("test-secret")
    elif failure_mode == "storage_error":
        image_boundaries.storage.put_object.side_effect = RuntimeError("test-secret")
    for recipe_id in recipes.values():
        db.get(Recipe, recipe_id).image_status = "failed"
    db.commit()
    if failure_mode != "failed_status":
        promote_admin(token)
        failure = request("POST", f"/recipes/{next(iter(recipes.values()))}/image/generate", token, {})
        assert failure.status_code == (503 if failure_mode.startswith("missing") else 502)
        assert "test-secret" not in failure.text
    image_boundaries.sdk_factory.reset_mock()
    image_boundaries.storage_factory.reset_mock()

    preview = request("POST", "/meal-plans/solve/preview", token, {"excluded_recipe_ids": excluded})
    assert preview.status_code == 200 and len(preview.json()["meals"]) == 4, preview.text
    assert all(item["image_url"] is None for item in preview.json()["meals"])
    plan = make_plan(token, excluded)
    assert all(item["image_url"] is None for item in plan["meals"])
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan
    item = plan["meals"][0]
    swapped = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{item['id']}/swap", token, {})
    assert swapped.status_code == 200, swapped.text
    assert all(item["image_url"] is None for item in swapped.json()["meals"])
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()
