from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedUUIDBase


class DailyMetrics(TimestampedUUIDBase):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_daily_metrics_user_date"),
        CheckConstraint("water_glasses >= 0 and water_glasses <= 100", name="ck_daily_metrics_water_range"),
        CheckConstraint("fruit_veg_servings >= 0 and fruit_veg_servings <= 100", name="ck_daily_metrics_servings_range"),
        CheckConstraint("sleep_hours >= 0 and sleep_hours <= 24", name="ck_daily_metrics_sleep_range"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date)
    water_glasses: Mapped[int] = mapped_column(Integer)
    fruit_veg_servings: Mapped[float] = mapped_column(Float)
    sleep_hours: Mapped[float] = mapped_column(Float)
