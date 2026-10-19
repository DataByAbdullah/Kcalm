"""SQLAlchemy models and reusable model utilities."""

from app.models.base import TimestampMixin, TimestampedUUIDBase, UUIDPrimaryKeyMixin
from app.models.adaptation import MealPlanAdaptationSnapshot
from app.models.food import Food, FoodNutrient, FoodServing
from app.models.grocery import GroceryList, GroceryListItem
from app.models.meal_log import MealLog, MealLogNutrientSnapshot
from app.models.meal_plan import (
    MealPlan,
    MealPlanItemIngredientSnapshot,
    MealPlanItem,
    MealPlanItemNutrientSnapshot,
    MealPlanMicronutrientTargetSnapshot,
    WeeklyMealPlan,
)
from app.models.recipe import (
    Recipe,
    RecipeEquipment,
    RecipeIngredient,
    RecipeNutrient,
    RecipeStep,
    RecipeTag,
    RecipeTagLink,
)
from app.models.recipe_execution import (
    RecipeExecutionSession,
    RecipeExecutionStepSnapshot,
)
from app.models.user import User
from app.models.user_profile import (
    UserAllergy,
    UserDietaryRestriction,
    UserDislikedFood,
    UserEquipment,
    UserPreferredFood,
    UserProfile,
)

__all__ = [
    "TimestampMixin",
    "TimestampedUUIDBase",
    "UUIDPrimaryKeyMixin",
    "MealPlanAdaptationSnapshot",
    "Food",
    "FoodNutrient",
    "FoodServing",
    "GroceryList",
    "GroceryListItem",
    "MealLog",
    "MealLogNutrientSnapshot",
    "MealPlan",
    "MealPlanItem",
    "MealPlanItemIngredientSnapshot",
    "MealPlanItemNutrientSnapshot",
    "MealPlanMicronutrientTargetSnapshot",
    "WeeklyMealPlan",
    "Recipe",
    "RecipeEquipment",
    "RecipeIngredient",
    "RecipeNutrient",
    "RecipeStep",
    "RecipeTag",
    "RecipeTagLink",
    "RecipeExecutionSession",
    "RecipeExecutionStepSnapshot",
    "User",
    "UserAllergy",
    "UserDietaryRestriction",
    "UserDislikedFood",
    "UserEquipment",
    "UserPreferredFood",
    "UserProfile",
]
