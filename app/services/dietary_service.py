from app.core.exceptions import APIErrorException

ALLERGEN_CODES = {"peanut", "tree_nut", "milk", "egg", "fish", "shellfish", "soy", "wheat", "sesame"}
ALLERGEN_ALIASES = {
    "peanuts": {"peanut"}, "tree_nuts": {"tree_nut"}, "nuts": {"peanut", "tree_nut"},
    "dairy": {"milk"}, "eggs": {"egg"}, "soya": {"soy"},
}


def normalize_allergies(values):
    supported, unsupported = set(), set()
    for value in values:
        key = "_".join(value.strip().lower().split())
        if key in ALLERGEN_CODES:
            supported.add(key)
        elif key in ALLERGEN_ALIASES:
            supported.update(ALLERGEN_ALIASES[key])
        else:
            unsupported.add(key)
    return supported, unsupported


def review_food_allergens(db, food, codes, reference):
    from app.services.tracking_common import commit_tracking
    if set(codes) - ALLERGEN_CODES or not reference.strip() or len(reference) > 1000:
        raise APIErrorException(422, "INVALID_ALLERGEN_REVIEW", "Use canonical allergen codes and a source reference.")
    food.allergen_codes = sorted(set(codes))
    food.allergen_reference = reference.strip()
    commit_tracking(db)
