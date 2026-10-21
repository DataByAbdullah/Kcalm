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
    assert body["membership_tier"] == "free"
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
    assert body["membership_tier"] == "free"
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

def test_forgot_password_known_email_returns_generic_success(auth_db, monkeypatch) -> None:
    _, track = auth_db
    email = track(unique_email("forgot"))
    register_user(email)

    sent: dict[str, str] = {}

    def fake_send_password_reset_email(email: str, reset_token: str) -> None:
        sent["email"] = email
        sent["token"] = reset_token

    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_email",
        fake_send_password_reset_email,
    )

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/forgot-password",
            json={"email": email},
        )
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "If an account exists for this email, a password reset link has been sent."
    )
    assert sent["email"] == email
    assert sent["token"]


def test_forgot_password_unknown_email_returns_same_generic_success(auth_db, monkeypatch) -> None:
    _, track = auth_db
    email = track(unique_email("missing"))

    called = False

    def fake_send_password_reset_email(email: str, reset_token: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.services.auth_service.send_password_reset_email",
        fake_send_password_reset_email,
    )

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/forgot-password",
            json={"email": email},
        )
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "If an account exists for this email, a password reset link has been sent."
    )
    assert called is False


def test_reset_password_succeeds_and_invalidates_old_password(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("reset"))
    old_password = "StrongPassword123"
    new_password = "NewStrongPassword456"

    register_user(email, password=old_password)

    user = db.query(User).filter(User.email == email).one()

    from app.core.security import create_password_reset_token

    token = create_password_reset_token(
        subject=user.id,
        password_hash=user.password_hash,
    )

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": new_password,
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Password has been reset successfully."

    old_login = login_user(email, password=old_password)
    new_login = login_user(email, password=new_password)

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_reset_password_token_cannot_be_reused(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("reuse"))
    register_user(email)

    user = db.query(User).filter(User.email == email).one()

    from app.core.security import create_password_reset_token

    token = create_password_reset_token(
        subject=user.id,
        password_hash=user.password_hash,
    )

    first = run_async(
        api_request(
            "POST",
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": "FirstNewPassword123",
            },
        )
    )

    second = run_async(
        api_request(
            "POST",
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": "SecondNewPassword123",
            },
        )
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "INVALID_PASSWORD_RESET_TOKEN"


def test_reset_password_rejects_access_token(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("wrong-token-type"))
    register_user(email)

    user = db.query(User).filter(User.email == email).one()
    access_token = create_access_token(user.id)

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/reset-password",
            json={
                "token": access_token,
                "new_password": "AnotherStrongPassword123",
            },
        )
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PASSWORD_RESET_TOKEN"

def test_registration_accepts_full_name(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("full-name"))

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPassword123",
                "full_name": "Muhammad Hamdoon",
            },
        )
    )

    assert response.status_code == 201
    assert response.json()["full_name"] == "Muhammad Hamdoon"

    user = db.query(User).filter(User.email == email).one()
    assert user.full_name == "Muhammad Hamdoon"


def test_current_user_returns_full_name(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email("me-name"))

    register_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPassword123",
                "full_name": "Muhammad Hamdoon",
            },
        )
    )
    assert register_response.status_code == 201

    token = login_user(email).json()["access_token"]

    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Muhammad Hamdoon"


def test_current_user_can_update_full_name(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("update-name"))
    register_user(email)

    token = login_user(email).json()["access_token"]

    response = run_async(
        api_request(
            "PATCH",
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"full_name": "Muhammad Hamdoon"},
        )
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Muhammad Hamdoon"

    db.expire_all()
    user = db.query(User).filter(User.email == email).one()
    assert user.full_name == "Muhammad Hamdoon"

def test_login_returns_refresh_token(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email("refresh-login"))
    register_user(email)

    response = login_user(email)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_expires_in"] == get_settings().refresh_token_expire_days * 24 * 60 * 60


def test_refresh_token_returns_new_tokens(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email("refresh"))
    register_user(email)

    login_response = login_user(email)
    refresh_token = login_response.json()["refresh_token"]

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_access_token_cannot_be_used_as_refresh_token(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email("access-as-refresh"))
    register_user(email)

    access_token = login_user(email).json()["access_token"]

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


def test_refresh_token_cannot_access_protected_endpoint(auth_db) -> None:
    _, track = auth_db
    email = track(unique_email("refresh-as-access"))
    register_user(email)

    refresh_token = login_user(email).json()["refresh_token"]

    response = run_async(
        api_request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_refresh_token_fails(auth_db) -> None:
    db, track = auth_db
    email = track(unique_email("expired-refresh"))
    register_user(email)

    user = db.query(User).filter(User.email == email).one()
    settings = get_settings()

    expired_refresh_token = jwt.encode(
        {
            "sub": str(user.id),
            "type": "refresh",
            "iat": datetime.now(UTC) - timedelta(days=8),
            "exp": datetime.now(UTC) - timedelta(days=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": expired_refresh_token},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_EXPIRED"