import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import APIErrorException, unauthorized_error
from app.models.user import User


password_hasher = PasswordHasher()
bearer_scheme = HTTPBearer(auto_error=False)


class TokenExpiredError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def create_access_token(subject: str | UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def password_reset_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()


def create_password_reset_token(
    subject: str | UUID,
    password_hash: str,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        minutes=settings.password_reset_token_expire_minutes
    )

    payload = {
        "sub": str(subject),
        "type": "password_reset",
        "pwd": password_reset_fingerprint(password_hash),
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

def decode_password_reset_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc

    if payload.get("type") != "password_reset":
        raise InvalidTokenError

    return payload


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized_error(
            code="INVALID_TOKEN",
            message="Invalid or missing authentication token.",
        )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload.get("sub")))
    except TokenExpiredError as exc:
        raise unauthorized_error(
            code="TOKEN_EXPIRED",
            message="Authentication token has expired.",
        ) from exc
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise unauthorized_error(
            code="INVALID_TOKEN",
            message="Invalid or missing authentication token.",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized_error(
            code="INVALID_TOKEN",
            message="Invalid or missing authentication token.",
        )
    if not user.is_active:
        raise APIErrorException(
            status_code=status.HTTP_403_FORBIDDEN,
            code="USER_INACTIVE",
            message="This account is inactive.",
        )

    return user
