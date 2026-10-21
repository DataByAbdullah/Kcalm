from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    VERY_ACTIVE = "very_active"
    EXTRA_ACTIVE = "extra_active"


class Goal(StrEnum):
    FAT_LOSS = "fat_loss"
    MUSCLE_GAIN = "muscle_gain"
    MAINTENANCE = "maintenance"
    RECOMPOSITION = "recomposition"


class FoodSource(StrEnum):
    INTERNAL = "internal"
    USDA = "usda"
    LICENSED = "licensed"


class MealPlanStatus(StrEnum):
    GENERATED = "generated"
    ARCHIVED = "archived"


class WeeklyMealPlanStatus(StrEnum):
    GENERATED = "generated"
    ARCHIVED = "archived"


class GroceryListStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class GroceryCategory(StrEnum):
    PRODUCE = "produce"
    MEAT_SEAFOOD = "meat_seafood"
    DAIRY = "dairy"
    GRAINS = "grains"
    PANTRY = "pantry"
    FROZEN = "frozen"
    OTHER = "other"


class MealLogType(StrEnum):
    ATE_AS_PLANNED = "ate_as_planned"
    CORRECTED = "corrected"


class MealLogStatus(StrEnum):
    ACTIVE = "active"


class MealLogSourceType(StrEnum):
    FOOD = "food"
    RECIPE = "recipe"


class RecipeStepPhase(StrEnum):
    PREP = "prep"
    COOK = "cook"
    REST = "rest"
    ASSEMBLE = "assemble"
    SERVE = "serve"


class RecipeExecutionStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"



class MembershipTier(StrEnum):
    FREE = "free"
    PREMIUM = "premium"