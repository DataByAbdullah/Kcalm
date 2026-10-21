from datetime import date, datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert

from app.core.exceptions import APIErrorException
from app.models.habit import Habit, HabitCompletion
from app.schemas.habit import HabitResponse
from app.services.tracking_common import commit_tracking, tracking_transaction, validate_date_range, validate_record_date


def owned_habit(db, user, habit_id):
    habit = db.query(Habit).filter_by(user_id=user.id, id=habit_id).one_or_none()
    if habit is None:
        raise APIErrorException(404, "HABIT_NOT_FOUND", "Habit not found.")
    return habit


def create_habit(db, user, payload):
    validate_record_date(payload.start_date)
    habit = Habit(user_id=user.id, **payload.model_dump())
    db.add(habit)
    commit_tracking(db)
    return habit


def update_habit(db, user, habit_id, payload):
    habit = owned_habit(db, user, habit_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(habit, key, value)
    commit_tracking(db)
    return habit


def delete_habit(db, user, habit_id):
    db.delete(owned_habit(db, user, habit_id))
    commit_tracking(db)


def set_completion(db, user, habit_id, log_date, completed):
    habit = owned_habit(db, user, habit_id)
    validate_record_date(log_date)
    if log_date < habit.start_date:
        raise APIErrorException(422, "HABIT_NOT_STARTED", "Completion cannot precede the habit start date.")
    if completed:
        if not habit.active:
            raise APIErrorException(409, "HABIT_INACTIVE", "Inactive habits cannot be completed.")
        with tracking_transaction(db):
            db.execute(insert(HabitCompletion).values(habit_id=habit.id, log_date=log_date)
                       .on_conflict_do_nothing(constraint="uq_habit_completions_habit_date"))
    else:
        with tracking_transaction(db):
            db.query(HabitCompletion).filter_by(habit_id=habit.id, log_date=log_date).delete()
    return {"date": log_date, "completed": completed}


def list_habits(db, user, log_date, limit, offset):
    query = db.query(Habit).filter_by(user_id=user.id)
    habits = query.order_by(Habit.created_at, Habit.id).offset(offset).limit(limit).all()
    completed_ids = {row.habit_id for row in db.query(HabitCompletion).filter(
        HabitCompletion.habit_id.in_([habit.id for habit in habits]), HabitCompletion.log_date == log_date).all()}
    items = [{**HabitResponse.model_validate(habit).model_dump(), "date": log_date,
              "completed": habit.id in completed_ids, "scheduled": habit.active and log_date >= habit.start_date}
             for habit in habits]
    return {"items": items, "total": query.count(), "limit": limit, "offset": offset}


def habit_history(db, user, habit_id, start_date, end_date):
    habit = owned_habit(db, user, habit_id)
    end_date = end_date or datetime.now(timezone.utc).date()
    start_date = start_date or date.fromordinal(max(date.min.toordinal(), end_date.toordinal() - 29))
    validate_date_range(start_date, end_date)
    if (end_date - start_date).days > 365:
        raise APIErrorException(422, "DATE_RANGE_TOO_LARGE", "History is limited to 366 days per request.")
    validate_record_date(end_date)
    completed_dates = {row.log_date for row in db.query(HabitCompletion).filter(
        HabitCompletion.habit_id == habit.id, HabitCompletion.log_date >= start_date,
        HabitCompletion.log_date <= end_date).all()}
    day = max(start_date, habit.start_date)
    items = []
    while day <= end_date:
        items.append({"date": day, "completed": day in completed_dates})
        day += timedelta(days=1)
    return {"habit_id": habit.id, "items": items}
