from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from uuid import UUID

from app.core.security import (
    InvalidTokenError,
    TokenExpiredError,
    decode_password_reset_token,
    hash_password,
    password_reset_fingerprint,
    verify_password,
)
from app.services.password_reset_dispatch import enqueue_password_reset
from app.models.user import User


def logout_user(db: Session, user: User) -> None:
    try:
        db.execute(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(500, "LOGOUT_FAILED", "Could not log out. Please try again.") from exc


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized_email = normalize_email(email)
    return db.query(User).filter(User.email == normalized_email).one_or_none()


def register_user(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
) -> User:
    normalized_email = normalize_email(email)

    existing_user = get_user_by_email(db, normalized_email)
    if existing_user is not None:
        raise APIErrorException(
            status_code=409,
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
        )

    user = User(
        email=normalized_email,
        full_name=full_name,
        password_hash=hash_password(password),
        is_active=True,
    )

    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise APIErrorException(
            status_code=409,
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
        ) from exc

    db.refresh(user)
    return user

def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise APIErrorException(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise APIErrorException(
            status_code=403,
            code="USER_INACTIVE",
            message="This account is inactive.",
        )

    return user

def request_password_reset(db: Session, email: str) -> None:
    # Persist the same kind of work for known, unknown and inactive addresses.
    # No provider or password-reset token work runs on the public response path.
    enqueue_password_reset(db, normalize_email(email))


def reset_password(db: Session, token: str, new_password: str) -> None:
    try:
        payload = decode_password_reset_token(token)
        user_id = UUID(str(payload.get("sub")))
        token_fingerprint = str(payload.get("pwd"))
    except TokenExpiredError as exc:
        raise APIErrorException(
            status_code=400,
            code="PASSWORD_RESET_TOKEN_EXPIRED",
            message="Password reset token has expired.",
        ) from exc
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise APIErrorException(
            status_code=400,
            code="INVALID_PASSWORD_RESET_TOKEN",
            message="Password reset token is invalid.",
        ) from exc

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise APIErrorException(
            status_code=400,
            code="INVALID_PASSWORD_RESET_TOKEN",
            message="Password reset token is invalid.",
        )

    current_fingerprint = password_reset_fingerprint(user.password_hash)

    if token_fingerprint != current_fingerprint:
        raise APIErrorException(
            status_code=400,
            code="INVALID_PASSWORD_RESET_TOKEN",
            message="Password reset token is invalid or has already been used.",
        )

    expected_hash = user.password_hash
    replacement_hash = hash_password(new_password)
    try:
        changed = db.execute(
            update(User).where(
                User.id == user_id, User.is_active.is_(True),
                User.password_hash == expected_hash,
            ).values(
                password_hash=replacement_hash,
                token_version=User.token_version + 1,
            ).returning(User.id).execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if changed is None:
            db.rollback()
            raise APIErrorException(400, "INVALID_PASSWORD_RESET_TOKEN",
                                    "Password reset token is invalid or has already been used.")
        db.commit()
        db.expire(user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(500, "PASSWORD_CHANGE_FAILED", "Password could not be updated.") from exc


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise APIErrorException(400, "CURRENT_PASSWORD_INCORRECT", "Current password is incorrect.")
    if verify_password(new_password, user.password_hash):
        raise APIErrorException(422, "PASSWORD_UNCHANGED", "New password must differ from the current password.")
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(500, "PASSWORD_CHANGE_FAILED", "Password could not be updated.") from exc
