from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.auth import UserResponse


class UserDataExportResponse(BaseModel):
    schema_version: str = "1.0"
    exported_at: datetime
    user: UserResponse
    records: dict[str, list[dict[str, Any]]]
