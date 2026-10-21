from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedUUIDBase


class StepLog(TimestampedUUIDBase):
    __tablename__ = "step_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_step_logs_user_date"),
        CheckConstraint("steps >= 0 and steps <= 200000", name="ck_step_logs_range"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date)
    steps: Mapped[int] = mapped_column(Integer)
