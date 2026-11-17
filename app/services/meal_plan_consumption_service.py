"""Coordinate plan mutations without treating archived consumption as disposable."""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, object_session

from app.core.enums import MealLogStatus
from app.core.exceptions import APIErrorException
from app.models.meal_log import MealLog
from app.models.user import User


LOCK_WAIT_MILLISECONDS = 2000


def planning_inputs_changed_error() -> APIErrorException:
    return APIErrorException(
        409, "MEAL_PLAN_INPUTS_CHANGED",
        "Planning inputs changed while the meal plan was being prepared. Please retry.",
        details={"retryable": True}, headers={"Retry-After": "1"},
    )


def release_planning_reads(db: Session, user: User) -> None:
    """Release the API boundary's authentication read before opening a snapshot.

    Endpoint handlers call this before any mutation. Detaching the authenticated
    user preserves its loaded ID without opening another connection after rollback.
    Service callers' transactions are never implicitly released by the planner.
    """
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("The planning API boundary must contain only reads.")
    if object_session(user) is db:
        db.expunge(user)
    db.rollback()


@contextmanager
def planning_snapshot(db: Session) -> Iterator[Session]:
    """Read consistent planning inputs without holding a user's write lock.

    This separate, read-only transaction never commits or rolls back its caller's
    transaction. Writers must revalidate its results under the user lock.
    """
    with Session(bind=db.get_bind().engine, autoflush=False, expire_on_commit=False) as snapshot:
        snapshot.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        snapshot.execute(text("SET TRANSACTION READ ONLY"))
        yield snapshot


def lock_user_meal_plans(db: Session, user_id: UUID) -> None:
    """Serialize this user's planning/logging writes until commit or rollback.

    Lock an existing row even when the day has no plan yet. Every cooperating
    writer takes this lock before reading eligibility; weekly calls can safely
    acquire it again in the same transaction without ordering multiple day locks.
    """
    previous_timeout = db.scalar(text("SELECT setting::int FROM pg_settings WHERE name = 'lock_timeout'"))
    timeout = min(previous_timeout or LOCK_WAIT_MILLISECONDS, LOCK_WAIT_MILLISECONDS)
    try:
        db.execute(select(func.set_config("lock_timeout", f"{timeout}ms", True)))
        found = db.execute(select(User.id).where(User.id == user_id).with_for_update()).scalar_one_or_none()
        db.execute(select(func.set_config("lock_timeout", f"{previous_timeout}ms", True)))
    except DBAPIError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "40P01", "40001"}:
            raise APIErrorException(
                503, "MEAL_PLAN_BUSY", "Another update is in progress. Please retry.",
                details={"retryable": True}, headers={"Retry-After": "1"},
            ) from exc
        raise
    if found is None:
        db.rollback()
        raise APIErrorException(401, "INVALID_TOKEN", "The user no longer exists.")


def active_consumption_dates(user_id: UUID) -> Select[tuple[date]]:
    return select(MealLog.log_date).where(
        MealLog.user_id == user_id,
        MealLog.status == MealLogStatus.ACTIVE.value,
    ).distinct()


def ensure_dates_have_no_consumption(
    db: Session, user_id: UUID, start_date: date, end_date: date,
    *, details: dict | None = None,
) -> None:
    """Call under the user lock; plan status never invalidates consumption."""
    dates = db.scalars(active_consumption_dates(user_id).where(
        MealLog.log_date.between(start_date, end_date),
    ).order_by(MealLog.log_date)).all()
    if dates:
        raise APIErrorException(
            409, "MEAL_PLAN_CONSUMPTION_EXISTS",
            "Plans with logged consumption cannot be archived or replaced. Keep the existing plan and change unlogged meals.",
            details={"conflict_dates": [day.isoformat() for day in dates], "retryable": False, **(details or {})},
        )


def ensure_item_has_no_consumption(db: Session, item_id: UUID) -> None:
    if db.scalar(select(MealLog.id).where(
        MealLog.meal_plan_item_id == item_id,
        MealLog.status == MealLogStatus.ACTIVE.value,
    ).limit(1)) is not None:
        raise APIErrorException(
            409, "MEAL_PLAN_ITEM_ALREADY_LOGGED",
            "Logged meals cannot be swapped. Only unlogged meals can be changed.",
            details={"meal_plan_item_id": str(item_id)},
        )
