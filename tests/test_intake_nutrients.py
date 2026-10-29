from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.enums import FoodSource
from app.core.exceptions import APIErrorException
from app.models.food import Food, FoodNutrient
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE, calculate_recipe_nutrients
from app.seed_data.foods import DEV_FOOD_SEED_DATA
from tests.test_meal_logs import (
    create_user_plan, first_meal, intake_history, log_item, meal_log_db,
)
from tests.test_weight_logs import request


def test_each_food_fixture_explicitly_models_added_sugar():
    assert len(DEV_FOOD_SEED_DATA) == 12
    for food in DEV_FOOD_SEED_DATA:
        rows = {row["code"]: row for row in food["nutrients"]}
        assert rows["added_sugar"] == {"code": "added_sugar", "name": "Added Sugar", "amount": 0, "unit": "g"}
        assert rows.keys() == RECIPE_NUTRIENT_DEFINITION_BY_CODE.keys()


def ingredient(grams, fiber, added_sugar):
    rows = [SimpleNamespace(nutrient_code=code, amount=0, unit=definition.unit)
            for code, definition in RECIPE_NUTRIENT_DEFINITION_BY_CODE.items()]
    by_code = {row.nutrient_code: row for row in rows}
    by_code["fiber"].amount = fiber
    by_code["added_sugar"].amount = added_sugar
    by_code["carbohydrates"].amount = 50
    return SimpleNamespace(quantity_grams=Decimal(str(grams)), food=SimpleNamespace(nutrients=rows))


def test_recipe_rolls_up_fiber_and_added_sugar_without_using_carbohydrates():
    ingredients = [ingredient(150, 4, 3), ingredient(50, 2, 1)]
    calculated = {row.code: row for row in calculate_recipe_nutrients(ingredients, Decimal("2"))}
    assert len(calculated) == 16 and all(row.complete for row in calculated.values())
    assert calculated["fiber"].total_amount == 7
    assert calculated["fiber"].per_serving_amount == 3.5
    assert calculated["added_sugar"].total_amount == 5
    assert calculated["added_sugar"].per_serving_amount == 2.5
    assert calculated["carbohydrates"].total_amount == 100


def test_missing_added_sugar_remains_incomplete_not_a_known_zero():
    item = ingredient(100, 3, 0)
    item.food.nutrients = [row for row in item.food.nutrients if row.nutrient_code != "added_sugar"]
    rows = {row.code: row for row in calculate_recipe_nutrients([item], Decimal("1"))}
    assert not rows["added_sugar"].complete and rows["added_sugar"].missing_ingredient_count == 1


def test_added_sugar_unit_mismatch_is_rejected():
    item = ingredient(100, 3, 2)
    next(row for row in item.food.nutrients if row.nutrient_code == "added_sugar").unit = "mg"
    with pytest.raises(APIErrorException) as error:
        calculate_recipe_nutrients([item], Decimal("1"))
    assert error.value.code == "RECIPE_NUTRIENT_UNIT_MISMATCH"


def tracked_food(db, track_food, missing_added_sugar=False):
    food = Food(name="Structured nutrient test food", source=FoodSource.INTERNAL, category="test")
    db.add(food)
    db.flush()
    track_food(food.id)
    for code, definition in RECIPE_NUTRIENT_DEFINITION_BY_CODE.items():
        if missing_added_sugar and code == "added_sugar":
            continue
        amount = {"calories": 200, "protein": 4, "carbohydrates": 40, "fat": 2,
                  "fiber": 6, "added_sugar": 3}.get(code, 1)
        db.add(FoodNutrient(food_id=food.id, nutrient_code=code, nutrient_name=definition.name,
                            amount=amount, unit=definition.unit))
    db.commit()
    return food


