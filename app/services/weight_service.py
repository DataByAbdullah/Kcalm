from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from app.models.weight_log import WeightLog
from app.models.user_profile import UserProfile
from app.schemas.tracking import WeightProgressResponse
from app.services.tracking_common import commit_tracking, tracking_transaction, validate_date_range, validate_record_date


def save_weight(db: Session, user, log_date, payload):
    validate_record_date(log_date)
    statement = insert(WeightLog).values(user_id=user.id, log_date=log_date, weight_kg=payload.weight_kg)
    with tracking_transaction(db):
        db.execute(statement.on_conflict_do_update(
            constraint="uq_weight_logs_user_date",
            set_={"weight_kg": payload.weight_kg, "updated_at": func.now()},
        ))
    return db.query(WeightLog).filter_by(user_id=user.id, log_date=log_date).populate_existing().one()


def weight_progress(db: Session, user) -> WeightProgressResponse:
    query = db.query(WeightLog).filter_by(user_id=user.id)
    first = query.order_by(WeightLog.log_date.asc()).first()
    latest = query.order_by(WeightLog.log_date.desc()).first()
    profile = db.query(UserProfile).filter_by(user_id=user.id).one_or_none()
    start = first.weight_kg if first else None
    current = latest.weight_kg if latest else None
    target = profile.target_weight_kg if profile else None
    percent = None
    remaining = None
    if start is not None and current is not None and target is not None:
        distance = target - start
        percent = (100.0 if current == target else 0.0) if distance == 0 else max(0.0, min(100.0, (current - start) / distance * 100))
        remaining = abs(target - current) if distance == 0 else max(0.0, (target - current) * (1 if distance > 0 else -1))
    return WeightProgressResponse(
        starting_weight_kg=start, current_weight_kg=current, target_weight_kg=target,
        change_kg=current - start if current is not None else None,
        remaining_kg=remaining,
        progress_percent=percent,
    )


def weight_history(db, user, start_date=None, end_date=None, limit=100, offset=0):
    validate_date_range(start_date, end_date)
    query = db.query(WeightLog).filter_by(user_id=user.id)
    if start_date:
        query = query.filter(WeightLog.log_date >= start_date)
    if end_date:
        query = query.filter(WeightLog.log_date <= end_date)
    return {"items": query.order_by(WeightLog.log_date.desc()).offset(offset).limit(limit).all(),
            "total": query.count(), "limit": limit, "offset": offset, "progress": weight_progress(db, user)}


def delete_weight(db, user, log_date):
    row = db.query(WeightLog).filter_by(user_id=user.id, log_date=log_date).one_or_none()
    if row is None:
        raise APIErrorException(404, "WEIGHT_LOG_NOT_FOUND", "Weight log not found.")
    db.delete(row)
    commit_tracking(db)
