from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import APIErrorException
from app.models.notification import Notification
from app.services.achievement_service import get_achievements
from app.services.tracking_common import commit_tracking, tracking_transaction


def sync_notifications(db, user):
    created = 0
    with tracking_transaction(db):
        for achievement in get_achievements(db, user):
            if achievement.unlocked:
                statement = insert(Notification).values(user_id=user.id, event_key=achievement.code,
                    kind="achievement", title=achievement.name,
                    message=f"Recorded {achievement.current} {achievement.unit}; milestone: {achievement.target}.")
                result = db.execute(statement.on_conflict_do_nothing(constraint="uq_notifications_user_event").returning(Notification.id))
                created += int(result.scalar_one_or_none() is not None)
    return {"created_count": created}


def list_notifications(db, user, unread_only, limit, offset):
    query = db.query(Notification).filter_by(user_id=user.id)
    unread_count = query.filter(Notification.read_at.is_(None)).count()
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return {"items": query.order_by(Notification.created_at.desc(), Notification.id).offset(offset).limit(limit).all(),
            "total": query.count(), "unread_count": unread_count, "limit": limit, "offset": offset}


def mark_read(db, user, notification_id):
    notification = db.query(Notification).filter_by(user_id=user.id, id=notification_id).one_or_none()
    if notification is None:
        raise APIErrorException(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    notification.read_at = notification.read_at or datetime.now(timezone.utc)
    commit_tracking(db)
    return notification
