from uuid import UUID

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.user import User


def promote_admin(token: str) -> None:
    """Explicit database-only promotion for tests that author the shared catalog."""
    with SessionLocal.begin() as db:
        user = db.get(User, UUID(decode_access_token(token)["sub"]))
        assert user is not None
        user.is_admin = True
