import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.enums import ActivityLevel, Goal
from app.core.security import get_current_user
from app.main import app
from app.models.user import User
from app.nutrition.bmr import calculate_bmr, round_nutrition_output
from app.nutrition.calories import calculate_target_calories
from app.nutrition.constants import (
    CARBS_KCAL_PER_G,
    FAT_G_PER_KG,
    FAT_KCAL_PER_G,
    PROTEIN_G_PER_KG_BY_GOAL,
    PROTEIN_KCAL_PER_G,
)
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.macros import (
    calculate_fat_g,
    calculate_macro_calories,
    calculate_macros,
    calculate_protein_g,
)
from app.nutrition.micronutrients import (
    MICRONUTRIENT_REFERENCE_VALUES,
    SUPPORTED_NUTRIENT_CODES,
    MicronutrientReferenceDataError,
    MicronutrientTargetError,
    get_micronutrient_targets,
)
from app.nutrition.targets import calculate_nutrition_targets
from app.nutrition.tdee import ACTIVITY_MULTIPLIERS, calculate_tdee, get_activity_multiplier


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture
def nutrition_db():
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("users"):
                pytest.skip("users table is not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    db = SessionLocal()
    created_emails: list[str] = []

    def track(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    yield db, track

    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)
    db.commit()
    db.close()


@pytest.fixture
def authenticated_user_override():
    def override_current_user() -> User:
        return User(
            email="nutrition-test@example.com",
            password_hash="not-used",
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = override_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique_email(prefix: str = "nutrition") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def register_and_login(email: str) -> str:
    register_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert register_response.status_code == 201

    login_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def nutrition_payload() -> dict:
    return {
        "age": 29,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "activity_level": "moderate",
        "goal": "fat_loss",
        "target_rate": 0.5,
    }


def profile_payload(**overrides) -> dict:
    payload = {
        "age": 29,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "activity_level": "moderate",
        "goal": "fat_loss",
        "target_rate": 0.5,
        "max_cooking_minutes": 20,
        "meals_per_day": 4,
        "allergies": [],
        "dietary_restrictions": [],
        "preferred_foods": [],
        "disliked_foods": [],
        "equipment": ["stove"],
    }
    return payload | overrides


def calculate_nutrition(token: str, payload: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/nutrition/calculate",
            headers=auth_headers(token),
            json=payload or nutrition_payload(),
        )
    )


def create_profile(token: str, payload: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=payload or profile_payload(),
        )
    )


def get_micronutrients(token: str):
    return run_async(
        api_request(
            "GET",
            "/api/v1/nutrition/micronutrients",
            headers=auth_headers(token),
        )
    )


def targets_by_code(age: int, sex: str) -> dict:
    return {target.nutrient_code: target for target in get_micronutrient_targets(age=age, sex=sex)}


def test_male_bmr_uses_mifflin_st_jeor_formula() -> None:
    result = calculate_bmr(age=29, sex="male", height_cm=178, weight_kg=82)

    assert result == pytest.approx(1792.5)


def test_female_bmr_uses_mifflin_st_jeor_formula() -> None:
    result = calculate_bmr(age=30, sex="female", height_cm=165, weight_kg=60)

    assert result == pytest.approx(1320.25)


@pytest.mark.parametrize(
    ("activity_level", "multiplier"),
    [
        ("sedentary", 1.2),
        ("light", 1.375),
        ("moderate", 1.55),
        ("very_active", 1.725),
        ("extra_active", 1.9),
    ],
)
def test_activity_multipliers(activity_level: str, multiplier: float) -> None:
    assert get_activity_multiplier(activity_level) == pytest.approx(multiplier)


def test_activity_multiplier_mapping_supports_current_profile_values() -> None:
    assert set(ACTIVITY_MULTIPLIERS) == set(ActivityLevel)


def test_tdee_multiplies_bmr_by_activity_multiplier() -> None:
    result = calculate_tdee(bmr=1792.5, activity_level="moderate")

    assert result == pytest.approx(2778.375)


def test_nutrition_output_rounds_to_one_decimal_place() -> None:
    assert round_nutrition_output(2778.375) == 2778.4


@pytest.mark.parametrize(
    ("goal", "target_rate", "expected_calories"),
    [
        ("maintenance", None, 2500.0),
        ("fat_loss", 0.5, 2000.0),
        ("muscle_gain", 0.2, 2700.0),
        ("recomposition", 0.5, 2500.0),
    ],
)
def test_target_calories_by_goal(
    goal: str,
    target_rate: float | None,
    expected_calories: float,
) -> None:
    result = calculate_target_calories(
        tdee=2500,
        goal=goal,
        target_rate=target_rate,
    )

    assert result == pytest.approx(expected_calories)


def test_default_target_rates_are_used_for_adjusted_goals() -> None:
    assert calculate_target_calories(tdee=2500, goal="fat_loss") == pytest.approx(2000.0)
    assert calculate_target_calories(tdee=2500, goal="muscle_gain") == pytest.approx(2750.0)


@pytest.mark.parametrize(
    ("goal", "expected_protein"),
    [
        ("maintenance", 131.2),
        ("fat_loss", 164.0),
        ("muscle_gain", 147.6),
        ("recomposition", 164.0),
    ],
)
def test_protein_calculation_uses_goal_factor(goal: str, expected_protein: float) -> None:
    assert calculate_protein_g(weight_kg=82, goal=goal) == pytest.approx(expected_protein)
    assert PROTEIN_G_PER_KG_BY_GOAL[Goal(goal)] > 0


def test_fat_calculation_uses_weight_based_floor() -> None:
    assert calculate_fat_g(weight_kg=82) == pytest.approx(65.6)
    assert FAT_G_PER_KG == pytest.approx(0.8)


def test_carbs_fill_remaining_calories() -> None:
    macros = calculate_macros(target_calories=2278.375, weight_kg=82, goal="fat_loss")

    assert macros.protein_g == pytest.approx(164.0)
    assert macros.fat_g == pytest.approx(65.6)
    assert macros.carbs_g == pytest.approx(257.99375)


def test_macro_calories_match_target_calories() -> None:
    targets = calculate_nutrition_targets(
        age=29,
        sex="male",
        height_cm=178,
        weight_kg=82,
        activity_level="moderate",
        goal="fat_loss",
        target_rate=0.5,
    )

    assert calculate_macro_calories(targets.macros) == pytest.approx(targets.target_calories)


def test_kcal_per_gram_constants_remain_standard() -> None:
    assert PROTEIN_KCAL_PER_G == 4
    assert CARBS_KCAL_PER_G == 4
    assert FAT_KCAL_PER_G == 9


def test_male_adult_micronutrient_target_set() -> None:
    targets = targets_by_code(age=29, sex="male")

    assert set(targets) == set(SUPPORTED_NUTRIENT_CODES)
    assert targets["fiber"].amount == 38
    assert targets["calcium"].amount == 1000
    assert targets["iron"].amount == 8
    assert targets["magnesium"].amount == 400
    assert targets["potassium"].amount == 3400
    assert targets["sodium"].amount == 1500
    assert targets["vitamin_a"].amount == 900
    assert targets["vitamin_c"].amount == 90
    assert targets["vitamin_d"].amount == 15
    assert targets["vitamin_b12"].amount == 2.4
    assert targets["folate"].amount == 400


def test_female_adult_micronutrient_target_set() -> None:
    targets = targets_by_code(age=29, sex="female")

    assert targets["fiber"].amount == 25
    assert targets["iron"].amount == 18
    assert targets["magnesium"].amount == 310
    assert targets["potassium"].amount == 2600
    assert targets["vitamin_a"].amount == 700
    assert targets["vitamin_c"].amount == 75


