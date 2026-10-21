from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationListResponse, NotificationResponse, NotificationSyncResponse
from app.services.notification_service import list_notifications, mark_read, sync_notifications

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
def list_inbox(unread_only: bool = False, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_notifications(db, user, unread_only, limit, offset)


@router.post("/sync", response_model=NotificationSyncResponse)
def sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sync_notifications(db, user)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def read(notification_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mark_read(db, user, notification_id)
