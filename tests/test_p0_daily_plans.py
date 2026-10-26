from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.food import Food
from app.models.meal_plan import MealPlanItem
from app.models.recipe import Recipe
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE, calculate_recipe_nutrients
from app.schemas.meal_plan import MealPlanCreateRequest, MealSlotRequest
from app.seed_data.allergen_reviews import DEV_FOOD_ALLERGEN_REVIEWS
from app.seed_data.recipes import DEV_RECIPE_SEED_DATA, DEV_RECIPE_SEED_SOURCE
from app.services.recipe_seed_service import seed_development_recipes
from tests.test_meal_plan_persistence import (
    api_request, auth_headers, create_plan, create_profile, create_recipe,
    get_plan, meal_plan_db, recipe_payload, register_and_login, run_async, unique_email,
)


MEAL_TYPES = ("breakfast", "lunch", "pre_workout", "dinner")
EQUIPMENT = {"stovetop", "oven", "air_fryer", "slow_cooker", "microwave", "blender"}


@pytest.fixture(scope="module")
def catalog():
    with SessionLocal() as db:
        seed_development_recipes(db)


@pytest.fixture
def p0_user(meal_plan_db, catalog):
    db, track_email, track_recipe = meal_plan_db
    token = register_and_login(track_email(unique_email("p0")))
    create_profile(token, dietary_restrictions=["dairy_free", "gluten_free"],
                   equipment=["stovetop", "oven", "air_fryer"], max_cooking_minutes=20)
    return db, token, track_email, track_recipe


def request(method, path, token=None, body=None):
    return run_async(api_request(method, f"/api/v1{path}",
                                headers=auth_headers(token) if token else {}, json=body))


def four_slots(**overrides):
    return {"plan_date": "2026-10-26", "meal_slots": [
        {"meal_type": meal_type, "required": True} for meal_type in MEAL_TYPES
    ], "require_complete_nutrition": True, **overrides}


def catalog_recipes(db):
    return db.query(Recipe).filter_by(source=DEV_RECIPE_SEED_SOURCE, active=True).all()


@pytest.mark.parametrize("meal_type", [*MEAL_TYPES, "snack"])
def test_meal_type_schema_preserves_snack_and_accepts_pre_workout(meal_type):
    assert MealSlotRequest(meal_type=meal_type).meal_type == meal_type


def test_meal_type_schema_still_rejects_invalid_and_duplicate_types():
    with pytest.raises(ValidationError):
        MealSlotRequest(meal_type="post_workout")
    with pytest.raises(ValidationError):
        MealPlanCreateRequest(meal_slots=[{"meal_type": "pre_workout"}] * 2)


def test_catalog_counts_explicit_diets_equipment_and_instructions():
    assert len(DEV_RECIPE_SEED_DATA) == 41
    assert len({item["name"] for item in DEV_RECIPE_SEED_DATA}) == 41
    assert len(DEV_FOOD_ALLERGEN_REVIEWS) == 12
    for meal_type, expected_dual in zip(MEAL_TYPES, (7, 8, 6, 8)):
        recipes = [item for item in DEV_RECIPE_SEED_DATA if meal_type in item["tags"]]
        assert len(recipes) == 10
        assert sum({"dairy_free", "gluten_free"}.issubset(item["tags"]) for item in recipes) == expected_dual
        assert sum(item["prep_time_minutes"] + item["cook_time_minutes"] <= 20 for item in recipes) >= 9
        for item in recipes:
            assert set(item["equipment"]) <= EQUIPMENT
            assert len(item["steps"]) >= 3 and all(step["instruction"].strip() for step in item["steps"])
            foods = {ingredient["source_food_id"] for ingredient in item["ingredients"]}
            assert foods <= DEV_FOOD_ALLERGEN_REVIEWS.keys()
            assert "halal" not in item["tags"]
            if "gluten_free" in item["tags"]:
                assert "dev_oats" not in foods
            if "dairy_free" in item["tags"]:
                assert not foods & {"dev_milk", "dev_greek_yogurt"}
            if "vegan" in item["tags"]:
                assert not foods & {"dev_egg", "dev_milk", "dev_greek_yogurt", "dev_salmon", "dev_chicken_breast"}
            if "pescatarian" in item["tags"]:
                assert "dev_chicken_breast" not in foods
    assert sum("snack" in item["tags"] for item in DEV_RECIPE_SEED_DATA) == 1


