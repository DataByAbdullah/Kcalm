from dataclasses import dataclass
from math import isfinite
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.enums import FoodSource
from app.core.exceptions import APIErrorException
from app.integrations.usda import (
    USDAFoodDataCentralClient,
    USDAIntegrationError,
    USDAMalformedResponseError,
)
from app.integrations.usda_nutrients import normalize_usda_nutrients
from app.models.food import Food, FoodNutrient, FoodServing


@dataclass(frozen=True)
class USDAFoodSearchResult:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class USDAFoodImportResult:
    status: str
    food: Food


def search_usda_foods(
    client: USDAFoodDataCentralClient,
    query: str,
    page_size: int,
    page: int,
) -> USDAFoodSearchResult:
    try:
        payload = client.search_foods(
            query=query,
            page_size=page_size,
            page_number=page,
        )
        raw_foods = payload.get("foods")
        if not isinstance(raw_foods, list):
            raise USDAMalformedResponseError("foods is missing or is not a list")

        items = [normalize_search_item(item) for item in raw_foods]
        total = int(payload.get("totalHits", len(items)))
    except USDAIntegrationError as exc:
        raise usda_api_error(exc) from exc
    except (TypeError, ValueError) as exc:
        error = USDAMalformedResponseError("search pagination metadata is invalid")
        raise usda_api_error(error) from exc

    return USDAFoodSearchResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def import_usda_food_by_fdc_id(
    db: Session,
    client: USDAFoodDataCentralClient,
    fdc_id: int,
) -> USDAFoodImportResult:
    existing_food = get_existing_usda_food(db=db, fdc_id=fdc_id)
    if existing_food is not None:
        return USDAFoodImportResult(status="existing", food=existing_food)

    try:
        payload = client.get_food(fdc_id=fdc_id)
        normalized_food = normalize_usda_food(payload)
    except USDAIntegrationError as exc:
        raise usda_api_error(exc) from exc

    try:
        food = Food(
            name=normalized_food["name"],
            source=FoodSource.USDA,
            source_food_id=normalized_food["source_food_id"],
            category=normalized_food["category"],
            description=normalized_food["description"],
        )
        db.add(food)
        db.flush()

        for nutrient in normalized_food["nutrients"]:
            db.add(
                FoodNutrient(
                    food_id=food.id,
                    nutrient_code=nutrient["code"],
                    nutrient_name=nutrient["name"],
                    amount=nutrient["amount"],
                    unit=nutrient["unit"],
                )
            )

        for serving in normalized_food["servings"]:
            db.add(
                FoodServing(
                    food_id=food.id,
                    serving_name=serving["name"],
                    grams=serving["grams"],
                )
            )

        db.commit()
    except IntegrityError:
        db.rollback()
        existing_food = get_existing_usda_food(db=db, fdc_id=fdc_id)
        if existing_food is not None:
            return USDAFoodImportResult(status="existing", food=existing_food)
        raise APIErrorException(
            status_code=500,
            code="FOOD_IMPORT_FAILED",
            message="USDA food import failed because stored rows violated constraints.",
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=500,
            code="FOOD_IMPORT_FAILED",
            message="USDA food import failed before it could be saved.",
        ) from exc

    imported_food = get_existing_usda_food(db=db, fdc_id=fdc_id)
    if imported_food is None:
        raise APIErrorException(
            status_code=500,
            code="FOOD_IMPORT_FAILED",
            message="USDA food import completed but could not be reloaded.",
        )
    return USDAFoodImportResult(status="imported", food=imported_food)


def normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise USDAMalformedResponseError("foods item is not an object")

    try:
        fdc_id = int(item["fdcId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise USDAMalformedResponseError("search result fdcId is invalid") from exc

    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        raise USDAMalformedResponseError("search result description is invalid")

    data_type = item.get("dataType")
    brand_owner = item.get("brandOwner")

    return {
        "fdc_id": fdc_id,
        "description": description.strip(),
        "data_type": data_type.strip() if isinstance(data_type, str) else None,
        "brand_owner": brand_owner.strip() if isinstance(brand_owner, str) else None,
    }


def normalize_usda_food(payload: dict[str, Any]) -> dict[str, Any]:
    source_food_id = parse_fdc_id(payload)
    name = parse_food_name(payload)
    data_type = payload.get("dataType")
    brand_owner = payload.get("brandOwner")

    return {
        "name": name,
        "source_food_id": source_food_id,
        "category": parse_category(payload),
        "description": build_description(data_type=data_type, brand_owner=brand_owner),
        "nutrients": normalize_usda_nutrients(payload),
        "servings": normalize_usda_servings(payload),
    }


def parse_fdc_id(payload: dict[str, Any]) -> str:
    raw_fdc_id = payload.get("fdcId")
    try:
        fdc_id = int(raw_fdc_id)
    except (TypeError, ValueError) as exc:
        raise USDAMalformedResponseError("fdcId is missing or invalid") from exc
    if fdc_id <= 0:
        raise USDAMalformedResponseError("fdcId must be positive")
    return str(fdc_id)


def parse_food_name(payload: dict[str, Any]) -> str:
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise USDAMalformedResponseError("description is missing or blank")
    return description.strip().title()


def parse_category(payload: dict[str, Any]) -> str:
    food_category = payload.get("foodCategory")
    if isinstance(food_category, dict):
        category = food_category.get("description")
        if isinstance(category, str) and category.strip():
            return normalize_category(category)

    branded_category = payload.get("brandedFoodCategory")
    if isinstance(branded_category, str) and branded_category.strip():
        return normalize_category(branded_category)

    data_type = payload.get("dataType")
    if isinstance(data_type, str) and data_type.strip():
        return normalize_category(data_type)

    return "usda"


def normalize_category(category: str) -> str:
    normalized = category.strip().lower().replace("&", "and")
    normalized = "_".join(normalized.replace(",", " ").replace("/", " ").split())
    return normalized[:128] or "usda"


def build_description(data_type: Any, brand_owner: Any) -> str:
    parts = ["USDA FoodData Central import."]
    if isinstance(data_type, str) and data_type.strip():
        parts.append(f"Data type: {data_type.strip()}.")
    if isinstance(brand_owner, str) and brand_owner.strip():
        parts.append(f"Brand owner: {brand_owner.strip()}.")
    return " ".join(parts)


def normalize_usda_servings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    servings: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    add_serving(servings=servings, seen_names=seen_names, name="100 g", grams=100.0)

    raw_portions = payload.get("foodPortions", [])
    if raw_portions is None:
        raw_portions = []
    if not isinstance(raw_portions, list):
        raise USDAMalformedResponseError("foodPortions is not a list")

    for portion in raw_portions:
        if not isinstance(portion, dict):
            raise USDAMalformedResponseError("foodPortions item is not an object")
        grams = parse_positive_float(portion.get("gramWeight"))
        name = serving_name_from_portion(portion)
        if grams is not None and name is not None:
            add_serving(servings=servings, seen_names=seen_names, name=name, grams=grams)

    serving_size = parse_positive_float(payload.get("servingSize"))
    serving_size_unit = payload.get("servingSizeUnit")
    if serving_size is not None and isinstance(serving_size_unit, str):
        if serving_size_unit.strip().lower() in {"g", "gram", "grams"}:
            add_serving(
                servings=servings,
                seen_names=seen_names,
                name=f"{format_amount(serving_size)} g",
                grams=serving_size,
            )

    return servings


def serving_name_from_portion(portion: dict[str, Any]) -> str | None:
    portion_description = portion.get("portionDescription")
    if isinstance(portion_description, str) and portion_description.strip():
        return portion_description.strip()

    amount = parse_positive_float(portion.get("amount"))
    measure_unit = portion.get("measureUnit")
    unit_name = None
    if isinstance(measure_unit, dict):
        raw_unit_name = measure_unit.get("name")
        if isinstance(raw_unit_name, str) and raw_unit_name.strip():
            unit_name = raw_unit_name.strip()

    modifier = portion.get("modifier")
    if unit_name is None and isinstance(modifier, str) and modifier.strip():
        unit_name = modifier.strip()

    if amount is not None and unit_name is not None:
        return f"{format_amount(amount)} {unit_name}"

    return None


def add_serving(
    servings: list[dict[str, Any]],
    seen_names: set[str],
    name: str,
    grams: float,
) -> None:
    if not isfinite(grams) or grams <= 0:
        return

    normalized_name = name.strip()
    if not normalized_name:
        return

    dedupe_key = normalized_name.lower()
    if dedupe_key in seen_names:
        return

    seen_names.add(dedupe_key)
    servings.append({"name": normalized_name, "grams": round(grams, 6)})


def parse_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def format_amount(amount: float) -> str:
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:g}"


def get_existing_usda_food(db: Session, fdc_id: int) -> Food | None:
    return (
        db.query(Food)
        .options(selectinload(Food.nutrients), selectinload(Food.servings))
        .filter(
            Food.source == FoodSource.USDA,
            Food.source_food_id == str(fdc_id),
        )
        .one_or_none()
    )


def usda_api_error(exc: USDAIntegrationError) -> APIErrorException:
    return APIErrorException(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )
