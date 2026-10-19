from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import APIErrorException
from app.models.food import Food


def food_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="FOOD_NOT_FOUND",
        message="Food not found.",
    )


def list_foods(
    db: Session,
    search: str | None = None,
    category: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Food], int]:
    query = db.query(Food)

    if search is not None and search.strip():
        query = query.filter(Food.name.ilike(f"%{search.strip()}%"))

    if category is not None and category.strip():
        query = query.filter(func.lower(Food.category) == category.strip().lower())

    total = query.count()
    foods = query.order_by(Food.name.asc()).offset(offset).limit(limit).all()
    return foods, total


def get_food_detail(db: Session, food_id: UUID) -> Food:
    food = (
        db.query(Food)
        .options(selectinload(Food.nutrients), selectinload(Food.servings))
        .filter(Food.id == food_id)
        .one_or_none()
    )
    if food is None:
        raise food_not_found_error()
    return food
