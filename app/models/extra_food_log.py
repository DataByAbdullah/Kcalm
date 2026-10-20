from datetime import date
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedUUIDBase


class ExtraFoodLog(TimestampedUUIDBase):
    __tablename__ = "extra_food_logs"
    __table_args__ = (
        Index("ix_extra_food_logs_user_id", "user_id"),
        Index("ix_extra_food_logs_log_date", "log_date"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    log_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    food_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("foods.id"),
        nullable=True,
    )

    quantity_grams: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    calories: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    protein_g: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    carbs_g: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    fat_g: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    user = relationship("User")
    food = relationship("Food")
    nutrients = relationship(
        "ExtraFoodLogNutrientSnapshot",
        back_populates="extra_food_log",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExtraFoodLogNutrientSnapshot.nutrient_code",
    )

class ExtraFoodLogNutrientSnapshot(TimestampedUUIDBase):
    __tablename__ = "extra_food_log_nutrients"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_extra_food_log_nutrients_amount_non_negative",
        ),
        UniqueConstraint(
            "extra_food_log_id",
            "nutrient_code",
            name="uq_extra_food_log_nutrients_log_code",
        ),
        Index(
            "ix_extra_food_log_nutrients_extra_food_log_id",
            "extra_food_log_id",
        ),
        Index(
            "ix_extra_food_log_nutrients_nutrient_code",
            "nutrient_code",
        ),
    )

    extra_food_log_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "extra_food_logs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    nutrient_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    nutrient_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    amount: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    extra_food_log = relationship(
        "ExtraFoodLog",
        back_populates="nutrients",
    )