def test_seed_reviews_and_complete_nutrition_are_persisted_and_repeatable(meal_plan_db, catalog):
    db, _, _ = meal_plan_db
    original_ids = {recipe.name: recipe.id for recipe in catalog_recipes(db)}
    seeded = seed_development_recipes(db)
    assert seeded.inserted == 0 and seeded.updated == 41
    assert {recipe.name: recipe.id for recipe in catalog_recipes(db)} == original_ids
    for code, (expected_codes, _) in DEV_FOOD_ALLERGEN_REVIEWS.items():
        food = db.query(Food).filter_by(source_food_id=code).one()
        assert food.allergen_codes == expected_codes
        assert food.allergen_reference.strip() and "Cross-contact not assessed" in food.allergen_reference
        assert {nutrient.nutrient_code for nutrient in food.nutrients} == set(RECIPE_NUTRIENT_DEFINITION_BY_CODE)
    for recipe in catalog_recipes(db):
        calculated = calculate_recipe_nutrients(recipe.ingredients, recipe.servings)
        assert {nutrient.nutrient_code for nutrient in recipe.nutrients} == set(RECIPE_NUTRIENT_DEFINITION_BY_CODE)
        expected = {nutrient.code: nutrient for nutrient in calculated}
        for nutrient in recipe.nutrients:
            assert nutrient.complete and nutrient.missing_ingredient_count == 0
            assert nutrient.unit == RECIPE_NUTRIENT_DEFINITION_BY_CODE[nutrient.nutrient_code].unit
            assert nutrient.per_serving_amount == expected[nutrient.nutrient_code].per_serving_amount


def test_exact_frontend_profile_creates_and_persists_four_required_slots(p0_user):
    db, token, _, _ = p0_user
    for meal_type in MEAL_TYPES:
        preview = request("POST", "/recipes/candidates/preview", token,
                          {"meal_type": meal_type, "require_complete_nutrition": True})
        assert preview.status_code == 200, preview.text
        assert preview.json()["total_eligible"] >= 5
    response = create_plan(token, four_slots())
    assert response.status_code == 201, response.text
    plan = response.json()
    assert [meal["meal_type"] for meal in plan["meals"]] == list(MEAL_TYPES)
    assert len({meal["recipe_id"] for meal in plan["meals"]}) == 4
    for meal in plan["meals"]:
        recipe = db.get(Recipe, UUID(meal["recipe_id"]))
        assert {"dairy_free", "gluten_free"}.issubset(link.tag.name for link in recipe.tag_links)
        assert recipe.total_time_minutes <= 20
        assert {item.equipment for item in recipe.equipment} <= {"stovetop", "oven", "air_fryer"}
        assert set(meal["nutrition"]) == set(RECIPE_NUTRIENT_DEFINITION_BY_CODE)
    persisted = get_plan(token, plan["meal_plan_id"])
    assert persisted.status_code == 200 and persisted.json()["meals"] == plan["meals"]
    # The migrated check must accept pre_workout but continue rejecting unknown types.
    item = db.get(MealPlanItem, UUID(plan["meals"][2]["id"]))
    item.meal_type = "invalid"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.get(MealPlanItem, item.id).meal_type == "pre_workout"


