"""Explicit ingredient-content review of the defined development fixtures.

These specifications describe modeled foods, not verified retail products. No cross-contact
assessment or halal certification is implied. Generic oats are deliberately NOT gluten-free.
The nutrient fixtures remain separate and retain their existing approximate values.
"""

ALLERGEN_REVIEW_SOURCE = "https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/food-allergies"

# Each list was reviewed against the fixture's full ingredient specification, not its name.
DEV_FOOD_ALLERGEN_REVIEWS = {
    "dev_chicken_breast": ([], "Cooked chicken breast only; no marinade, breading, sauce, or additives."),
    "dev_cooked_rice": ([], "White rice cooked in water only; no stock, butter, or seasoning mix."),
    "dev_egg": (["egg"], "Whole hen egg; shell removed; no other ingredients."),
    "dev_oats": ([], "Plain rolled oats only; no additives. Gluten cross-contact is unknown; not gluten-free certified."),
    "dev_milk": (["milk"], "Plain cow milk; no flavors or added cereal ingredients."),
    "dev_greek_yogurt": (["milk"], "Plain cultured cow milk yogurt; no fruit, granola, gelatin, or flavorings."),
    "dev_spinach": ([], "Raw washed spinach leaves only; no dressing or processing ingredients."),
    "dev_broccoli": ([], "Raw washed broccoli florets only; no sauce or coating."),
    "dev_banana": ([], "Peeled raw banana flesh only; no processing ingredients."),
    "dev_salmon": (["fish"], "Raw unseasoned salmon fillet only; no marinade, coating, or glaze."),
    "dev_olive_oil": ([], "Pure olive oil only; no blended oils, flavorings, or additives."),
    "dev_potato": ([], "Raw washed potato only; no butter, flour, seasoning mix, or other ingredients."),
}


def seed_allergen_review(source_food_id):
    codes, specification = DEV_FOOD_ALLERGEN_REVIEWS[source_food_id]
    reference = f"Kcalm development fixture content review 2026-10-26. {specification} Reference: {ALLERGEN_REVIEW_SOURCE}. Cross-contact not assessed."
    return list(codes), reference
