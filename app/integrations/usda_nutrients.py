from dataclasses import dataclass
from math import isfinite
from typing import Any

from app.integrations.usda import (
    USDAMalformedResponseError,
    USDANoSupportedNutrientsError,
)


@dataclass(frozen=True)
class USDANutrientMapping:
    usda_ids: tuple[int, ...]
    usda_names: tuple[str, ...]
    code: str
    name: str
    unit: str


USDA_NUTRIENT_MAPPINGS: tuple[USDANutrientMapping, ...] = (
    USDANutrientMapping((1008,), ("Energy",), "calories", "Calories", "kcal"),
    USDANutrientMapping((1003,), ("Protein",), "protein", "Protein", "g"),
    USDANutrientMapping((1005,), ("Carbohydrate, by difference",), "carbohydrates", "Carbohydrates", "g"),
    USDANutrientMapping((1004,), ("Total lipid (fat)",), "fat", "Fat", "g"),
    USDANutrientMapping((1079,), ("Fiber, total dietary",), "fiber", "Fiber", "g"),
    USDANutrientMapping((1087,), ("Calcium, Ca",), "calcium", "Calcium", "mg"),
    USDANutrientMapping((1089,), ("Iron, Fe",), "iron", "Iron", "mg"),
    USDANutrientMapping((1090,), ("Magnesium, Mg",), "magnesium", "Magnesium", "mg"),
    USDANutrientMapping((1092,), ("Potassium, K",), "potassium", "Potassium", "mg"),
    USDANutrientMapping((1093,), ("Sodium, Na",), "sodium", "Sodium", "mg"),
    USDANutrientMapping((1106,), ("Vitamin A, RAE",), "vitamin_a", "Vitamin A", "mcg RAE"),
    USDANutrientMapping((1162,), ("Vitamin C, total ascorbic acid",), "vitamin_c", "Vitamin C", "mg"),
    USDANutrientMapping((1114,), ("Vitamin D (D2 + D3)",), "vitamin_d", "Vitamin D", "mcg"),
    USDANutrientMapping((1178,), ("Vitamin B-12",), "vitamin_b12", "Vitamin B12", "mcg"),
    USDANutrientMapping((1190,), ("Folate, DFE",), "folate", "Folate", "mcg DFE"),
)

USDA_NUTRIENT_MAPPING_BY_ID = {
    usda_id: mapping
    for mapping in USDA_NUTRIENT_MAPPINGS
    for usda_id in mapping.usda_ids
}

USDA_NUTRIENT_MAPPING_BY_NAME = {
    name.strip().lower(): mapping
    for mapping in USDA_NUTRIENT_MAPPINGS
    for name in mapping.usda_names
}

SUPPORTED_USDA_NUTRIENT_CODES = tuple(mapping.code for mapping in USDA_NUTRIENT_MAPPINGS)

UNIT_ALIASES = {
    "kcal": "kcal",
    "calorie": "kcal",
    "calories": "kcal",
    "kj": "kJ",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "ug": "mcg",
    "mcg": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
}

MASS_UNIT_TO_GRAMS = {
    "g": 1.0,
    "mg": 0.001,
    "mcg": 0.000001,
}

TARGET_UNIT_BASE = {
    "mcg RAE": "mcg",
    "mcg DFE": "mcg",
}


def normalize_usda_nutrients(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fdc_id = str(payload.get("fdcId", ""))
    raw_nutrients = payload.get("foodNutrients")
    if not isinstance(raw_nutrients, list):
        raise USDAMalformedResponseError("foodNutrients is missing or is not a list")

    normalized: dict[str, dict[str, Any]] = {}

    for item in raw_nutrients:
        if not isinstance(item, dict):
            raise USDAMalformedResponseError("foodNutrients item is not an object")

        mapping = find_mapping(item)
        if mapping is None or mapping.code in normalized:
            continue

        amount = extract_amount(item)
        if amount is None:
            continue

        unit = extract_unit(item)
        converted_amount = convert_unit(amount=amount, source_unit=unit, target_unit=mapping.unit)
        if converted_amount is None:
            continue

        normalized[mapping.code] = {
            "code": mapping.code,
            "name": mapping.name,
            "amount": round(converted_amount, 6),
            "unit": mapping.unit,
        }

    if not normalized:
        raise USDANoSupportedNutrientsError(fdc_id=fdc_id)

    return list(normalized.values())


def find_mapping(item: dict[str, Any]) -> USDANutrientMapping | None:
    nutrient = item.get("nutrient")
    nutrient = nutrient if isinstance(nutrient, dict) else {}

    raw_id = item.get("nutrientId", nutrient.get("id"))
    try:
        nutrient_id = int(raw_id)
    except (TypeError, ValueError):
        nutrient_id = None

    if nutrient_id is not None and nutrient_id in USDA_NUTRIENT_MAPPING_BY_ID:
        return USDA_NUTRIENT_MAPPING_BY_ID[nutrient_id]

    raw_name = item.get("nutrientName", nutrient.get("name"))
    if isinstance(raw_name, str):
        return USDA_NUTRIENT_MAPPING_BY_NAME.get(raw_name.strip().lower())

    return None


def extract_amount(item: dict[str, Any]) -> float | None:
    raw_amount = item.get("amount")
    if raw_amount is None:
        raw_amount = item.get("value")
    if raw_amount is None:
        return None

    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise USDAMalformedResponseError("nutrient amount is not numeric") from exc

    if not isfinite(amount) or amount < 0:
        raise USDAMalformedResponseError("nutrient amount is invalid")

    return amount


def extract_unit(item: dict[str, Any]) -> str | None:
    nutrient = item.get("nutrient")
    nutrient = nutrient if isinstance(nutrient, dict) else {}
    raw_unit = item.get("unitName", nutrient.get("unitName"))
    return raw_unit if isinstance(raw_unit, str) else None


def convert_unit(amount: float, source_unit: str | None, target_unit: str) -> float | None:
    source = canonical_unit(source_unit)
    target = canonical_unit(TARGET_UNIT_BASE.get(target_unit, target_unit))
    if source is None or target is None:
        return None

    if source == target:
        return amount

    if source == "kJ" and target == "kcal":
        return amount * 0.239005736

    if source in MASS_UNIT_TO_GRAMS and target in MASS_UNIT_TO_GRAMS:
        amount_in_grams = amount * MASS_UNIT_TO_GRAMS[source]
        return amount_in_grams / MASS_UNIT_TO_GRAMS[target]

    return None


def canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None

    cleaned = unit.strip().replace("µ", "u").replace("μ", "u").lower()
    return UNIT_ALIASES.get(cleaned)
