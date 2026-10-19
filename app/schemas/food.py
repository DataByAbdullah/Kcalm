from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import FoodSource


class FoodSummaryResponse(BaseModel):
    id: UUID
    name: str
    category: str
    source: FoodSource

    model_config = ConfigDict(from_attributes=True)


class FoodListResponse(BaseModel):
    items: list[FoodSummaryResponse]
    total: int
    limit: int
    offset: int


class FoodNutrientResponse(BaseModel):
    code: str
    name: str
    amount: float = Field(ge=0)
    unit: str


class FoodServingResponse(BaseModel):
    name: str
    grams: float = Field(gt=0)


class FoodDetailResponse(BaseModel):
    id: UUID
    name: str
    source: FoodSource
    source_food_id: str | None
    category: str
    description: str | None
    nutrients_per_100g: list[FoodNutrientResponse]
    servings: list[FoodServingResponse]


class USDAFoodSearchItemResponse(BaseModel):
    fdc_id: int
    description: str
    data_type: str | None
    brand_owner: str | None


class USDAFoodSearchResponse(BaseModel):
    items: list[USDAFoodSearchItemResponse]
    total: int
    page: int
    page_size: int


class USDAFoodImportResponse(BaseModel):
    status: str
    food: FoodDetailResponse
