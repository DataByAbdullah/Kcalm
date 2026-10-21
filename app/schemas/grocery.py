from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.core.enums import GroceryCategory, GroceryListStatus


class GroceryListItemResponse(BaseModel):
    id: UUID
    food_id: UUID | None
    food_name: str
    quantity: float
    unit: str
    quantity_grams: float | None
    category: GroceryCategory
    checked: bool
    manually_added: bool
    created_at: datetime
    updated_at: datetime


class GroceryListResponse(BaseModel):
    grocery_list_id: UUID
    weekly_plan_id: UUID
    status: GroceryListStatus
    generated_at: datetime
    items: list[GroceryListItemResponse]
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def item_count(self) -> int:
        return len(self.items)

    @computed_field
    @property
    def checked_item_count(self) -> int:
        return sum(item.checked for item in self.items)

    @computed_field
    @property
    def completion_percent(self) -> float:
        return round(self.checked_item_count / self.item_count * 100, 1) if self.items else 0.0


class GroceryListSummaryResponse(BaseModel):
    grocery_list_id: UUID
    weekly_plan_id: UUID
    status: GroceryListStatus
    item_count: int
    checked_item_count: int
    generated_at: datetime
    created_at: datetime
    updated_at: datetime


class GroceryListListResponse(BaseModel):
    items: list[GroceryListSummaryResponse]
    total: int


class GroceryListItemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    category: GroceryCategory = GroceryCategory.OTHER

    @field_validator("name", "unit")
    @classmethod
    def text_fields_not_blank(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class GroceryListItemUpdateRequest(BaseModel):
    checked: bool | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    category: GroceryCategory | None = None

    @field_validator("unit")
    @classmethod
    def unit_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("unit cannot be blank")
        return normalized

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if (
            self.checked is None
            and self.quantity is None
            and self.unit is None
            and self.category is None
        ):
            raise ValueError("At least one grocery item field must be provided.")
        return self
