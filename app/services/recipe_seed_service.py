from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.enums import FoodSource
from app.core.exceptions import APIErrorException
from app.models.food import Food
from app.models.recipe import Recipe
from app.schemas.recipe import (
    RecipeCreateRequest,
    RecipeIngredientRequest,
    RecipeStepRequest,
    RecipeUpdateRequest,
)
from app.seed_data.recipes import DEV_RECIPE_SEED_DATA, DEV_RECIPE_SEED_SOURCE
from app.services.food_seed_service import seed_development_foods
from app.services.recipe_service import create_recipe, update_recipe


@dataclass(frozen=True)
class RecipeSeedResult:
    inserted: int
    updated: int
    total: int


def seed_development_recipes(db: Session) -> RecipeSeedResult:
    seed_development_foods(db)
    food_by_source_id = load_development_foods(db)
    inserted = 0
    updated = 0

    for item in DEV_RECIPE_SEED_DATA:
        payload = recipe_payload_from_seed(item=item, food_by_source_id=food_by_source_id)
        existing_recipe = (
            db.query(Recipe)
            .filter(
                Recipe.source == DEV_RECIPE_SEED_SOURCE,
                Recipe.name == item["name"],
                Recipe.active.is_(True),
            )
            .one_or_none()
        )

        if existing_recipe is None:
            create_recipe(db=db, payload=payload, source=DEV_RECIPE_SEED_SOURCE)
            inserted += 1
        else:
            update_recipe(
                db=db,
                recipe_id=existing_recipe.id,
                payload=RecipeUpdateRequest(**payload.model_dump()),
            )
            updated += 1

    return RecipeSeedResult(
        inserted=inserted,
        updated=updated,
        total=len(DEV_RECIPE_SEED_DATA),
    )


def load_development_foods(db: Session) -> dict[str, Food]:
    foods = (
        db.query(Food)
        .filter(Food.source == FoodSource.INTERNAL)
        .all()
    )
    food_by_source_id = {
        food.source_food_id: food
        for food in foods
        if food.source_food_id is not None
    }
    required_food_ids = {
        ingredient["source_food_id"]
        for recipe in DEV_RECIPE_SEED_DATA
        for ingredient in recipe["ingredients"]
    }
    missing = sorted(required_food_ids - set(food_by_source_id))
    if missing:
        raise APIErrorException(
            status_code=500,
            code="RECIPE_SEED_FOOD_MISSING",
            message="Development recipe seed references missing development foods.",
            details={"source_food_ids": missing},
        )
    return food_by_source_id


def recipe_payload_from_seed(
    item: dict,
    food_by_source_id: dict[str, Food],
) -> RecipeCreateRequest:
    return RecipeCreateRequest(
        name=item["name"],
        description=item["description"],
        servings=Decimal(str(item["servings"])),
        prep_time_minutes=item["prep_time_minutes"],
        cook_time_minutes=item["cook_time_minutes"],
        difficulty=item["difficulty"],
        instructions_summary=item["instructions_summary"],
        ingredients=[
            RecipeIngredientRequest(
                food_id=food_by_source_id[ingredient["source_food_id"]].id,
                quantity_grams=Decimal(str(ingredient["quantity_grams"])),
                display_quantity=ingredient.get("display_quantity"),
                display_unit=ingredient.get("display_unit"),
                preparation_note=ingredient.get("preparation_note"),
                position=index,
            )
            for index, ingredient in enumerate(item["ingredients"], start=1)
        ],
        steps=[
            RecipeStepRequest(
                position=index,
                instruction=step["instruction"],
                phase=step.get("phase", "cook"),
                duration_seconds=step.get("duration_seconds"),
                timer=step.get("timer", False),
                timer_required=step.get("timer_required"),
                timer_seconds=step.get("timer_seconds"),
            )
            for index, step in enumerate(item["steps"], start=1)
        ],
        tags=item["tags"],
        equipment=item["equipment"],
    )
