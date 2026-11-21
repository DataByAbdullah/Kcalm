"""Durable password-reset work; recipient addresses and tokens are never stored."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedUUIDBase


class PasswordResetJob(TimestampedUUIDBase):
    __tablename__ = "password_reset_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','accepted','discarded','failed')", name="ck_reset_jobs_status"),
        CheckConstraint("attempts >= 0", name="ck_reset_jobs_attempts"),
        CheckConstraint("(user_id IS NULL) = (password_fingerprint IS NULL)", name="ck_reset_jobs_subject"),
        CheckConstraint("(status = 'processing' AND lease_id IS NOT NULL AND lease_until IS NOT NULL) OR "
                        "(status <> 'processing' AND lease_id IS NULL AND lease_until IS NULL)", name="ck_reset_jobs_lease"),
        Index("ix_reset_jobs_available", "status", "available_at"),
        Index("ix_reset_jobs_lease", "lease_until"),
        Index("ix_reset_jobs_user", "user_id"),
        Index("ix_reset_jobs_cleanup", "status", "updated_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    password_fingerprint: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(40))
