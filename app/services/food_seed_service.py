from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import FoodSource
from app.models.food import Food, FoodNutrient, FoodServing
from app.seed_data.foods import DEV_FOOD_SEED_DATA
from app.seed_data.allergen_reviews import seed_allergen_review
from app.services.dietary_service import apply_food_allergen_review


@dataclass(frozen=True)
class FoodSeedResult:
    inserted: int
    updated: int
    total: int


def seed_development_foods(db: Session) -> FoodSeedResult:
    inserted = 0
    updated = 0

    for item in DEV_FOOD_SEED_DATA:
        food = (
            db.query(Food)
            .filter(
                Food.source == FoodSource.INTERNAL,
                Food.source_food_id == item["source_food_id"],
            )
            .one_or_none()
        )
        if food is None:
            food = Food(
                source=FoodSource.INTERNAL,
                source_food_id=item["source_food_id"],
            )
            db.add(food)
            inserted += 1
        else:
            updated += 1

        food.name = item["name"]
        food.category = item["category"]
        food.description = item["description"]
        codes, reference = seed_allergen_review(item["source_food_id"])
        apply_food_allergen_review(food, codes, reference)
        db.flush()

        db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).delete(
            synchronize_session=False
        )
        db.query(FoodServing).filter(FoodServing.food_id == food.id).delete(
            synchronize_session=False
        )
        db.flush()

        for nutrient in item["nutrients"]:
            db.add(
                FoodNutrient(
                    food_id=food.id,
                    nutrient_code=nutrient["code"],
                    nutrient_name=nutrient["name"],
                    amount=nutrient["amount"],
                    unit=nutrient["unit"],
                )
            )

        for serving in item["servings"]:
            db.add(
                FoodServing(
                    food_id=food.id,
                    serving_name=serving["name"],
                    grams=serving["grams"],
                )
            )

    db.commit()
    return FoodSeedResult(
        inserted=inserted,
        updated=updated,
        total=len(DEV_FOOD_SEED_DATA),
    )
