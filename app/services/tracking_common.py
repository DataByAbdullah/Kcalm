from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import APIErrorException


def validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise APIErrorException(422, "INVALID_DATE_RANGE", "start_date must be on or before end_date.")


def validate_record_date(log_date: date) -> None:
    latest_allowed_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    if log_date > latest_allowed_date:
        raise APIErrorException(422, "FUTURE_LOG_DATE", "Tracking dates cannot be more than one calendar day ahead of the current UTC date.")


def commit_tracking(db) -> None:
    with tracking_transaction(db):
        pass


@contextmanager
def tracking_transaction(db):
    try:
        yield
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(500, "TRACKING_SAVE_FAILED", "Tracking data could not be saved.") from exc
    except Exception:
        db.rollback()
        raise
