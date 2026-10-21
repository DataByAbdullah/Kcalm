from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedUUIDBase


class Notification(TimestampedUUIDBase):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_key: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(String(1000))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
