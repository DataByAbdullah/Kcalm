from datetime import date
from uuid import UUID

from sqlalchemy import Date, Float, ForeignKey, Index, String
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
