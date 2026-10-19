from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import GroceryCategory, GroceryListStatus
from app.core.security import get_current_user
from app.models.grocery import GroceryList, GroceryListItem
from app.models.user import User
from app.schemas.grocery import (
    GroceryListItemCreateRequest,
    GroceryListItemResponse,
    GroceryListItemUpdateRequest,
    GroceryListListResponse,
    GroceryListResponse,
    GroceryListSummaryResponse,
)
from app.services.grocery_service import (
    add_manual_grocery_list_item,
    archive_grocery_list,
    get_grocery_list_detail,
    list_grocery_lists,
    regenerate_grocery_list,
    remove_grocery_list_item,
    update_grocery_list_item,
)


router = APIRouter()


def grocery_item_to_response(item: GroceryListItem) -> GroceryListItemResponse:
    return GroceryListItemResponse(
        id=item.id,
        food_id=item.food_id,
        food_name=item.food_name_snapshot,
        quantity=item.quantity,
        unit=item.unit,
        quantity_grams=item.quantity_grams,
        category=GroceryCategory(item.category),
        checked=item.checked,
        manually_added=item.manually_added,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def grocery_list_to_response(grocery_list: GroceryList) -> GroceryListResponse:
    return GroceryListResponse(
        grocery_list_id=grocery_list.id,
        weekly_plan_id=grocery_list.weekly_plan_id,
        status=GroceryListStatus(grocery_list.status),
        generated_at=grocery_list.generated_at,
        items=[grocery_item_to_response(item) for item in grocery_list.items],
        created_at=grocery_list.created_at,
        updated_at=grocery_list.updated_at,
    )


def grocery_list_to_summary_response(grocery_list: GroceryList) -> GroceryListSummaryResponse:
    return GroceryListSummaryResponse(
        grocery_list_id=grocery_list.id,
        weekly_plan_id=grocery_list.weekly_plan_id,
        status=GroceryListStatus(grocery_list.status),
        item_count=len(grocery_list.items),
        checked_item_count=sum(1 for item in grocery_list.items if item.checked),
        generated_at=grocery_list.generated_at,
        created_at=grocery_list.created_at,
        updated_at=grocery_list.updated_at,
    )


@router.get("", response_model=GroceryListListResponse)
def read_grocery_lists(
    weekly_plan_id: UUID | None = Query(default=None),
    status_filter: GroceryListStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListListResponse:
    grocery_lists, total = list_grocery_lists(
        db=db,
        user=current_user,
        weekly_plan_id=weekly_plan_id,
        status=status_filter,
    )
    return GroceryListListResponse(
        items=[grocery_list_to_summary_response(item) for item in grocery_lists],
        total=total,
    )


@router.get("/{grocery_list_id}", response_model=GroceryListResponse)
def read_grocery_list(
    grocery_list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListResponse:
    grocery_list = get_grocery_list_detail(
        db=db,
        user=current_user,
        grocery_list_id=grocery_list_id,
    )
    return grocery_list_to_response(grocery_list)


@router.post("/{grocery_list_id}/regenerate", response_model=GroceryListResponse)
def regenerate_grocery_list_endpoint(
    grocery_list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListResponse:
    grocery_list = regenerate_grocery_list(
        db=db,
        user=current_user,
        grocery_list_id=grocery_list_id,
    )
    return grocery_list_to_response(grocery_list)


@router.post(
    "/{grocery_list_id}/items",
    response_model=GroceryListResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_grocery_list_item(
    grocery_list_id: UUID,
    payload: GroceryListItemCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListResponse:
    grocery_list = add_manual_grocery_list_item(
        db=db,
        user=current_user,
        grocery_list_id=grocery_list_id,
        payload=payload,
    )
    return grocery_list_to_response(grocery_list)


@router.patch("/{grocery_list_id}/items/{item_id}", response_model=GroceryListResponse)
def update_grocery_item(
    grocery_list_id: UUID,
    item_id: UUID,
    payload: GroceryListItemUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListResponse:
    grocery_list = update_grocery_list_item(
        db=db,
        user=current_user,
        grocery_list_id=grocery_list_id,
        item_id=item_id,
        payload=payload,
    )
    return grocery_list_to_response(grocery_list)


@router.delete("/{grocery_list_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grocery_item(
    grocery_list_id: UUID,
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    remove_grocery_list_item(
        db=db,
        user=current_user,
        grocery_list_id=grocery_list_id,
        item_id=item_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{grocery_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grocery_list(
    grocery_list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    archive_grocery_list(db=db, user=current_user, grocery_list_id=grocery_list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