def test_micronutrient_age_band_selection() -> None:
    age_29 = targets_by_code(age=29, sex="male")
    age_31 = targets_by_code(age=31, sex="male")
    age_71 = targets_by_code(age=71, sex="male")

    assert age_29["magnesium"].amount == 400
    assert age_31["magnesium"].amount == 420
    assert age_29["vitamin_d"].amount == 15
    assert age_71["vitamin_d"].amount == 20
    assert age_71["fiber"].amount == 30
    assert age_71["calcium"].amount == 1200


def test_iron_differs_by_sex_where_reference_requires() -> None:
    assert targets_by_code(age=29, sex="male")["iron"].amount == 8
    assert targets_by_code(age=29, sex="female")["iron"].amount == 18
    assert targets_by_code(age=51, sex="female")["iron"].amount == 8


def test_micronutrient_units_are_valid() -> None:
    targets = targets_by_code(age=29, sex="male")

    assert targets["fiber"].unit == "g"
    assert targets["calcium"].unit == "mg"
    assert targets["iron"].unit == "mg"
    assert targets["magnesium"].unit == "mg"
    assert targets["potassium"].unit == "mg"
    assert targets["sodium"].unit == "mg"
    assert targets["vitamin_a"].unit == "mcg RAE"
    assert targets["vitamin_c"].unit == "mg"
    assert targets["vitamin_d"].unit == "mcg"
    assert targets["vitamin_b12"].unit == "mcg"
    assert targets["folate"].unit == "mcg DFE"


def test_micronutrient_upper_limits() -> None:
    targets = targets_by_code(age=29, sex="male")

    assert targets["fiber"].upper_limit is None
    assert targets["calcium"].upper_limit == 2500
    assert targets["iron"].upper_limit == 45
    assert targets["magnesium"].upper_limit == 350
    assert targets["magnesium"].upper_limit_type == "UL_SUPPLEMENTAL"
    assert targets["potassium"].upper_limit is None
    assert targets["sodium"].upper_limit == 2300
    assert targets["sodium"].upper_limit_type == "CDRR"
    assert targets["vitamin_a"].upper_limit == 3000
    assert targets["vitamin_c"].upper_limit == 2000
    assert targets["vitamin_d"].upper_limit == 100
    assert targets["vitamin_b12"].upper_limit is None
    assert targets["folate"].upper_limit == 1000
    assert targets["folate"].upper_limit_unit == "mcg folic acid"


def test_unsupported_micronutrient_age_range_fails() -> None:
    with pytest.raises(MicronutrientReferenceDataError, match="age 12"):
        get_micronutrient_targets(age=12, sex="male")


def test_invalid_micronutrient_sex_fails() -> None:
    with pytest.raises(MicronutrientTargetError, match="Unsupported sex"):
        get_micronutrient_targets(age=29, sex="other")


def test_missing_reference_data_fails() -> None:
    reference_values_without_calcium = tuple(
        value for value in MICRONUTRIENT_REFERENCE_VALUES if value.nutrient_code != "calcium"
    )

    with pytest.raises(MicronutrientReferenceDataError, match="calcium"):
        get_micronutrient_targets(
            age=29,
            sex="male",
            reference_values=reference_values_without_calcium,
        )


def test_negative_carbs_are_rejected() -> None:
    with pytest.raises(NutritionCalculationError, match="too low"):
        calculate_macros(target_calories=800, weight_kg=120, goal="fat_loss")


@pytest.mark.parametrize("target_rate", [-0.1, 0, 3])
def test_invalid_target_rate_fails(target_rate: float) -> None:
    with pytest.raises(NutritionCalculationError, match="target_rate"):
        calculate_target_calories(tdee=2500, goal="fat_loss", target_rate=target_rate)


