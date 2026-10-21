from uuid import uuid4

import pytest

from app.services.dietary_service import review_food_allergens
from app.core.exceptions import APIErrorException
from app.models.food import Food, FoodNutrient
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.core.enums import FoodSource
from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import create_profile


def recipe_body(food_id, tags):
    return {"name": f"Diet test {uuid4().hex}", "servings": 1, "prep_time_minutes": 5, "cook_time_minutes": 0,
            "difficulty": "easy", "tags": tags, "equipment": [], "ingredients": [{"food_id": food_id, "quantity_grams": 100}], "steps": []}


def test_diet_tags_and_reviewed_allergens_flow_into_candidates_and_solver(tracking_user):
    db, token = tracking_user
    create_profile(token, allergies=["peanuts"], dietary_restrictions=["halal", "pescatarian"])
    food = Food(name=f"Reviewed test food {uuid4().hex}", source=FoodSource.INTERNAL, category="test")
    db.add(food)
    db.flush()
    for code, definition in RECIPE_NUTRIENT_DEFINITION_BY_CODE.items():
        db.add(FoodNutrient(food_id=food.id, nutrient_code=code, nutrient_name=definition.name,
                           amount={"calories": 100, "protein": 10, "carbohydrates": 10, "fat": 2}.get(code, 1), unit=definition.unit))
    db.commit()
    recipe_ids = []
    try:
        for tags in (["dinner", "halal", "pescatarian"], ["dinner", "halal"], ["dinner", "pescatarian"]):
            result = request("POST", "/recipes", token, recipe_body(str(food.id), tags))
            assert result.status_code == 201, result.text
            recipe_ids.append(result.json()["id"])
        def preview():
            return request("POST", "/recipes/candidates/preview", token, {"meal_type": "dinner"}).json()
        missing = preview()
        assert next(item for item in missing["excluded"] if item["recipe_id"] == recipe_ids[0])["reasons"] == ["allergy_metadata_missing"]
        review_food_allergens(db, food, ["peanut"], "Test fixture reviewed metadata")
        assert next(item for item in preview()["excluded"] if item["recipe_id"] == recipe_ids[0])["reasons"] == ["allergy_conflict"]
        review_food_allergens(db, food, [], "Test fixture reviewed metadata")
        eligible = preview()
        assert {item["recipe_id"] for item in eligible["candidates"]} == {recipe_ids[0]}
        assert "Cross-contact" in eligible["allergy_limitation"]
        solved = request("POST", "/meal-plans", token,
            {"plan_date": "2026-03-01", "meal_slots": [{"meal_type": "dinner"}], "require_complete_nutrition": True})
        assert solved.status_code == 201, solved.text
        assert solved.json()["meals"][0]["recipe_id"] == recipe_ids[0]
        assert all(next(item for item in eligible["excluded"] if item["recipe_id"] == rid)["reasons"] == ["dietary_restriction_mismatch"] for rid in recipe_ids[1:])
        request("PATCH", "/users/profile", token, {"allergies": ["unmapped allergy"]})
        assert not preview()["candidates"]
        solve = request("POST", "/meal-plans/solve/preview", token, {"meal_slots": [{"meal_type": "dinner"}], "require_complete_nutrition": False})
        assert solve.status_code == 200 and solve.json()["status"] == "infeasible"
        with pytest.raises(APIErrorException):
            review_food_allergens(db, food, ["invented"], "source")
    finally:
        from app.models.recipe import Recipe
        from app.models.meal_plan import MealPlan
        from uuid import UUID
        # Delete only this test user's plan before removing its private fixture recipes.
        owner_id = UUID(request("GET", "/auth/me", token).json()["id"])
        db.query(MealPlan).filter_by(user_id=owner_id).delete(synchronize_session=False)
        db.commit()
        for recipe_id in recipe_ids:
            db.delete(db.get(Recipe, UUID(recipe_id)))
        db.commit()
        db.delete(food)
        db.commit()
