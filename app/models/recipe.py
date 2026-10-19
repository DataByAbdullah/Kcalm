from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RecipeStepPhase
from app.models.base import TimestampedUUIDBase


class Recipe(TimestampedUUIDBase):
    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_recipes_name_not_blank"),
        CheckConstraint("servings > 0", name="ck_recipes_servings_positive"),
        CheckConstraint("prep_time_minutes >= 0", name="ck_recipes_prep_time_non_negative"),
        CheckConstraint("cook_time_minutes >= 0", name="ck_recipes_cook_time_non_negative"),
        CheckConstraint("total_time_minutes >= 0", name="ck_recipes_total_time_non_negative"),
        CheckConstraint(
            "total_time_minutes = prep_time_minutes + cook_time_minutes",
            name="ck_recipes_total_time_matches_parts",
        ),
        Index("ix_recipes_name", "name"),
        Index("ix_recipes_active", "active"),
        Index("ix_recipes_total_time_minutes", "total_time_minutes"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    servings: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cook_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instructions_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="user_created")

    ingredients = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeIngredient.position",
    )
    steps = relationship(
        "RecipeStep",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeStep.position",
    )
    tag_links = relationship(
        "RecipeTagLink",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    equipment = relationship(
        "RecipeEquipment",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeEquipment.equipment",
    )
    nutrients = relationship(
        "RecipeNutrient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeNutrient.nutrient_code",
    )


class RecipeIngredient(TimestampedUUIDBase):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        CheckConstraint("quantity_grams > 0", name="ck_recipe_ingredients_quantity_positive"),
        CheckConstraint("position > 0", name="ck_recipe_ingredients_position_positive"),
        UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredients_recipe_id_position"),
        Index("ix_recipe_ingredients_recipe_id", "recipe_id"),
        Index("ix_recipe_ingredients_food_id", "food_id"),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    food_id: Mapped[UUID] = mapped_column(ForeignKey("foods.id"), nullable=False)
    quantity_grams: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    display_quantity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preparation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    recipe = relationship("Recipe", back_populates="ingredients")
    food = relationship("Food")


class RecipeStep(TimestampedUUIDBase):
    __tablename__ = "recipe_steps"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_recipe_steps_position_positive"),
        CheckConstraint("length(btrim(instruction)) > 0", name="ck_recipe_steps_instruction_not_blank"),
        CheckConstraint(
            "phase in ('prep', 'cook', 'rest', 'assemble', 'serve')",
            name="ck_recipe_steps_phase_valid",
        ),
        CheckConstraint(
            "duration_seconds is null or duration_seconds >= 0",
            name="ck_recipe_steps_duration_non_negative",
        ),
        CheckConstraint(
            "timer_seconds is null or timer_seconds >= 0",
            name="ck_recipe_steps_timer_seconds_non_negative",
        ),
        UniqueConstraint("recipe_id", "position", name="uq_recipe_steps_recipe_id_position"),
        Index("ix_recipe_steps_recipe_id", "recipe_id"),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecipeStepPhase.COOK.value,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timer_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cue_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    animation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_asset_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    visual_cue: Mapped[str | None] = mapped_column(String(128), nullable=True)

    recipe = relationship("Recipe", back_populates="steps")


class RecipeTag(TimestampedUUIDBase):
    __tablename__ = "recipe_tags"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_recipe_tags_name_not_blank"),
        UniqueConstraint("name", name="uq_recipe_tags_name"),
        Index("ix_recipe_tags_name", "name"),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)

    recipe_links = relationship("RecipeTagLink", back_populates="tag")


class RecipeTagLink(TimestampedUUIDBase):
    __tablename__ = "recipe_tag_links"
    __table_args__ = (
        UniqueConstraint("recipe_id", "tag_id", name="uq_recipe_tag_links_recipe_id_tag_id"),
        Index("ix_recipe_tag_links_recipe_id", "recipe_id"),
        Index("ix_recipe_tag_links_tag_id", "tag_id"),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipe_tags.id", ondelete="CASCADE"),
        nullable=False,
    )

    recipe = relationship("Recipe", back_populates="tag_links")
    tag = relationship("RecipeTag", back_populates="recipe_links")


class RecipeEquipment(TimestampedUUIDBase):
    __tablename__ = "recipe_equipment"
    __table_args__ = (
        CheckConstraint("length(btrim(equipment)) > 0", name="ck_recipe_equipment_not_blank"),
        UniqueConstraint("recipe_id", "equipment", name="uq_recipe_equipment_recipe_id_equipment"),
        Index("ix_recipe_equipment_recipe_id", "recipe_id"),
        Index("ix_recipe_equipment_equipment", "equipment"),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    equipment: Mapped[str] = mapped_column(String(128), nullable=False)

    recipe = relationship("Recipe", back_populates="equipment")


class RecipeNutrient(TimestampedUUIDBase):
    __tablename__ = "recipe_nutrients"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_recipe_nutrients_total_amount_non_negative"),
        CheckConstraint(
            "per_serving_amount >= 0",
            name="ck_recipe_nutrients_per_serving_amount_non_negative",
        ),
        CheckConstraint("missing_ingredient_count >= 0", name="ck_recipe_nutrients_missing_count_non_negative"),
        CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_recipe_nutrients_code_not_blank",
        ),
        CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_recipe_nutrients_name_not_blank",
        ),
        CheckConstraint("length(btrim(unit)) > 0", name="ck_recipe_nutrients_unit_not_blank"),
        UniqueConstraint("recipe_id", "nutrient_code", name="uq_recipe_nutrients_recipe_id_code"),
        Index("ix_recipe_nutrients_recipe_id", "recipe_id"),
        Index("ix_recipe_nutrients_nutrient_code", "nutrient_code"),
    )

    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    nutrient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    per_serving_amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    missing_ingredient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    recipe = relationship("Recipe", back_populates="nutrients")
