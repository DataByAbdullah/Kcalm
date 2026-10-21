import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.models.user_profile import UserAllergy, UserDietaryRestriction, UserEquipment


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_profile_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "user_allergies",
                "user_dietary_restrictions",
                "user_equipment",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("user profile tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def profile_db():
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


def unique_email(prefix: str = "profile") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def base_profile_payload() -> dict:
    return {
        "age": 29,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "target_weight_kg": 75,
        "activity_level": "moderate",
        "goal": "fat_loss",
        "target_rate": 0.5,
        "max_cooking_minutes": 20,
        "meals_per_day": 4,
        "allergies": ["peanuts"],
        "dietary_restrictions": ["halal"],
        "preferred_foods": ["chicken", "rice"],
        "disliked_foods": ["mushrooms"],
        "equipment": ["stove", "microwave", "air_fryer"],
    }


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


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_profile(token: str, payload: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=payload or base_profile_payload(),
        )
    )


def get_profile(token: str):
    return run_async(api_request("GET", "/api/v1/users/profile", headers=auth_headers(token)))


def patch_profile(token: str, payload: dict):
    return run_async(
        api_request(
            "PATCH",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=payload,
        )
    )


def test_authenticated_user_can_create_profile(profile_db) -> None:
    db, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)

    response = create_profile(token)

    assert response.status_code == 201
    body = response.json()
    assert body["age"] == 29
    assert body["goal"] == "fat_loss"
    assert body["target_weight_kg"] == 75
    user = db.query(User).filter(User.email == email).one()
    assert user.profile is not None


def test_unauthenticated_user_cannot_create_profile() -> None:
    response = run_async(api_request("POST", "/api/v1/users/profile", json=base_profile_payload()))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_duplicate_profile_creation_fails(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    first_response = create_profile(token)

    response = create_profile(token)

    assert first_response.status_code == 201
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_ALREADY_EXISTS"


def test_profile_belongs_to_correct_user(profile_db) -> None:
    _, track = profile_db
    email_one = track(unique_email("one"))
    email_two = track(unique_email("two"))
    token_one = register_and_login(email_one)
    token_two = register_and_login(email_two)
    payload_one = base_profile_payload()
    payload_two = base_profile_payload() | {"age": 41, "weight_kg": 91}

    assert create_profile(token_one, payload_one).status_code == 201
    assert create_profile(token_two, payload_two).status_code == 201

    assert get_profile(token_one).json()["age"] == 29
    assert get_profile(token_two).json()["age"] == 41


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("age", 0),
        ("height_cm", 20),
        ("weight_kg", 5),
        ("target_weight_kg", 5),
        ("meals_per_day", 99),
    ],
)
def test_invalid_numeric_profile_values_fail(profile_db, field_name: str, value) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    payload = base_profile_payload() | {field_name: value}

    response = create_profile(token, payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PROFILE_DATA"


def test_invalid_activity_level_fails(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    payload = base_profile_payload() | {"activity_level": "sometimes"}

    response = create_profile(token, payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PROFILE_DATA"


def test_invalid_goal_fails(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    payload = base_profile_payload() | {"goal": "bulk_cut"}

    response = create_profile(token, payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PROFILE_DATA"


def test_duplicate_and_whitespace_values_are_normalized(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    payload = base_profile_payload() | {
        "allergies": [" Peanuts ", "peanuts", "PEANUTS", " "],
        "preferred_foods": [" Chicken ", "chicken", "RICE", "rice"],
        "equipment": [" Stove ", "stove", "MICROWAVE"],
    }

    response = create_profile(token, payload)

    assert response.status_code == 201
    body = response.json()
    assert body["allergies"] == ["peanuts"]
    assert body["preferred_foods"] == ["chicken", "rice"]
    assert body["equipment"] == ["microwave", "stove"]


def test_authenticated_user_receives_own_profile_with_all_lists(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = get_profile(token)

    assert response.status_code == 200
    body = response.json()
    assert body["allergies"] == ["peanuts"]
    assert body["dietary_restrictions"] == ["halal"]
    assert body["preferred_foods"] == ["chicken", "rice"]
    assert body["disliked_foods"] == ["mushrooms"]
    assert set(body["equipment"]) == {"stove", "microwave", "air_fryer"}


def test_missing_profile_returns_error(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)

    response = get_profile(token)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_weight_only_patch_works(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = patch_profile(token, {"weight_kg": 80})

    assert response.status_code == 200
    assert response.json()["weight_kg"] == 80

def test_target_weight_patch_works(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = patch_profile(
        token,
        {"target_weight_kg": 72},
    )

    assert response.status_code == 200
    assert response.json()["target_weight_kg"] == 72

def test_goal_and_cooking_time_update_works(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = patch_profile(token, {"goal": "maintenance", "max_cooking_minutes": 15})

    assert response.status_code == 200
    assert response.json()["goal"] == "maintenance"
    assert response.json()["max_cooking_minutes"] == 15


def test_list_replacement_and_omitted_fields_behavior(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = patch_profile(token, {"equipment": ["stove", "air_fryer"], "allergies": []})

    assert response.status_code == 200
    body = response.json()
    assert body["equipment"] == ["air_fryer", "stove"]
    assert body["allergies"] == []
    assert body["preferred_foods"] == ["chicken", "rice"]
    assert body["weight_kg"] == 82


def test_invalid_patch_does_not_partially_update(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201

    response = patch_profile(token, {"weight_kg": 80, "meals_per_day": 99})
    current_profile = get_profile(token)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PROFILE_DATA"
    assert current_profile.json()["weight_kg"] == 82
    assert current_profile.json()["meals_per_day"] == 4


def test_relationship_records_are_persisted(profile_db) -> None:
    db, track = profile_db
    email = track(unique_email())
    token = register_and_login(email)
    assert create_profile(token).status_code == 201
    user = db.query(User).filter(User.email == email).one()

    assert db.query(UserAllergy).filter(UserAllergy.user_id == user.id).count() == 1
    assert (
        db.query(UserDietaryRestriction)
        .filter(UserDietaryRestriction.user_id == user.id)
        .count()
        == 1
    )
    assert db.query(UserEquipment).filter(UserEquipment.user_id == user.id).count() == 3


def test_invalid_auth_behavior_remains_correct() -> None:
    response = run_async(
        api_request(
            "GET",
            "/api/v1/users/profile",
            headers={"Authorization": "Bearer not-a-token"},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_auth_behavior_remains_correct(profile_db) -> None:
    _, track = profile_db
    email = track(unique_email())
    register_and_login(email)
    settings = get_settings()
    expired_token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = get_profile(expired_token)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_inactive_auth_behavior_remains_correct(profile_db) -> None:
    db, track = profile_db
    email = track(unique_email())
    register_and_login(email)
    user = db.query(User).filter(User.email == email).one()
    token = create_access_token(user.id)

    user.is_active = False
    db.commit()

    response = get_profile(token)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_INACTIVE"
