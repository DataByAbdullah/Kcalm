from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedUUIDBase


class Habit(TimestampedUUIDBase):
    __tablename__ = "habits"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_habits_name"),
        Index("ix_habits_user_id", "user_id"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    completions = relationship("HabitCompletion", cascade="all, delete-orphan", passive_deletes=True)


class HabitCompletion(TimestampedUUIDBase):
    __tablename__ = "habit_completions"
    __table_args__ = (UniqueConstraint("habit_id", "log_date", name="uq_habit_completions_habit_date"),)
    habit_id: Mapped[UUID] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date)
