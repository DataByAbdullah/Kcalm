from app.core.enums import ActivityLevel


ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.55,
    ActivityLevel.VERY_ACTIVE: 1.725,
    ActivityLevel.EXTRA_ACTIVE: 1.9,
}


def get_activity_multiplier(activity_level: ActivityLevel | str) -> float:
    activity_level_value = ActivityLevel(activity_level)
    return ACTIVITY_MULTIPLIERS[activity_level_value]


def calculate_tdee(bmr: float, activity_level: ActivityLevel | str) -> float:
    """Calculate TDEE from BMR and a supported activity multiplier."""
    if bmr <= 0:
        raise ValueError("bmr must be greater than 0")

    return bmr * get_activity_multiplier(activity_level)

