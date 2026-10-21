from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime

    @computed_field
    @property
    def read(self) -> bool:
        return self.read_at is not None


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationSyncResponse(BaseModel):
    created_count: int