def test_pre_workout_crud_tag_and_candidate_equipment_filter(p0_user):
    db, token, _, track_recipe = p0_user
    payload = recipe_payload(db, f"Pre-workout CRUD {uuid4().hex}",
                             ["pre_workout", "dairy_free", "gluten_free"],
                             ["dev_cooked_rice"], equipment=["slow_cooker"])
    recipe = create_recipe(db, token, track_recipe, payload)
    preview = request("POST", "/recipes/candidates/preview", token, {"meal_type": "pre_workout"})
    excluded = {item["recipe_id"]: item["reasons"] for item in preview.json()["excluded"]}
    assert "missing_required_equipment" in excluded[recipe["id"]]
    updated = request("PATCH", f"/recipes/{recipe['id']}", token, {"equipment": ["stovetop"]})
    assert updated.status_code == 200, updated.text
    preview = request("POST", "/recipes/candidates/preview", token, {"meal_type": "pre_workout"})
    assert recipe["id"] in {item["recipe_id"] for item in preview.json()["candidates"]}


@pytest.mark.parametrize("codes,reference,reason", [
    ([], "Explicit modeled banana ingredient-content review", None),
    (["peanut"], "Explicit modeled conflict fixture review", "allergy_conflict"),
    (None, None, "allergy_metadata_missing"),
    ([], "", "allergy_metadata_missing"),
])
def test_reviewed_metadata_is_enforced_by_candidates_and_solver(p0_user, codes, reference, reason):
    db, token, _, _ = p0_user
    request("PATCH", "/users/profile", token, {"allergies": ["peanuts"]})
    chosen = db.query(Recipe).filter_by(name="Banana Rice Energy Bowl", source=DEV_RECIPE_SEED_SOURCE).one()
    excluded_ids = [str(recipe.id) for recipe in db.query(Recipe).all() if recipe.id != chosen.id]
    banana = db.query(Food).filter_by(source_food_id="dev_banana").one()
    original_codes, original_reference = banana.allergen_codes, banana.allergen_reference
    try:
        banana.allergen_codes, banana.allergen_reference = codes, reference
        db.commit()
        body = {"meal_type": "pre_workout", "excluded_recipe_ids": excluded_ids}
        preview = request("POST", "/recipes/candidates/preview", token, body)
        assert preview.status_code == 200, preview.text
        assert "Cross-contact" in preview.json()["allergy_limitation"]
        solve_body = {"meal_slots": [{"meal_type": "pre_workout", "required": True}],
                      "excluded_recipe_ids": excluded_ids, "require_complete_nutrition": False}
        solve = request("POST", "/meal-plans/solve/preview", token, solve_body)
        assert solve.status_code == 200, solve.text
        if reason:
            rejection = next(item for item in preview.json()["excluded"] if item["recipe_id"] == str(chosen.id))
            assert reason in rejection["reasons"]
            assert not preview.json()["candidates"] and solve.json()["status"] == "infeasible"
        else:
            assert [item["recipe_id"] for item in preview.json()["candidates"]] == [str(chosen.id)]
            assert solve.json()["meals"][0]["recipe_id"] == str(chosen.id)
    finally:
        banana.allergen_codes, banana.allergen_reference = original_codes, original_reference
        db.commit()


def test_allergy_constrained_four_slot_plan_uses_only_reviewed_nonconflicting_foods(p0_user):
    db, token, _, _ = p0_user
    request("PATCH", "/users/profile", token, {"allergies": ["eggs", "fish", "dairy"]})
    result = create_plan(token, four_slots())
    assert result.status_code == 201, result.text
    assert [meal["meal_type"] for meal in result.json()["meals"]] == list(MEAL_TYPES)
    for meal in result.json()["meals"]:
        recipe = db.get(Recipe, UUID(meal["recipe_id"]))
        for ingredient in recipe.ingredients:
            assert ingredient.food.allergen_codes == []
            assert ingredient.food.allergen_reference.strip()


