from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import APIErrorException
from app.models.step_log import StepLog
from app.services.tracking_common import commit_tracking, tracking_transaction, validate_date_range, validate_record_date


def save_steps(db, user, log_date, payload):
    validate_record_date(log_date)
    statement = insert(StepLog).values(user_id=user.id, log_date=log_date, steps=payload.steps)
    with tracking_transaction(db):
        db.execute(statement.on_conflict_do_update(
            constraint="uq_step_logs_user_date", set_={"steps": payload.steps, "updated_at": func.now()},
        ))
    return get_steps(db, user, log_date)


def get_steps(db, user, log_date):
    row = db.query(StepLog).filter_by(user_id=user.id, log_date=log_date).populate_existing().one_or_none()
    if row is None:
        raise APIErrorException(404, "STEP_LOG_NOT_FOUND", "Step log not found.")
    return row


def step_history(db, user, start_date=None, end_date=None, limit=100, offset=0):
    validate_date_range(start_date, end_date)
    query = db.query(StepLog).filter_by(user_id=user.id)
    if start_date:
        query = query.filter(StepLog.log_date >= start_date)
    if end_date:
        query = query.filter(StepLog.log_date <= end_date)
    return {"items": query.order_by(StepLog.log_date.desc()).offset(offset).limit(limit).all(),
            "total": query.count(), "limit": limit, "offset": offset}


def delete_steps(db, user, log_date):
    db.delete(get_steps(db, user, log_date))
    commit_tracking(db)
