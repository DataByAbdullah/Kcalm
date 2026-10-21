from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import APIErrorException
from app.models.food import Food
from app.models.recipe import (
    Recipe,
    RecipeEquipment,
    RecipeIngredient,
    RecipeNutrient,
    RecipeStep,
    RecipeTag,
    RecipeTagLink,
)
from app.nutrition.recipe import calculate_recipe_nutrients
from app.schemas.recipe import RecipeCreateRequest, RecipeUpdateRequest


ALLOWED_RECIPE_TAGS = {
    "pescatarian",
    "halal",
    "quick",
    "vegetarian",
    "vegan",
    "dairy_free",
    "gluten_free",
    "high_protein",
    "breakfast",
    "lunch",
    "dinner",
    "snack",
}

ALLOWED_RECIPE_EQUIPMENT = {
    "oven",
    "stovetop",
    "microwave",
    "blender",
    "air_fryer",
}

EQUIPMENT_ALIASES = {
    "stove": "stovetop",
    "air fryer": "air_fryer",
}


def recipe_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="RECIPE_NOT_FOUND",
        message="Recipe not found.",
    )


def list_recipes(
    db: Session,
    search: str | None = None,
    tag: str | None = None,
    max_total_time_minutes: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Recipe], int]:
    query = db.query(Recipe).filter(Recipe.active.is_(True))

    if search is not None and search.strip():
        query = query.filter(Recipe.name.ilike(f"%{search.strip()}%"))

    if tag is not None and tag.strip():
        normalized_tag = normalize_tag(tag)
        query = (
            query.join(RecipeTagLink)
            .join(RecipeTag)
            .filter(RecipeTag.name == normalized_tag)
        )

    if max_total_time_minutes is not None:
        query = query.filter(Recipe.total_time_minutes <= max_total_time_minutes)

    total = query.count()
    recipes = (
        query.options(selectinload(Recipe.tag_links).selectinload(RecipeTagLink.tag))
        .order_by(Recipe.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return recipes, total


def get_recipe_detail(db: Session, recipe_id: UUID) -> Recipe:
    recipe = load_recipe(db=db, recipe_id=recipe_id)
    if recipe is None or not recipe.active:
        raise recipe_not_found_error()
    return recipe


def create_recipe(
    db: Session,
    payload: RecipeCreateRequest,
    source: str = "user_created",
) -> Recipe:
    tags = normalize_tags(payload.tags)
    equipment = normalize_equipment_list(payload.equipment)
    total_time_minutes = payload.prep_time_minutes + payload.cook_time_minutes
    validate_quick_recipe(tags=tags, total_time_minutes=total_time_minutes)
    positioned_ingredients = normalize_positions(payload.ingredients, "ingredient")
    positioned_steps = normalize_positions(payload.steps, "step")
    food_by_id = load_foods_for_ingredients(db, positioned_ingredients)

    try:
        recipe = Recipe(
            name=payload.name,
            description=payload.description,
            servings=payload.servings,
            prep_time_minutes=payload.prep_time_minutes,
            cook_time_minutes=payload.cook_time_minutes,
            total_time_minutes=total_time_minutes,
            difficulty=payload.difficulty,
            instructions_summary=payload.instructions_summary,
            active=True,
            source=source,
        )
        db.add(recipe)
        db.flush()

        replace_ingredients(db, recipe, positioned_ingredients, food_by_id)
        replace_steps(db, recipe, positioned_steps)
        replace_tags(db, recipe, tags)
        replace_equipment(db, recipe, equipment)
        recalculate_recipe_nutrients(db, recipe.id)
        db.commit()
    except APIErrorException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=500,
            code="RECIPE_SAVE_FAILED",
            message="Recipe could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    created = load_recipe(db=db, recipe_id=recipe.id)
    if created is None:
        raise recipe_not_found_error()
    return created


def update_recipe(
    db: Session,
    recipe_id: UUID,
    payload: RecipeUpdateRequest,
) -> Recipe:
    recipe = load_recipe(db=db, recipe_id=recipe_id)
    if recipe is None or not recipe.active:
        raise recipe_not_found_error()

    fields_set = payload.model_fields_set
    positioned_ingredients = None
    food_by_id = None
    positioned_steps = None
    tags = None
    equipment = None

    if "ingredients" in fields_set:
        if payload.ingredients is None or not payload.ingredients:
            raise APIErrorException(
                status_code=422,
                code="RECIPE_REQUIRES_INGREDIENTS",
                message="Recipe must include at least one ingredient.",
            )
        positioned_ingredients = normalize_positions(payload.ingredients, "ingredient")
        food_by_id = load_foods_for_ingredients(db, positioned_ingredients)

    if "steps" in fields_set:
        positioned_steps = normalize_positions(payload.steps or [], "step")

    if "tags" in fields_set:
        tags = normalize_tags(payload.tags or [])

    if "equipment" in fields_set:
        equipment = normalize_equipment_list(payload.equipment or [])

    next_prep_time = payload.prep_time_minutes if "prep_time_minutes" in fields_set else recipe.prep_time_minutes
    next_cook_time = payload.cook_time_minutes if "cook_time_minutes" in fields_set else recipe.cook_time_minutes
    next_total_time = next_prep_time + next_cook_time
    next_tags = tags if tags is not None else [link.tag.name for link in recipe.tag_links]
    validate_quick_recipe(tags=next_tags, total_time_minutes=next_total_time)

    try:
        if "name" in fields_set and payload.name is not None:
            recipe.name = payload.name
        if "description" in fields_set:
            recipe.description = payload.description
        if "servings" in fields_set and payload.servings is not None:
            recipe.servings = payload.servings
        if "prep_time_minutes" in fields_set:
            recipe.prep_time_minutes = payload.prep_time_minutes or 0
        if "cook_time_minutes" in fields_set:
            recipe.cook_time_minutes = payload.cook_time_minutes or 0
        recipe.total_time_minutes = recipe.prep_time_minutes + recipe.cook_time_minutes
        if "difficulty" in fields_set:
            recipe.difficulty = payload.difficulty
        if "instructions_summary" in fields_set:
            recipe.instructions_summary = payload.instructions_summary

        if positioned_ingredients is not None and food_by_id is not None:
            replace_ingredients(db, recipe, positioned_ingredients, food_by_id)
        if positioned_steps is not None:
            replace_steps(db, recipe, positioned_steps)
        if tags is not None:
            replace_tags(db, recipe, tags)
        if equipment is not None:
            replace_equipment(db, recipe, equipment)

        recalculate_recipe_nutrients(db, recipe.id)
        db.commit()
    except APIErrorException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=500,
            code="RECIPE_SAVE_FAILED",
            message="Recipe could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    updated = load_recipe(db=db, recipe_id=recipe.id)
    if updated is None:
        raise recipe_not_found_error()
    return updated


def archive_recipe(db: Session, recipe_id: UUID) -> None:
    recipe = load_recipe(db=db, recipe_id=recipe_id)
    if recipe is None or not recipe.active:
        raise recipe_not_found_error()
    recipe.active = False
    db.commit()


def load_recipe(db: Session, recipe_id: UUID) -> Recipe | None:
    return (
        db.query(Recipe)
        .options(
            selectinload(Recipe.ingredients)
            .selectinload(RecipeIngredient.food)
            .selectinload(Food.nutrients),
            selectinload(Recipe.steps),
            selectinload(Recipe.tag_links).selectinload(RecipeTagLink.tag),
            selectinload(Recipe.equipment),
            selectinload(Recipe.nutrients),
        )
        .populate_existing()
        .filter(Recipe.id == recipe_id)
        .one_or_none()
    )


def normalize_positions(items: list, item_name: str) -> list:
    positioned = []
    seen_positions: set[int] = set()
    for index, item in enumerate(items, start=1):
        position = item.position or index
        if position in seen_positions:
            raise APIErrorException(
                status_code=422,
                code=f"DUPLICATE_RECIPE_{item_name.upper()}_POSITION",
                message=f"Recipe {item_name} positions must be unique.",
                details={"position": position},
            )
        seen_positions.add(position)
        positioned.append((position, item))
    return positioned


def load_foods_for_ingredients(db: Session, positioned_ingredients: list) -> dict[UUID, Food]:
    food_ids = {item.food_id for _, item in positioned_ingredients}
    foods = (
        db.query(Food)
        .options(selectinload(Food.nutrients))
        .filter(Food.id.in_(food_ids))
        .all()
    )
    food_by_id = {food.id: food for food in foods}
    missing_food_ids = sorted(str(food_id) for food_id in food_ids - set(food_by_id))
    if missing_food_ids:
        raise APIErrorException(
            status_code=422,
            code="INVALID_RECIPE_FOOD",
            message="Recipe ingredient references an unknown food.",
            details={"food_ids": missing_food_ids},
        )
    return food_by_id


def replace_ingredients(
    db: Session,
    recipe: Recipe,
    positioned_ingredients: list,
    food_by_id: dict[UUID, Food],
) -> None:
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete(
        synchronize_session=False
    )
    db.flush()
    for position, item in positioned_ingredients:
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                food_id=item.food_id,
                food=food_by_id[item.food_id],
                quantity_grams=item.quantity_grams,
                display_quantity=item.display_quantity,
                display_unit=item.display_unit,
                preparation_note=item.preparation_note,
                position=position,
            )
        )
    db.flush()