def test_selected_recipe_swap_preserves_pre_workout_and_rejects_ineligible_recipe(p0_user):
    db, token, _, _ = p0_user
    plan = create_plan(token, four_slots()).json()
    meal = next(item for item in plan["meals"] if item["meal_type"] == "pre_workout")
    preview = request("POST", "/recipes/candidates/preview", token,
                      {"meal_type": "pre_workout", "excluded_recipe_ids": [item["recipe_id"] for item in plan["meals"]]}).json()
    replacement = preview["candidates"][0]["recipe_id"]
    url = f"/meal-plans/{plan['meal_plan_id']}/items/{meal['id']}/swap"
    response = request("POST", url, token, {"recipe_id": replacement})
    assert response.status_code == 200, response.text
    swapped = next(item for item in response.json()["meals"] if item["id"] == meal["id"])
    assert swapped["recipe_id"] == replacement and swapped["meal_type"] == "pre_workout"
    wrong_type = plan["meals"][0]["recipe_id"]
    assert request("POST", url, token, {"recipe_id": wrong_type}).json()["error"]["code"] == "NO_SWAP_CANDIDATE"
    # Direct selection still passes through the allergy filter.
    food = db.get(Recipe, UUID(meal["recipe_id"])).ingredients[0].food
    original_codes, original_reference = food.allergen_codes, food.allergen_reference
    try:
        request("PATCH", "/users/profile", token, {"allergies": ["peanuts"]})
        food.allergen_codes, food.allergen_reference = ["peanut"], "Explicit conflict test review"
        db.commit()
        assert request("POST", url, token, {"recipe_id": meal["recipe_id"]}).status_code == 422
    finally:
        food.allergen_codes, food.allergen_reference = original_codes, original_reference
        db.commit()


def test_recipe_player_and_plan_log_listing_support_pre_workout(p0_user):
    _, token, track_email, _ = p0_user
    plan = create_plan(token, four_slots()).json()
    meal = plan["meals"][2]
    prefix = f"/meal-plans/{plan['meal_plan_id']}"
    started = request("POST", f"{prefix}/items/{meal['id']}/execution-session", token)
    assert started.status_code in (200, 201), started.text
    assert len(started.json()["steps"]) >= 3
    assert request("GET", f"{prefix}/logs", token).json() == []
    logged = request("POST", f"{prefix}/items/{meal['id']}/log", token, {"type": "ate_as_planned"})
    assert logged.status_code in (200, 201), logged.text
    logs = request("GET", f"{prefix}/logs", token)
    assert logs.status_code == 200 and len(logs.json()) == 1
    assert logs.json()[0]["meal_plan_item_id"] == meal["id"]
    other = register_and_login(track_email(unique_email("p0-other")))
    assert request("GET", f"{prefix}/logs", other).status_code == 404
    assert request("GET", f"{prefix}/logs").status_code == 401
    assert request("DELETE", f"{prefix}/items/{meal['id']}/log", token).status_code == 204
    assert request("GET", f"{prefix}/logs", token).json() == []


def test_snack_listing_stays_separate_owned_and_date_filtered(p0_user):
    _, token, track_email, _ = p0_user
    body = {"log_date": "2026-10-26", "name": "Separate snack", "calories": 100,
            "protein_g": 2, "carbs_g": 20, "fat_g": 1}
    created = request("POST", "/nutrition/snacks", token, body)
    assert created.status_code == 201, created.text
    response = request("GET", "/nutrition/snacks?date=2026-10-26", token)
    assert response.status_code == 200 and response.json() == [created.json()]
    assert request("GET", "/nutrition/snacks?date=2026-10-25", token).json() == []
    assert request("GET", "/nutrition/snacks?offset=1", token).json() == []
    assert request("GET", "/nutrition/snacks?limit=0", token).status_code == 422
    other = register_and_login(track_email(unique_email("p0-snack-other")))
    assert request("GET", "/nutrition/snacks", other).json() == []
    assert request("GET", "/nutrition/snacks").status_code == 401
    assert request("DELETE", f"/nutrition/snacks/{created.json()['id']}", token).status_code == 204
    assert request("GET", "/nutrition/snacks", token).json() == []
