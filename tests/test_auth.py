import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.security import create_access_token, hash_password, verify_password
from app.main import app
from app.models.user import User


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture(autouse=True)
def require_users_table():
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("users"):
                pytest.skip("users table is not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def auth_db():
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


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def register_user(email: str, password: str = "StrongPassword123"):
    return run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
    )


def login_user(email: str, password: str = "StrongPassword123"):
    return run_async(
        api_request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
    )


def test_registration_succeeds(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())

    response = register_user(email)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body
    assert db.get(User, UUID(body["id"])) is not None


def test_registration_normalizes_email(auth_db) -> None:
    db, track = auth_db
    email = unique_email()
    normalized_email = track(email)

    response = register_user(f"  {email.upper()}  ")

    assert response.status_code == 201
    assert response.json()["email"] == normalized_email
    assert db.query(User).filter(User.email == normalized_email).one_or_none() is not None


def test_registration_hashes_password_and_does_not_return_hash(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())
    password = "StrongPassword123"

    response = register_user(email, password=password)

    assert response.status_code == 201
    assert "password_hash" not in response.json()
    user = db.query(User).filter(User.email == email).one()
    assert user.password_hash != password
    assert verify_password(password, user.password_hash)


def test_duplicate_email_fails(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())
    first_response = register_user(email)

    response = register_user(email.upper())

    assert first_response.status_code == 201
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_invalid_email_fails() -> None:
    response = register_user("not-an-email")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_weak_password_fails(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())

    response = register_user(email, password="short")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_correct_credentials_succeeds(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())
    register_user(email)

    response = login_user(email)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60


def test_login_incorrect_password_fails(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())
    register_user(email)

    response = login_user(email, password="WrongPassword123")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_account_fails(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())

    response = login_user(email)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_inactive_user_fails(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())
    user = User(
        email=email,
        password_hash=hash_password("StrongPassword123"),
        is_active=False,
    )
    db.add(user)
    db.commit()

    response = login_user(email)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_INACTIVE"


def test_current_user_missing_authorization_header_fails() -> None:
    response = run_async(api_request("GET", "/api/v1/auth/me"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_current_user_malformed_token_fails() -> None:
    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-token"},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_current_user_expired_token_fails(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())
    user = User(
        email=email,
        password_hash=hash_password("StrongPassword123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    settings = get_settings()
    expired_token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_current_user_valid_token_succeeds(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email())
    register_user(email)
    token = login_user(email).json()["access_token"]

    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["is_active"] is True
    assert "password_hash" not in body


def test_current_user_inactive_user_fails(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())
    user = User(
        email=email,
        password_hash=hash_password("StrongPassword123"),
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)

    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_INACTIVE"


def test_user_persists_correctly(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email())

    response = register_user(email)
    user = db.query(User).filter(User.email == email).one()

    assert response.status_code == 201
    assert str(user.id) == response.json()["id"]
    assert user.email == email
    assert user.is_active is True
