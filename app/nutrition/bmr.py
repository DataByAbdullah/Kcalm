from app.core.enums import Sex


def calculate_bmr(age: int, sex: Sex | str, height_cm: float, weight_kg: float) -> float:
    """Calculate BMR using the Mifflin-St Jeor equation."""
    if age <= 0:
        raise ValueError("age must be greater than 0")
    if height_cm <= 0:
        raise ValueError("height_cm must be greater than 0")
    if weight_kg <= 0:
        raise ValueError("weight_kg must be greater than 0")

    sex_value = Sex(sex)
    base_bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)

    if sex_value == Sex.MALE:
        return base_bmr + 5
    if sex_value == Sex.FEMALE:
        return base_bmr - 161

    raise ValueError(f"Unsupported sex: {sex}")


def round_nutrition_output(value: float) -> float:
    """Round nutrition API display values to one decimal place."""
    return round(value, 1)

