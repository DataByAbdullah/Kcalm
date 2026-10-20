from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ExtraFoodLogCreateRequest(BaseModel):
    log_date: date

    food_id: UUID | None = None
    quantity_grams: float | None = Field(default=None, gt=0)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_entry(self) -> Self:
        if self.food_id is not None:
            if self.quantity_grams is None:
                raise ValueError(
                    "Food entries require quantity_grams."
                )

            if any(
                value is not None
                for value in (
                    self.calories,
                    self.protein_g,
                    self.carbs_g,
                    self.fat_g,
                )
            ):
                raise ValueError(
                    "Food entries cannot include custom nutrition values."
                )

            return self

        if self.quantity_grams is not None:
            raise ValueError(
                "quantity_grams requires food_id."
            )

        if self.name is None or not self.name.strip():
            raise ValueError(
                "Custom entries require name."
            )

        if any(
            value is None
            for value in (
                self.calories,
                self.protein_g,
                self.carbs_g,
                self.fat_g,
            )
        ):
            raise ValueError(
                "Custom entries require calories, protein_g, carbs_g and fat_g."
            )

        return self


class ExtraFoodLogResponse(BaseModel):
    id: UUID
    log_date: date
    name: str
    food_id: UUID | None
    quantity_grams: float | None
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    created_at: datetime
    updated_at: datetime
