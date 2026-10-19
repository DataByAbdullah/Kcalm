from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from app.core.exceptions import APIErrorException


@dataclass(frozen=True)
class NutrientDefinition:
    code: str
    name: str
    unit: str


@dataclass(frozen=True)
class CalculatedRecipeNutrient:
    code: str
    name: str
    total_amount: float
    per_serving_amount: float
    unit: str
    missing_ingredient_count: int
    complete: bool


class IngredientLike(Protocol):
    quantity_grams: Decimal
    food: object


RECIPE_NUTRIENT_DEFINITIONS: tuple[NutrientDefinition, ...] = (
    NutrientDefinition("calories", "Calories", "kcal"),
    NutrientDefinition("protein", "Protein", "g"),
    NutrientDefinition("carbohydrates", "Carbohydrates", "g"),
    NutrientDefinition("fat", "Fat", "g"),
    NutrientDefinition("fiber", "Fiber", "g"),
    NutrientDefinition("calcium", "Calcium", "mg"),
    NutrientDefinition("iron", "Iron", "mg"),
    NutrientDefinition("magnesium", "Magnesium", "mg"),
    NutrientDefinition("potassium", "Potassium", "mg"),
    NutrientDefinition("sodium", "Sodium", "mg"),
    NutrientDefinition("vitamin_a", "Vitamin A", "mcg RAE"),
    NutrientDefinition("vitamin_c", "Vitamin C", "mg"),
    NutrientDefinition("vitamin_d", "Vitamin D", "mcg"),
    NutrientDefinition("vitamin_b12", "Vitamin B12", "mcg"),
    NutrientDefinition("folate", "Folate", "mcg DFE"),
)

RECIPE_NUTRIENT_DEFINITION_BY_CODE = {
    definition.code: definition for definition in RECIPE_NUTRIENT_DEFINITIONS
}


def calculate_recipe_nutrients(
    ingredients: list[IngredientLike],
    servings: Decimal,
) -> list[CalculatedRecipeNutrient]:
    if servings <= 0:
        raise APIErrorException(
            status_code=422,
            code="INVALID_RECIPE_SERVINGS",
            message="Recipe servings must be greater than zero.",
        )
    if not ingredients:
        raise APIErrorException(
            status_code=422,
            code="RECIPE_REQUIRES_INGREDIENTS",
            message="Recipe must include at least one ingredient.",
        )

    results: list[CalculatedRecipeNutrient] = []
    for definition in RECIPE_NUTRIENT_DEFINITIONS:
        total = Decimal("0")
        missing_count = 0

        for ingredient in ingredients:
            nutrients_by_code = {
                nutrient.nutrient_code: nutrient
                for nutrient in getattr(ingredient.food, "nutrients", [])
            }
            food_nutrient = nutrients_by_code.get(definition.code)
            if food_nutrient is None:
                missing_count += 1
                continue

            if food_nutrient.unit != definition.unit:
                raise APIErrorException(
                    status_code=422,
                    code="RECIPE_NUTRIENT_UNIT_MISMATCH",
                    message="Food nutrient unit does not match the recipe nutrient definition.",
                    details={
                        "nutrient_code": definition.code,
                        "expected_unit": definition.unit,
                        "actual_unit": food_nutrient.unit,
                    },
                )

            nutrient_amount = Decimal(str(food_nutrient.amount))
            ingredient_grams = Decimal(str(ingredient.quantity_grams))
            total += nutrient_amount * ingredient_grams / Decimal("100")

        per_serving = total / servings
        results.append(
            CalculatedRecipeNutrient(
                code=definition.code,
                name=definition.name,
                total_amount=decimal_to_float(total),
                per_serving_amount=decimal_to_float(per_serving),
                unit=definition.unit,
                missing_ingredient_count=missing_count,
                complete=missing_count == 0,
            )
        )

    return results


def decimal_to_float(value: Decimal) -> float:
    rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(rounded)
