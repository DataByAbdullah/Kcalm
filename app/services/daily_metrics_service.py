from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import APIErrorException
from app.models.daily_metrics import DailyMetrics
from app.services.tracking_common import (
    commit_tracking, tracking_transaction, validate_date_range, validate_record_date,
)


def save_daily_metrics(db, user, log_date, payload):
    validate_record_date(log_date)
    values = payload.model_dump()
    statement = insert(DailyMetrics).values(user_id=user.id, log_date=log_date, **values)
    with tracking_transaction(db):
        db.execute(statement.on_conflict_do_update(
            constraint="uq_daily_metrics_user_date",
            set_={**values, "updated_at": func.now()},
        ))
    return get_daily_metrics(db, user, log_date)


def get_daily_metrics(db, user, log_date):
    row = db.query(DailyMetrics).filter_by(
        user_id=user.id, log_date=log_date
    ).populate_existing().one_or_none()
    if row is None:
        raise APIErrorException(404, "DAILY_METRICS_NOT_FOUND", "Daily metrics not found.")
    return row


def daily_metrics_history(db, user, start_date=None, end_date=None, limit=100, offset=0):
    validate_date_range(start_date, end_date)
    query = db.query(DailyMetrics).filter_by(user_id=user.id)
    if start_date:
        query = query.filter(DailyMetrics.log_date >= start_date)
    if end_date:
        query = query.filter(DailyMetrics.log_date <= end_date)
    return {"items": query.order_by(DailyMetrics.log_date.desc()).offset(offset).limit(limit).all(),
            "total": query.count(), "limit": limit, "offset": offset}


def delete_daily_metrics(db, user, log_date):
    db.delete(get_daily_metrics(db, user, log_date))
    commit_tracking(db)
