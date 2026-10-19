from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.routes.grocery_lists import grocery_list_to_response
from app.api.routes.meal_plans import plan_to_response
from app.core.database import get_db
from app.core.enums import WeeklyMealPlanStatus
from app.core.security import get_current_user
from app.models.meal_plan import WeeklyMealPlan
from app.models.user import User
from app.schemas.weekly_plan import (
    WeeklyGroceryPreviewItemResponse,
    WeeklyGroceryPreviewResponse,
    WeeklyMealPlanCreateRequest,
    WeeklyMealPlanListResponse,
    WeeklyMealPlanResponse,
    WeeklyMealPlanSummaryResponse,
)
from app.schemas.grocery import GroceryListResponse
from app.services.grocery_service import (
    create_grocery_list_from_weekly_plan,
    get_weekly_grocery_preview,
)
from app.services.weekly_plan_service import (
    archive_weekly_plan,
    create_weekly_plan,
    get_weekly_plan_detail,
    list_weekly_plans,
)


router = APIRouter()


def weekly_plan_to_summary_response(week: WeeklyMealPlan) -> WeeklyMealPlanSummaryResponse:
    return WeeklyMealPlanSummaryResponse(
        weekly_plan_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        status=WeeklyMealPlanStatus(week.status),
        daily_plan_count=len(week.daily_plans),
        created_at=week.created_at,
        updated_at=week.updated_at,
    )


def weekly_plan_to_response(week: WeeklyMealPlan) -> WeeklyMealPlanResponse:
    return WeeklyMealPlanResponse(
        weekly_plan_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        status=WeeklyMealPlanStatus(week.status),
        daily_plans=[
            plan_to_response(plan)
            for plan in sorted(week.daily_plans, key=lambda item: item.plan_date)
        ],
        created_at=week.created_at,
        updated_at=week.updated_at,
    )


@router.post("", response_model=WeeklyMealPlanResponse, status_code=status.HTTP_201_CREATED)
def create_weekly_meal_plan(
    payload: WeeklyMealPlanCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeeklyMealPlanResponse:
    week = create_weekly_plan(db=db, user=current_user, payload=payload)
    return weekly_plan_to_response(week)


@router.get("", response_model=WeeklyMealPlanListResponse)
def read_weekly_meal_plans(
    status_filter: WeeklyMealPlanStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeeklyMealPlanListResponse:
    weeks, total = list_weekly_plans(
        db=db,
        user=current_user,
        status=status_filter,
    )
    return WeeklyMealPlanListResponse(
        items=[weekly_plan_to_summary_response(week) for week in weeks],
        total=total,
    )


@router.get("/{weekly_plan_id}/grocery/preview", response_model=WeeklyGroceryPreviewResponse)
def read_weekly_grocery_preview(
    weekly_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeeklyGroceryPreviewResponse:
    preview = get_weekly_grocery_preview(
        db=db,
        user=current_user,
        weekly_plan_id=weekly_plan_id,
    )
    return WeeklyGroceryPreviewResponse(
        weekly_plan_id=preview.weekly_plan.id,
        start_date=preview.weekly_plan.start_date,
        end_date=preview.weekly_plan.end_date,
        items=[
            WeeklyGroceryPreviewItemResponse(
                food_id=item.food_id,
                food_name=item.food_name,
                total_grams=item.total_grams,
                source=item.source,
                source_food_id=item.source_food_id,
                category=item.category,
            )
            for item in preview.items
        ],
    )


@router.post(
    "/{weekly_plan_id}/grocery-list",
    response_model=GroceryListResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_weekly_grocery_list(
    weekly_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroceryListResponse:
    grocery_list = create_grocery_list_from_weekly_plan(
        db=db,
        user=current_user,
        weekly_plan_id=weekly_plan_id,
    )
    return grocery_list_to_response(grocery_list)


@router.get("/{weekly_plan_id}", response_model=WeeklyMealPlanResponse)
def read_weekly_meal_plan(
    weekly_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeeklyMealPlanResponse:
    week = get_weekly_plan_detail(db=db, user=current_user, weekly_plan_id=weekly_plan_id)
    return weekly_plan_to_response(week)


@router.delete("/{weekly_plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_weekly_meal_plan(
    weekly_plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    archive_weekly_plan(db=db, user=current_user, weekly_plan_id=weekly_plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