def test_meal_plan_and_logs_and_food_snacks_preserve_nutrient_snapshots(meal_log_db):
    db, track_email, _, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-15")
    food = tracked_food(db, track_food)
    meal = first_meal(plan)
    assert all("added_sugar" in item["nutrition"] for item in plan["meals"])
    assert plan["daily_totals"]["added_sugar"] == 0
    planned_log = log_item(token, plan["meal_plan_id"], meal["id"], {"type": "ate_as_planned"})
    assert planned_log.status_code == 200
    assert next(row for row in planned_log.json()["nutrients"] if row["code"] == "added_sugar")["amount"] == 0
    corrected = log_item(token, plan["meal_plan_id"], plan["meals"][1]["id"],
                         {"type": "corrected", "source_type": "food", "food_id": str(food.id), "quantity_grams": 75})
    assert corrected.status_code == 200, corrected.text
    snack = request("POST", "/nutrition/snacks", token,
                    {"log_date": "2026-10-15", "food_id": str(food.id), "quantity_grams": 50})
    assert snack.status_code == 201
    intake = intake_history(token, "2026-10-14", "2026-10-16").json()
    assert intake[0]["fiber_g"] == intake[0]["added_sugar_g"] == 0
    assert intake[2]["fiber_g"] == intake[2]["added_sugar_g"] == 0
    assert intake[1]["fiber_g"] == pytest.approx(meal["nutrition"]["fiber"] + 7.5)
    assert intake[1]["added_sugar_g"] == 3.75
    for row in food.nutrients:
        if row.nutrient_code in ("fiber", "added_sugar"):
            row.amount = 99
    db.commit()
    assert intake_history(token, "2026-10-14", "2026-10-16").json() == intake


def test_custom_snack_and_mixed_day_nutrients_are_unavailable_until_removed(meal_log_db):
    db, track_email, _, track_food = meal_log_db
    token, _ = create_user_plan(db, track_email, plan_date="2026-10-16")
    food = tracked_food(db, track_food)
    base = {"log_date": "2026-10-17"}
    food_snack = request("POST", "/nutrition/snacks", token,
                         {**base, "food_id": str(food.id), "quantity_grams": 100}).json()
    custom = request("POST", "/nutrition/snacks", token,
                     {**base, "name": "Manual macros", "calories": 100, "protein_g": 2, "carbs_g": 20, "fat_g": 1}).json()
    mixed = intake_history(token, "2026-10-17", "2026-10-17").json()[0]
    assert mixed["calories"] == 300
    assert mixed["fiber_g"] is None and mixed["added_sugar_g"] is None
    request("DELETE", f"/nutrition/snacks/{food_snack['id']}", token)
    custom_only = intake_history(token, "2026-10-17", "2026-10-17").json()[0]
    assert custom_only["fiber_g"] is None and custom_only["added_sugar_g"] is None
    request("DELETE", f"/nutrition/snacks/{custom['id']}", token)
    empty = intake_history(token, "2026-10-17", "2026-10-17").json()[0]
    assert empty["fiber_g"] == empty["added_sugar_g"] == 0


def test_old_food_snapshot_missing_added_sugar_keeps_fiber_known(meal_log_db):
    db, track_email, _, track_food = meal_log_db
    token, _ = create_user_plan(db, track_email, plan_date="2026-10-18")
    food = tracked_food(db, track_food, missing_added_sugar=True)
    assert request("POST", "/nutrition/snacks", token,
                   {"log_date": "2026-10-19", "food_id": str(food.id), "quantity_grams": 100}).status_code == 201
    day = intake_history(token, "2026-10-19", "2026-10-19").json()[0]
    assert day["fiber_g"] == 6 and day["added_sugar_g"] is None


def test_corrected_recipe_does_not_snapshot_incomplete_added_sugar_as_zero(meal_log_db):
    db, track_email, track_recipe, track_food = meal_log_db
    token, plan = create_user_plan(db, track_email, plan_date="2026-10-20")
    food = tracked_food(db, track_food, missing_added_sugar=True)
    created = request("POST", "/recipes", token, {
        "name": f"Incomplete corrected recipe {uuid4().hex}", "servings": 1,
        "prep_time_minutes": 0, "cook_time_minutes": 0, "tags": ["breakfast"],
        "ingredients": [{"food_id": str(food.id), "quantity_grams": 100}], "steps": [],
    })
    assert created.status_code == 201, created.text
    recipe = created.json()
    track_recipe(recipe["id"])
    added = next(row for row in recipe["nutrition"]["per_serving"] if row["code"] == "added_sugar")
    assert not added["complete"] and added["missing_ingredient_count"] == 1
    corrected = log_item(token, plan["meal_plan_id"], first_meal(plan)["id"], {
        "type": "corrected", "source_type": "recipe", "recipe_id": recipe["id"], "servings": 1,
    })
    assert corrected.status_code == 200, corrected.text
    assert "added_sugar" in corrected.json()["missing_nutrient_codes"]
    assert not corrected.json()["nutrient_complete"]
    intake = intake_history(token, "2026-10-20", "2026-10-20").json()[0]
    assert intake["fiber_g"] == 6 and intake["added_sugar_g"] is None
