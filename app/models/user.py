from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import MembershipTier
from app.models.base import TimestampedUUIDBase


class User(TimestampedUUIDBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    membership_tier: Mapped[MembershipTier] = mapped_column(
        Enum(
            MembershipTier,
            values_callable=lambda enum_class: [
                item.value for item in enum_class
            ],
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=MembershipTier.FREE,
        server_default=MembershipTier.FREE.value,
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    profile = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    allergies = relationship(
        "UserAllergy",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    dietary_restrictions = relationship(
        "UserDietaryRestriction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    preferred_foods = relationship(
        "UserPreferredFood",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    disliked_foods = relationship(
        "UserDislikedFood",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    equipment = relationship(
        "UserEquipment",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    meal_plans = relationship(
        "MealPlan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
