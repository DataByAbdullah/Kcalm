from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.integrations.usda import USDAFoodDataCentralClient
from app.models.food import Food
from app.models.user import User
from app.schemas.food import (
    FoodDetailResponse,
    FoodListResponse,
    FoodNutrientResponse,
    FoodServingResponse,
    USDAFoodImportResponse,
    USDAFoodSearchResponse,
)
from app.services.food_service import get_food_detail, list_foods
from app.services.usda_food_service import (
    import_usda_food_by_fdc_id,
    search_usda_foods,
)


router = APIRouter()


def get_usda_client(settings: Settings = Depends(get_settings)) -> USDAFoodDataCentralClient:
    return USDAFoodDataCentralClient(api_key=settings.usda_api_key)


def food_to_detail_response(food: Food) -> FoodDetailResponse:
    return FoodDetailResponse(
        id=food.id,
        name=food.name,
        source=food.source,
        source_food_id=food.source_food_id,
        category=food.category,
        description=food.description,
        nutrients_per_100g=[
            FoodNutrientResponse(
                code=nutrient.nutrient_code,
                name=nutrient.nutrient_name,
                amount=nutrient.amount,
                unit=nutrient.unit,
            )
            for nutrient in food.nutrients
        ],
        servings=[
            FoodServingResponse(
                name=serving.serving_name,
                grams=serving.grams,
            )
            for serving in food.servings
        ],
    )


@router.get("/usda/search", response_model=USDAFoodSearchResponse)
def search_usda_catalog(
    q: str = Query(min_length=1, max_length=128),
    page_size: int = Query(default=10, ge=1, le=50),
    page: int = Query(default=1, ge=1),
    _current_user: User = Depends(get_current_user),
    usda_client: USDAFoodDataCentralClient = Depends(get_usda_client),
) -> USDAFoodSearchResponse:
    result = search_usda_foods(
        client=usda_client,
        query=q.strip(),
        page_size=page_size,
        page=page,
    )
    return USDAFoodSearchResponse(
        items=result.items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/usda/import/{fdc_id}", response_model=USDAFoodImportResponse)
def import_usda_food(
    response: Response,
    fdc_id: int = Path(ge=1),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    usda_client: USDAFoodDataCentralClient = Depends(get_usda_client),
) -> USDAFoodImportResponse:
    result = import_usda_food_by_fdc_id(
        db=db,
        client=usda_client,
        fdc_id=fdc_id,
    )
    response.status_code = 201 if result.status == "imported" else 200
    return USDAFoodImportResponse(
        status=result.status,
        food=food_to_detail_response(result.food),
    )


@router.get("", response_model=FoodListResponse)
def read_foods(
    search: str | None = Query(default=None, min_length=1, max_length=128),
    category: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FoodListResponse:
    foods, total = list_foods(
        db=db,
        search=search,
        category=category,
        limit=limit,
        offset=offset,
    )
    return FoodListResponse(
        items=foods,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{food_id}", response_model=FoodDetailResponse)
def read_food_detail(
    food_id: UUID,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FoodDetailResponse:
    return food_to_detail_response(get_food_detail(db=db, food_id=food_id))
