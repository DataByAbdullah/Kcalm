from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FoodSource
from app.models.base import TimestampedUUIDBase
from app.models.user_profile import enum_values


class Food(TimestampedUUIDBase):
    __tablename__ = "foods"
    __table_args__ = (
        CheckConstraint(
            "source in ('internal', 'usda', 'licensed')",
            name="ck_foods_source_valid",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_foods_name_not_blank"),
        CheckConstraint("length(btrim(category)) > 0", name="ck_foods_category_not_blank"),
        UniqueConstraint("source", "source_food_id", name="uq_foods_source_source_food_id"),
        Index("ix_foods_name", "name"),
        Index("ix_foods_category", "category"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[FoodSource] = mapped_column(
        Enum(FoodSource, values_callable=enum_values, native_enum=False, length=32),
        nullable=False,
        default=FoodSource.INTERNAL,
    )
    source_food_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    nutrients = relationship(
        "FoodNutrient",
        back_populates="food",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FoodNutrient.nutrient_code",
    )
    servings = relationship(
        "FoodServing",
        back_populates="food",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FoodServing.serving_name",
    )


class FoodNutrient(TimestampedUUIDBase):
    __tablename__ = "food_nutrients"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_food_nutrients_amount_non_negative"),
        CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_food_nutrients_code_not_blank",
        ),
        CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_food_nutrients_name_not_blank",
        ),
        CheckConstraint("length(btrim(unit)) > 0", name="ck_food_nutrients_unit_not_blank"),
        UniqueConstraint("food_id", "nutrient_code", name="uq_food_nutrients_food_id_code"),
        Index("ix_food_nutrients_food_id", "food_id"),
        Index("ix_food_nutrients_nutrient_code", "nutrient_code"),
    )

    food_id: Mapped[UUID] = mapped_column(
        ForeignKey("foods.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    nutrient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    food = relationship("Food", back_populates="nutrients")


class FoodServing(TimestampedUUIDBase):
    __tablename__ = "food_servings"
    __table_args__ = (
        CheckConstraint("grams > 0", name="ck_food_servings_grams_positive"),
        CheckConstraint(
            "length(btrim(serving_name)) > 0",
            name="ck_food_servings_name_not_blank",
        ),
        UniqueConstraint("food_id", "serving_name", name="uq_food_servings_food_id_name"),
        Index("ix_food_servings_food_id", "food_id"),
    )

    food_id: Mapped[UUID] = mapped_column(
        ForeignKey("foods.id", ondelete="CASCADE"),
        nullable=False,
    )
    serving_name: Mapped[str] = mapped_column(String(128), nullable=False)
    grams: Mapped[float] = mapped_column(Float, nullable=False)

    food = relationship("Food", back_populates="servings")