def replace_steps(db: Session, recipe: Recipe, positioned_steps: list) -> None:
    db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe.id).delete(synchronize_session=False)
    db.flush()
    for position, item in positioned_steps:
        timer_required = effective_timer_required(item)
        db.add(
            RecipeStep(
                recipe_id=recipe.id,
                position=position,
                instruction=item.instruction,
                phase=item.phase.value,
                duration_seconds=item.duration_seconds,
                timer=timer_required,
                timer_seconds=item.timer_seconds,
                cue_action=item.cue_action,
                animation_key=item.animation_key,
                media_asset_key=item.media_asset_key,
                visual_cue=item.visual_cue,
            )
        )
    db.flush()


def effective_timer_required(item) -> bool:
    if item.timer_required is not None:
        return item.timer_required
    if item.timer_seconds is not None:
        return True
    return item.timer


def replace_tags(db: Session, recipe: Recipe, tags: list[str]) -> None:
    db.query(RecipeTagLink).filter(RecipeTagLink.recipe_id == recipe.id).delete(
        synchronize_session=False
    )
    db.flush()
    for tag_name in tags:
        tag = get_or_create_tag(db, tag_name)
        db.add(RecipeTagLink(recipe_id=recipe.id, tag_id=tag.id))
    db.flush()


def replace_equipment(db: Session, recipe: Recipe, equipment_items: list[str]) -> None:
    db.query(RecipeEquipment).filter(RecipeEquipment.recipe_id == recipe.id).delete(
        synchronize_session=False
    )
    db.flush()
    for equipment in equipment_items:
        db.add(RecipeEquipment(recipe_id=recipe.id, equipment=equipment))
    db.flush()


