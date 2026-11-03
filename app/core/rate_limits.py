"""Fixed windows shared by all API workers through PostgreSQL.

Each identity/scope has one reusable bucket. Counts include failed requests.
Only HMAC digests are persisted; forwarded headers are not trusted here.
"""
from datetime import timedelta
import hashlib
import hmac
from typing import Literal

from fastapi import Depends, Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.exceptions import APIErrorException
from app.core.security import get_current_user, require_admin
from app.models.rate_limit import RateLimitBucket
from app.models.user import User


Scope = Literal["register", "login", "forgot_password", "ai", "usda_import"]


def consume_rate_limit(scope: Scope, identity: str, settings: Settings) -> None:
    limit = getattr(settings, f"rate_limit_{scope}_requests")
    window = getattr(settings, f"rate_limit_{scope}_window_seconds")
    key_hash = hmac.new(
        settings.jwt_secret.encode(), f"{scope}:{identity}".encode(), hashlib.sha256
    ).hexdigest()
    now = func.statement_timestamp()
    expires_at = now + timedelta(seconds=window)
    expired = RateLimitBucket.expires_at <= now
    statement = insert(RateLimitBucket).values(
        key_hash=key_hash, request_count=1, expires_at=expires_at
    ).on_conflict_do_update(
        index_elements=[RateLimitBucket.key_hash],
        set_={
            "request_count": case((expired, 1), else_=RateLimitBucket.request_count + 1),
            "expires_at": case((expired, expires_at), else_=RateLimitBucket.expires_at),
        },
        where=or_(expired, RateLimitBucket.request_count < limit),
    ).returning(RateLimitBucket.request_count)
    retry_after = None
    try:
        # Separate transaction: failed credentials or downstream rollbacks must
        # still consume quota, without committing any endpoint's business data.
        with SessionLocal.begin() as db:
            if db.execute(statement).scalar_one_or_none() is None:
                retry_after = db.scalar(select(
                    func.greatest(1, func.ceil(func.extract(
                        "epoch", RateLimitBucket.expires_at - func.clock_timestamp()
                    )))
                ).where(RateLimitBucket.key_hash == key_hash))
    except SQLAlchemyError as exc:
        raise APIErrorException(
            503, "RATE_LIMIT_UNAVAILABLE", "Request limiting is temporarily unavailable."
        ) from exc
    if retry_after is not None:
        raise APIErrorException(
            429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please try again later.",
            headers={"Retry-After": str(int(retry_after))},
        )


def client_rate_limit(scope: Scope):
    def dependency(request: Request, settings: Settings = Depends(get_settings)) -> None:
        identity = request.client.host if request.client else "unknown"
        consume_rate_limit(scope, identity, settings)
    return dependency


def rate_limit_ai(
    user: User = Depends(get_current_user), settings: Settings = Depends(get_settings),
) -> User:
    consume_rate_limit("ai", str(user.id), settings)
    return user


def rate_limit_usda_import(
    user: User = Depends(require_admin), settings: Settings = Depends(get_settings),
) -> User:
    consume_rate_limit("usda_import", str(user.id), settings)
    return user
