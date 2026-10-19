from uuid import UUID

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActivityLevel, Goal, Sex
from app.models.base import TimestampedUUIDBase


def enum_values(enum_class):
    return [item.value for item in enum_class]


class UserProfile(TimestampedUUIDBase):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, values_callable=enum_values, native_enum=False, length=16),
        nullable=False,
    )
    height_cm: Mapped[float] = mapped_column(Float, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    activity_level: Mapped[ActivityLevel] = mapped_column(
        Enum(ActivityLevel, values_callable=enum_values, native_enum=False, length=32),
        nullable=False,
    )
    goal: Mapped[Goal] = mapped_column(
        Enum(Goal, values_callable=enum_values, native_enum=False, length=32),
        nullable=False,
    )
    target_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cooking_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    meals_per_day: Mapped[int] = mapped_column(Integer, nullable=False)

    user = relationship("User", back_populates="profile")


class UserAllergy(TimestampedUUIDBase):
    __tablename__ = "user_allergies"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_allergies_user_id_name"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    user = relationship("User", back_populates="allergies")


class UserDietaryRestriction(TimestampedUUIDBase):
    __tablename__ = "user_dietary_restrictions"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_dietary_restrictions_user_id_name"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    user = relationship("User", back_populates="dietary_restrictions")


class UserPreferredFood(TimestampedUUIDBase):
    __tablename__ = "user_preferred_foods"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_preferred_foods_user_id_name"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    user = relationship("User", back_populates="preferred_foods")


class UserDislikedFood(TimestampedUUIDBase):
    __tablename__ = "user_disliked_foods"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_disliked_foods_user_id_name"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    user = relationship("User", back_populates="disliked_foods")


class UserEquipment(TimestampedUUIDBase):
    __tablename__ = "user_equipment"
    __table_args__ = (UniqueConstraint("user_id", "equipment", name="uq_user_equipment_user_id_equipment"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    equipment: Mapped[str] = mapped_column(String(128), nullable=False)

    user = relationship("User", back_populates="equipment")
