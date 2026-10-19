from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.enums import GroceryCategory, GroceryListStatus, WeeklyMealPlanStatus
from app.core.exceptions import APIErrorException
from app.meal_planning.scaling import scale_amount, unscale_amount
from app.models.grocery import GroceryList, GroceryListItem
from app.models.meal_plan import (
    MealPlan,
    MealPlanItem,
    MealPlanItemIngredientSnapshot,
    WeeklyMealPlan,
)
from app.models.user import User
from app.schemas.grocery import GroceryListItemCreateRequest, GroceryListItemUpdateRequest
from app.services.weekly_plan_service import weekly_plan_not_found_error


GROCERY_UNIT_GRAMS = "g"
FOOD_CATEGORY_TO_GROCERY_CATEGORY = {
    "fruit": GroceryCategory.PRODUCE,
    "vegetable": GroceryCategory.PRODUCE,
    "starchy_vegetable": GroceryCategory.PRODUCE,
    "protein": GroceryCategory.MEAT_SEAFOOD,
    "dairy": GroceryCategory.DAIRY,
    "grain": GroceryCategory.GRAINS,
    "grains": GroceryCategory.GRAINS,
    "fat": GroceryCategory.PANTRY,
    "pantry": GroceryCategory.PANTRY,
    "frozen": GroceryCategory.FROZEN,
}


@dataclass(frozen=True)
class GroceryPreviewItem:
    food_id: UUID
    food_name: str
    total_grams: float
    source: str | None
    source_food_id: str | None
    category: str | None


@dataclass(frozen=True)
class GroceryPreview:
    weekly_plan: WeeklyMealPlan
    items: list[GroceryPreviewItem]


def grocery_snapshot_missing_error(meal_plan_item_ids: list[UUID]) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="GROCERY_SNAPSHOT_MISSING",
        message="Grocery preview requires meal item ingredient snapshots.",
        details={"meal_plan_item_ids": [str(item_id) for item_id in meal_plan_item_ids]},
    )


def grocery_list_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="GROCERY_LIST_NOT_FOUND",
        message="Grocery list not found.",
    )


def grocery_list_item_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="GROCERY_LIST_ITEM_NOT_FOUND",
        message="Grocery list item not found.",
    )


def grocery_list_already_exists_error(weekly_plan_id: UUID) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="GROCERY_LIST_ALREADY_EXISTS",
        message="An active grocery list already exists for this weekly plan.",
        details={"weekly_plan_id": str(weekly_plan_id)},
    )


def grocery_list_archived_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="GROCERY_LIST_ARCHIVED",
        message="Archived grocery lists cannot be modified.",
    )


def grocery_weekly_plan_archived_error(weekly_plan_id: UUID) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="WEEKLY_PLAN_ARCHIVED",
        message="Cannot generate a new grocery list from an archived weekly plan.",
        details={"weekly_plan_id": str(weekly_plan_id)},
    )


def grocery_list_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="GROCERY_LIST_SAVE_FAILED",
        message="Grocery list could not be saved.",
    )


def category_for_food_category(food_category: str | None) -> GroceryCategory:
    if food_category is None:
        return GroceryCategory.OTHER
    normalized = "_".join(food_category.strip().lower().split())
    return FOOD_CATEGORY_TO_GROCERY_CATEGORY.get(normalized, GroceryCategory.OTHER)


def quantity_grams_for_unit(quantity: float, unit: str) -> float | None:
    normalized = unit.strip().lower()
    if normalized in {"g", "gram", "grams"}:
        return quantity
    return None