def get_or_create_tag(db: Session, tag_name: str) -> RecipeTag:
    tag = db.query(RecipeTag).filter(func.lower(RecipeTag.name) == tag_name.lower()).one_or_none()
    if tag is not None:
        return tag
    tag = RecipeTag(name=tag_name)
    db.add(tag)
    db.flush()
    return tag


def recalculate_recipe_nutrients(db: Session, recipe_id: UUID) -> None:
    db.flush()
    recipe = load_recipe(db=db, recipe_id=recipe_id)
    if recipe is None:
        raise recipe_not_found_error()

    db.query(RecipeNutrient).filter(RecipeNutrient.recipe_id == recipe.id).delete(
        synchronize_session=False
    )
    db.flush()
    calculated_nutrients = calculate_recipe_nutrients(
        ingredients=list(recipe.ingredients),
        servings=Decimal(str(recipe.servings)),
    )
    for nutrient in calculated_nutrients:
        db.add(
            RecipeNutrient(
                recipe_id=recipe.id,
                nutrient_code=nutrient.code,
                nutrient_name=nutrient.name,
                total_amount=nutrient.total_amount,
                per_serving_amount=nutrient.per_serving_amount,
                unit=nutrient.unit,
                missing_ingredient_count=nutrient.missing_ingredient_count,
                complete=nutrient.complete,
            )
        )
    db.flush()


def normalize_tags(values: list[str]) -> list[str]:
    normalized_values = []
    seen = set()
    for value in values:
        normalized = normalize_key(value)
        if normalized not in ALLOWED_RECIPE_TAGS:
            raise APIErrorException(
                status_code=422,
                code="INVALID_RECIPE_TAG",
                message="Recipe tag is not supported.",
                details={"tag": value, "supported_tags": sorted(ALLOWED_RECIPE_TAGS)},
            )
        if normalized not in seen:
            normalized_values.append(normalized)
            seen.add(normalized)
    return normalized_values


def normalize_tag(value: str) -> str:
    normalized = normalize_key(value)
    if normalized not in ALLOWED_RECIPE_TAGS:
        raise APIErrorException(
            status_code=422,
            code="INVALID_RECIPE_TAG",
            message="Recipe tag is not supported.",
            details={"tag": value, "supported_tags": sorted(ALLOWED_RECIPE_TAGS)},
        )
    return normalized


def normalize_equipment_list(values: list[str]) -> list[str]:
    normalized_values = []
    seen = set()
    for value in values:
        normalized = EQUIPMENT_ALIASES.get(normalize_key(value), normalize_key(value))
        if normalized not in ALLOWED_RECIPE_EQUIPMENT:
            raise APIErrorException(
                status_code=422,
                code="INVALID_RECIPE_EQUIPMENT",
                message="Recipe equipment is not supported.",
                details={
                    "equipment": value,
                    "supported_equipment": sorted(ALLOWED_RECIPE_EQUIPMENT),
                },
            )
        if normalized not in seen:
            normalized_values.append(normalized)
            seen.add(normalized)
    return normalized_values


def normalize_key(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", " ").split())


def validate_quick_recipe(tags: list[str], total_time_minutes: int) -> None:
    if "quick" in tags and total_time_minutes > 20:
        raise APIErrorException(
            status_code=422,
            code="QUICK_RECIPE_TOO_LONG",
            message="Recipes tagged quick must be 20 minutes or less.",
            details={"total_time_minutes": total_time_minutes, "maximum": 20},
        )
