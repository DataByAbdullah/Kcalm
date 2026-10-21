from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedUUIDBase


class WeightLog(TimestampedUUIDBase):
    __tablename__ = "weight_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_weight_logs_user_date"),
        CheckConstraint("weight_kg >= 20 and weight_kg <= 500", name="ck_weight_logs_range"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[float] = mapped_column(Float)