def get_weekly_grocery_preview(
    db: Session,
    user: User,
    weekly_plan_id: UUID,
) -> GroceryPreview:
    week = (
        db.query(WeeklyMealPlan)
        .options(
            selectinload(WeeklyMealPlan.daily_plans)
            .selectinload(MealPlan.items)
            .selectinload(MealPlanItem.ingredient_snapshots)
            .selectinload(MealPlanItemIngredientSnapshot.food)
        )
        .filter(WeeklyMealPlan.id == weekly_plan_id, WeeklyMealPlan.user_id == user.id)
        .one_or_none()
    )
    if week is None:
        raise weekly_plan_not_found_error()

    missing_item_ids = [
        item.id
        for daily_plan in week.daily_plans
        for item in daily_plan.items
        if not item.ingredient_snapshots
    ]
    if missing_item_ids:
        raise grocery_snapshot_missing_error(sorted(missing_item_ids, key=str))

    grams_by_food_id: dict[UUID, int] = {}
    names_by_food_id: dict[UUID, str] = {}
    source_by_food_id: dict[UUID, str | None] = {}
    source_food_id_by_food_id: dict[UUID, str | None] = {}
    category_by_food_id: dict[UUID, str | None] = {}
    for daily_plan in sorted(week.daily_plans, key=lambda plan: plan.plan_date):
        for item in sorted(daily_plan.items, key=lambda meal: meal.position):
            for snapshot in sorted(
                item.ingredient_snapshots,
                key=lambda ingredient: (ingredient.food_name_snapshot.lower(), str(ingredient.food_id)),
            ):
                food_id = snapshot.food_id
                grams_by_food_id[food_id] = grams_by_food_id.get(food_id, 0) + scale_amount(
                    snapshot.quantity_grams
                )
                names_by_food_id[food_id] = snapshot.food_name_snapshot
                if snapshot.food is not None:
                    source = snapshot.food.source
                    source_by_food_id[food_id] = getattr(source, "value", source)
                    source_food_id_by_food_id[food_id] = snapshot.food.source_food_id
                    category_by_food_id[food_id] = snapshot.food.category
                else:
                    source_by_food_id.setdefault(food_id, None)
                    source_food_id_by_food_id.setdefault(food_id, None)
                    category_by_food_id.setdefault(food_id, None)

    items = [
        GroceryPreviewItem(
            food_id=food_id,
            food_name=names_by_food_id[food_id],
            total_grams=unscale_amount(grams),
            source=source_by_food_id.get(food_id),
            source_food_id=source_food_id_by_food_id.get(food_id),
            category=category_by_food_id.get(food_id),
        )
        for food_id, grams in sorted(
            grams_by_food_id.items(),
            key=lambda pair: (names_by_food_id[pair[0]].lower(), str(pair[0])),
        )
    ]
    return GroceryPreview(weekly_plan=week, items=items)


def create_grocery_list_from_weekly_plan(
    db: Session,
    user: User,
    weekly_plan_id: UUID,
) -> GroceryList:
    preview = get_weekly_grocery_preview(db=db, user=user, weekly_plan_id=weekly_plan_id)
    if preview.weekly_plan.status == WeeklyMealPlanStatus.ARCHIVED.value:
        raise grocery_weekly_plan_archived_error(weekly_plan_id)
    ensure_no_active_grocery_list_for_weekly_plan(
        db=db,
        user_id=user.id,
        weekly_plan_id=weekly_plan_id,
    )

    grocery_list = GroceryList(
        user_id=user.id,
        weekly_plan_id=weekly_plan_id,
        status=GroceryListStatus.ACTIVE.value,
    )
    try:
        db.add(grocery_list)
        db.flush()
        persist_automatic_grocery_items(
            db=db,
            grocery_list=grocery_list,
            preview_items=preview.items,
        )
        db.commit()
        db.expire_all()
    except IntegrityError as exc:
        db.rollback()
        raise grocery_list_already_exists_error(weekly_plan_id) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise grocery_list_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list.id)


def ensure_no_active_grocery_list_for_weekly_plan(
    db: Session,
    user_id: UUID,
    weekly_plan_id: UUID,
) -> None:
    existing = (
        db.query(GroceryList.id)
        .filter(
            GroceryList.user_id == user_id,
            GroceryList.weekly_plan_id == weekly_plan_id,
            GroceryList.status == GroceryListStatus.ACTIVE.value,
        )
        .one_or_none()
    )
    if existing is not None:
        raise grocery_list_already_exists_error(weekly_plan_id)


def persist_automatic_grocery_items(
    db: Session,
    grocery_list: GroceryList,
    preview_items: list[GroceryPreviewItem],
    checked_by_food_id: dict[UUID, bool] | None = None,
) -> None:
    checked_by_food_id = checked_by_food_id or {}
    for item in preview_items:
        db.add(
            GroceryListItem(
                grocery_list_id=grocery_list.id,
                food_id=item.food_id,
                food_name_snapshot=item.food_name,
                quantity=item.total_grams,
                unit=GROCERY_UNIT_GRAMS,
                quantity_grams=item.total_grams,
                category=category_for_food_category(item.category).value,
                checked=checked_by_food_id.get(item.food_id, False),
                manually_added=False,
            )
        )


def get_grocery_list_detail(
    db: Session,
    user: User,
    grocery_list_id: UUID,
) -> GroceryList:
    grocery_list = (
        db.query(GroceryList)
        .options(selectinload(GroceryList.items))
        .filter(GroceryList.id == grocery_list_id, GroceryList.user_id == user.id)
        .one_or_none()
    )
    if grocery_list is None:
        raise grocery_list_not_found_error()
    return grocery_list


def list_grocery_lists(
    db: Session,
    user: User,
    weekly_plan_id: UUID | None = None,
    status: GroceryListStatus | None = None,
) -> tuple[list[GroceryList], int]:
    effective_status = status or GroceryListStatus.ACTIVE
    query = (
        db.query(GroceryList)
        .options(selectinload(GroceryList.items))
        .filter(
            GroceryList.user_id == user.id,
            GroceryList.status == effective_status.value,
        )
    )
    if weekly_plan_id is not None:
        query = query.filter(GroceryList.weekly_plan_id == weekly_plan_id)

    total = query.count()
    grocery_lists = query.order_by(
        GroceryList.generated_at.desc(),
        GroceryList.created_at.desc(),
    ).all()
    return grocery_lists, total


def archive_grocery_list(
    db: Session,
    user: User,
    grocery_list_id: UUID,
) -> None:
    grocery_list = get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)
    if grocery_list.status != GroceryListStatus.ARCHIVED.value:
        grocery_list.status = GroceryListStatus.ARCHIVED.value
        db.commit()


def update_grocery_list_item(
    db: Session,
    user: User,
    grocery_list_id: UUID,
    item_id: UUID,
    payload: GroceryListItemUpdateRequest,
) -> GroceryList:
    grocery_list = get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)
    ensure_grocery_list_modifiable(grocery_list)
    item = grocery_list_item_for_update(grocery_list=grocery_list, item_id=item_id)

    if payload.checked is not None:
        item.checked = payload.checked
    if payload.quantity is not None:
        item.quantity = payload.quantity
    if payload.unit is not None:
        item.unit = payload.unit
    if payload.quantity is not None or payload.unit is not None:
        item.quantity_grams = quantity_grams_for_unit(item.quantity, item.unit)
    if payload.category is not None:
        item.category = payload.category.value

    try:
        db.commit()
        db.expire_all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise grocery_list_save_failed_error() from exc

    return get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)


def add_manual_grocery_list_item(
    db: Session,
    user: User,
    grocery_list_id: UUID,
    payload: GroceryListItemCreateRequest,
) -> GroceryList:
    grocery_list = get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)
    ensure_grocery_list_modifiable(grocery_list)
    item = GroceryListItem(
        grocery_list_id=grocery_list.id,
        food_id=None,
        food_name_snapshot=payload.name,
        quantity=payload.quantity,
        unit=payload.unit,
        quantity_grams=quantity_grams_for_unit(payload.quantity, payload.unit),
        category=payload.category.value,
        checked=False,
        manually_added=True,
    )
    try:
        db.add(item)
        db.commit()
        db.expire_all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise grocery_list_save_failed_error() from exc

    return get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)


def remove_grocery_list_item(
    db: Session,
    user: User,
    grocery_list_id: UUID,
    item_id: UUID,
) -> None:
    grocery_list = get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)
    ensure_grocery_list_modifiable(grocery_list)
    item = grocery_list_item_for_update(grocery_list=grocery_list, item_id=item_id)
    try:
        db.delete(item)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise grocery_list_save_failed_error() from exc


def regenerate_grocery_list(
    db: Session,
    user: User,
    grocery_list_id: UUID,
) -> GroceryList:
    grocery_list = get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)
    ensure_grocery_list_modifiable(grocery_list)
    preview = get_weekly_grocery_preview(
        db=db,
        user=user,
        weekly_plan_id=grocery_list.weekly_plan_id,
    )
    checked_by_food_id = {
        item.food_id: item.checked
        for item in grocery_list.items
        if item.food_id is not None and not item.manually_added
    }
    try:
        for item in list(grocery_list.items):
            if not item.manually_added:
                db.delete(item)
        db.flush()
        persist_automatic_grocery_items(
            db=db,
            grocery_list=grocery_list,
            preview_items=preview.items,
            checked_by_food_id=checked_by_food_id,
        )
        grocery_list.generated_at = datetime.now(timezone.utc)
        db.commit()
        db.expire_all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise grocery_list_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_grocery_list_detail(db=db, user=user, grocery_list_id=grocery_list_id)


def ensure_grocery_list_modifiable(grocery_list: GroceryList) -> None:
    if grocery_list.status == GroceryListStatus.ARCHIVED.value:
        raise grocery_list_archived_error()


def grocery_list_item_for_update(
    grocery_list: GroceryList,
    item_id: UUID,
) -> GroceryListItem:
    for item in grocery_list.items:
        if item.id == item_id:
            return item
    raise grocery_list_item_not_found_error()
