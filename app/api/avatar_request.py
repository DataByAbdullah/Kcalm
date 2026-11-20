"""Avatar-only authenticated, bounded JSON request reading."""
import asyncio

from fastapi import Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.core.database import get_db
from app.core.rate_limits import rate_limit_avatar
from app.models.user import User
from app.schemas.avatar import AvatarUploadRequest
from app.services.avatar_service import avatar_too_large_error, invalid_avatar_error


# 409623 bytes for a maximal standard Data URL, plus more than 100 KiB of JSON
# overhead. Also bound escaped JSON strings and otherwise insignificant padding.
MAX_AVATAR_REQUEST_BYTES = 512 * 1024
AVATAR_BODY_TIMEOUT_SECONDS = 30


async def read_avatar_request(
    request: Request, _user: User = Depends(rate_limit_avatar),
    db: Session = Depends(get_db),
) -> AvatarUploadRequest:
    # No Body parameter is declared anywhere on this route. FastAPI must finish
    # authentication and the shared quota dependency before any body is received.
    # This route has only read authentication data in this session. Release that
    # transaction/connection before awaiting a slow client. The limiter committed
    # its own transaction; the ORM user remains attached for the later update.
    await run_in_threadpool(db.rollback)
    lengths = request.headers.getlist("content-length")
    declared_length = None
    if lengths:
        value = lengths[0].strip()
        if len(lengths) != 1 or not value or not value.isascii() or not value.isdecimal():
            raise invalid_avatar_error()
        normalized = value.lstrip("0") or "0"
        maximum = str(MAX_AVATAR_REQUEST_BYTES)
        if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
            raise avatar_too_large_error()
        declared_length = int(normalized)

    mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime != "application/json" and not (mime.startswith("application/") and mime.endswith("+json")):
        raise invalid_avatar_error()
    body = bytearray()
    try:
        async with asyncio.timeout(AVATAR_BODY_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                # Check before extending the buffer, regardless of Content-Length.
                if len(chunk) > MAX_AVATAR_REQUEST_BYTES - len(body):
                    raise avatar_too_large_error()
                body.extend(chunk)
    except (ClientDisconnect, TimeoutError):
        raise invalid_avatar_error() from None
    if declared_length is not None and declared_length != len(body):
        raise invalid_avatar_error()
    try:
        return AvatarUploadRequest.model_validate_json(body)
    except ValidationError:
        raise invalid_avatar_error() from None