def test_invalid_goal_fails() -> None:
    with pytest.raises(NutritionCalculationError, match="Unsupported goal"):
        calculate_target_calories(tdee=2500, goal="bulk_cut")


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        ({"age": -1, "sex": "male", "height_cm": 178, "weight_kg": 82}, "age"),
        ({"age": 29, "sex": "male", "height_cm": 0, "weight_kg": 82}, "height_cm"),
        ({"age": 29, "sex": "male", "height_cm": 178, "weight_kg": -1}, "weight_kg"),
        ({"age": 29, "sex": "other", "height_cm": 178, "weight_kg": 82}, "other"),
    ],
)
def test_invalid_bmr_inputs_fail(kwargs: dict, expected_message: str) -> None:
    with pytest.raises(ValueError, match=expected_message):
        calculate_bmr(**kwargs)


def test_invalid_activity_level_fails() -> None:
    with pytest.raises(ValueError, match="sometimes"):
        calculate_tdee(bmr=1792.5, activity_level="sometimes")


def test_authenticated_user_can_calculate_nutrition_targets(authenticated_user_override) -> None:
    response = calculate_nutrition("test-token")

    assert response.status_code == 200
    assert response.json() == {
        "bmr": 1792.5,
        "tdee": 2778.4,
        "target_calories": 2278.4,
        "macros": {
            "protein_g": 164.0,
            "carbs_g": 258.0,
            "fat_g": 65.6,
        },
    }


def test_bearer_token_user_can_calculate_nutrition_targets(nutrition_db) -> None:
    _, track = nutrition_db
    email = track(unique_email())
    token = register_and_login(email)

    response = calculate_nutrition(token)

    assert response.status_code == 200
    assert response.json()["target_calories"] == 2278.4
    assert response.json()["macros"] == {
        "protein_g": 164.0,
        "carbs_g": 258.0,
        "fat_g": 65.6,
    }


def test_nutrition_calculation_requires_authentication() -> None:
    response = run_async(
        api_request(
            "POST",
            "/api/v1/nutrition/calculate",
            json=nutrition_payload(),
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_authenticated_user_can_read_micronutrient_targets(nutrition_db) -> None:
    _, track = nutrition_db
    email = track(unique_email("micronutrients"))
    token = register_and_login(email)
    assert create_profile(token, profile_payload(age=29, sex="male")).status_code == 201

    response = get_micronutrients(token)

    assert response.status_code == 200
    body = response.json()
    micronutrients = {item["code"]: item for item in body["micronutrients"]}
    assert set(micronutrients) == set(SUPPORTED_NUTRIENT_CODES)
    assert micronutrients["calcium"]["target"] == 1000
    assert micronutrients["calcium"]["unit"] == "mg"
    assert micronutrients["calcium"]["upper_limit"] == 2500
    assert micronutrients["iron"]["target"] == 8
    assert micronutrients["iron"]["upper_limit"] == 45
    assert micronutrients["sodium"]["upper_limit_type"] == "CDRR"


def test_micronutrient_targets_missing_profile_returns_profile_not_found(nutrition_db) -> None:
    _, track = nutrition_db
    email = track(unique_email("no-profile"))
    token = register_and_login(email)

    response = get_micronutrients(token)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_micronutrient_targets_require_authentication() -> None:
    response = run_async(api_request("GET", "/api/v1/nutrition/micronutrients"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("age", -1),
        ("height_cm", 0),
        ("weight_kg", -1),
        ("sex", "other"),
        ("activity_level", "sometimes"),
        ("goal", "bulk_cut"),
        ("target_rate", -0.5),
    ],
)
def test_invalid_nutrition_payload_fails(
    authenticated_user_override,
    field_name: str,
    value,
) -> None:
    payload = nutrition_payload() | {field_name: value}

    response = calculate_nutrition("test-token", payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_impossible_nutrition_calculation_returns_controlled_error(
    authenticated_user_override,
) -> None:
    payload = {
        "age": 120,
        "sex": "female",
        "height_cm": 50,
        "weight_kg": 20,
        "activity_level": "sedentary",
        "goal": "fat_loss",
        "target_rate": 0.5,
    }

    response = calculate_nutrition("test-token", payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NUTRITION_CALCULATION_ERROR"
