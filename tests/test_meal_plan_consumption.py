from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier, Event
from time import monotonic
from uuid import UUID

import pytest
from ortools.sat.python import cp_model
from sqlalchemy import event, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.database import engine, get_db
from app.main import app
from app.core.exceptions import APIErrorException
from app.models.meal_log import MealLog, MealLogNutrientSnapshot
from app.models.meal_plan import MealPlan, MealPlanItem, WeeklyMealPlan
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.meal_log import MealLogRequest
from app.schemas.meal_plan import MealPlanCreateRequest
from app.schemas.user_profile import UserProfileUpdateRequest
from app.services.meal_log_service import log_meal_plan_item
from app.services.meal_plan_service import (
    archive_meal_plan,
    create_daily_meal_plan,
    get_meal_plan_detail,
)
from app.services.user_profile_service import update_profile
from app.services import meal_plan_consumption_service, meal_plan_service, meal_swap_service, weekly_plan_service
from app.schemas.meal_plan import MealSwapRequest
from app.schemas.weekly_plan import WeeklyMealPlanCreateRequest
from tests.test_auth import auth_db
from tests.test_meal_plan_persistence import create_profile, register_and_login, unique_email
from tests.test_profile_plan_invalidation import freeze_invalidation_time
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


DAY = date(2026, 11, 7)


@pytest.fixture
def consumption_user(auth_db, seeded_schedule_catalog, freeze_invalidation_time, monkeypatch):
    # Exercise real feasibility solving and its supported fallback, without
    # spending the optimization budget in every persistence/concurrency test.
    original_solve = cp_model.CpSolver.Solve

    def feasibility_only(solver, model, *args, **kwargs):
        if model.HasObjective():
            return cp_model.UNKNOWN
        return original_solve(solver, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", feasibility_only)
    freeze_invalidation_time(datetime(2026, 11, 7, 12, tzinfo=UTC))
    db, track = auth_db
    email = track(unique_email("consumption"))
    token = register_and_login(email)
    create_profile(
        token, meals_per_day=4, timezone="UTC",
        equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"],
    )
    return db, token, db.query(User).filter(User.email == email).one().id


def make_plan(token, day=DAY):
    response = request("POST", "/meal-plans", token, {"plan_date": day.isoformat()})
    assert response.status_code == 201, response.text
    return response.json()


def log(token, plan, index=0, body=None):
    response = request(
        "POST", f"/meal-plans/{plan['meal_plan_id']}/items/{plan['meals'][index]['id']}/log",
        token, body or {"type": "ate_as_planned"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def intake(token, day=DAY):
    response = request("GET", f"/nutrition/intake?from={day}&to={day}", token)
    assert response.status_code == 200, response.text
    return response.json()[0]


def archive(token, plan):
    response = request("DELETE", f"/meal-plans/{plan['meal_plan_id']}", token)
    assert response.status_code == 204, response.text


def legacy_archive(db, plan):
    """Reproduce pre-guard archived history only in the test database."""
    stored = db.get(MealPlan, UUID(plan["meal_plan_id"]))
    stored.status = "archived"
    db.commit()


def assert_consumption_conflict(response, day=DAY):
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MEAL_PLAN_CONSUMPTION_EXISTS"
    assert response.json()["error"]["details"]["conflict_dates"] == [day.isoformat()]


def seed_legacy_log(db, user_id, plan, index=0, calories=None):
    """Construct historical state only in the isolated regression database."""
    item = db.get(MealPlanItem, UUID(plan["meals"][index]["id"]))
    entry = MealLog(
        user_id=user_id, meal_plan_id=item.meal_plan_id, meal_plan_item_id=item.id,
        log_date=date.fromisoformat(plan["plan_date"]), log_type="ate_as_planned", status="active",
    )
    entry.nutrients = [
        MealLogNutrientSnapshot(
            nutrient_code=n.nutrient_code, nutrient_name=n.nutrient_name, unit=n.unit,
            amount=calories if n.nutrient_code == "calories" and calories is not None else n.amount,
        )
        for n in item.nutrients
    ]
    db.add(entry)


@pytest.mark.parametrize("logged_count", [1, 4])
def test_consumption_then_archive_blocks_recreation_without_losing_intake(consumption_user, logged_count):
    db, token, user_id = consumption_user
    plan = make_plan(token)
    entries = [log(token, plan, index) for index in range(logged_count)]
    before = intake(token)
    assert_consumption_conflict(request("DELETE", f"/meal-plans/{plan['meal_plan_id']}", token))
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan
    legacy_archive(db, plan)
    for _ in range(3):
        assert_consumption_conflict(request("POST", "/meal-plans", token, {"plan_date": str(DAY)}))
    assert intake(token) == before
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json() == entries
    assert db.query(MealLog).filter(MealLog.user_id == user_id).count() == logged_count
    assert db.query(MealPlan).filter(MealPlan.user_id == user_id).count() == 1


def test_same_item_logging_is_idempotent_and_corrections_replace_snapshot(consumption_user):
    db, token, user_id = consumption_user
    plan = make_plan(token)
    first = log(token, plan)
    assert log(token, plan)["meal_log_id"] == first["meal_log_id"]
    correction = log(token, plan, body={
        "type": "corrected", "source_type": "recipe",
        "recipe_id": plan["meals"][0]["recipe_id"], "servings": 0.5,
    })
    assert correction["meal_log_id"] == first["meal_log_id"]
    calories = next(n["amount"] for n in correction["nutrients"] if n["code"] == "calories")
    assert intake(token)["calories"] == pytest.approx(calories)
    assert db.query(MealLog).filter(MealLog.user_id == user_id).count() == 1


def test_explicitly_resetting_all_logs_allows_replacement(consumption_user):
    _, token, _ = consumption_user
    plan = make_plan(token)
    log(token, plan)
    response = request("DELETE", f"/meal-plans/{plan['meal_plan_id']}/items/{plan['meals'][0]['id']}/log", token)
    assert response.status_code == 204, response.text
    archive(token, plan)
    assert make_plan(token)["meal_plan_id"] != plan["meal_plan_id"]
    assert intake(token)["calories"] == 0


@pytest.mark.parametrize("changes", [
    {"meals_per_day": 3}, {"weight_kg": 90}, {"equipment": ["stovetop"]}, {"timezone": "Asia/Karachi"},
])
def test_profile_invalidation_retains_consumed_day_and_archives_unconsumed_dates(consumption_user, changes):
    _, token, _ = consumption_user
    plan = make_plan(token)
    future = make_plan(token, DAY + timedelta(days=1))
    entry = log(token, plan)
    before = intake(token)
    response = request("PATCH", "/users/profile", token, changes)
    assert response.status_code == 200, response.text
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan
    assert request("GET", f"/meal-plans/{future['meal_plan_id']}", token).json()["status"] == "archived"
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json() == [entry]
    assert intake(token) == before
    duplicate = request("POST", "/meal-plans", token, {"plan_date": str(DAY)})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PLAN_ALREADY_EXISTS"


def test_archived_consumption_also_protects_a_current_plan_on_the_same_date(consumption_user):
    db, token, user_id = consumption_user
    historical = make_plan(token)
    archive(token, historical)
    current = make_plan(token)
    seed_legacy_log(db, user_id, historical)
    db.commit()
    before = intake(token)
    assert request("PATCH", "/users/profile", token, {"meals_per_day": 3}).status_code == 200
    assert request("GET", f"/meal-plans/{current['meal_plan_id']}", token).json() == current
    assert intake(token) == before


def test_historical_four_plan_intake_remains_exactly_counted(consumption_user):
    db, token, user_id = consumption_user
    plans = []
    for _ in range(4):
        plan = make_plan(token)
        archive(token, plan)
        plans.append(plan)
    for plan in plans:
        for index in range(4):
            seed_legacy_log(db, user_id, plan, index, calories=620.22)
    db.commit()
    before = intake(token)
    assert before["calories"] == pytest.approx(9923.52)
    assert_consumption_conflict(request("POST", "/meal-plans", token, {"plan_date": str(DAY)}))
    assert request("PATCH", "/users/profile", token, {"meals_per_day": 3}).status_code == 200
    assert intake(token) == before
    assert db.query(MealLog).filter(MealLog.user_id == user_id).count() == 16


@pytest.mark.parametrize("day_offset", [0, 3, 6])
def test_weekly_creation_preflights_all_consumed_dates_without_partial_writes(consumption_user, day_offset):
    db, token, user_id = consumption_user
    day = DAY + timedelta(days=day_offset)
    plan = make_plan(token, day)
    log(token, plan)
    legacy_archive(db, plan)
    assert_consumption_conflict(request("POST", "/weekly-meal-plans", token, {"start_date": str(DAY)}), day)
    assert db.query(WeeklyMealPlan).filter(WeeklyMealPlan.user_id == user_id).count() == 0
    assert db.query(MealPlan).filter(MealPlan.user_id == user_id).count() == 1


@pytest.mark.parametrize("weekly", [False, True])
def test_unconsumed_dates_still_allow_archive_and_recreation(consumption_user, weekly):
    _, token, _ = consumption_user
    plan = make_plan(token)
    archive(token, plan)
    response = request("POST", "/weekly-meal-plans" if weekly else "/meal-plans", token,
                       {"start_date" if weekly else "plan_date": str(DAY)})
    assert response.status_code == 201, response.text
    assert intake(token)["calories"] == 0


def test_explicit_weekly_archive_preserves_consumption_and_active_members(consumption_user):
    _, token, _ = consumption_user
    response = request("POST", "/weekly-meal-plans", token, {"start_date": str(DAY)})
    assert response.status_code == 201, response.text
    week = response.json()
    plan = week["daily_plans"][0]
    entry = log(token, plan)
    before = intake(token)
    assert_consumption_conflict(request("DELETE", f"/weekly-meal-plans/{week['weekly_plan_id']}", token))
    assert request("GET", f"/weekly-meal-plans/{week['weekly_plan_id']}", token).json() == week
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json() == [entry]
    assert intake(token) == before
    # Archiving an unconsumed member must not leave a hole in the protected week.
    assert_consumption_conflict(request("DELETE", f"/meal-plans/{week['daily_plans'][1]['meal_plan_id']}", token))
    log(token, plan, 1)


def test_profile_invalidation_retains_consumed_week_and_grocery_functionality(consumption_user):
    _, token, _ = consumption_user
    response = request("POST", "/weekly-meal-plans", token, {"start_date": str(DAY)})
    assert response.status_code == 201, response.text
    week = response.json()
    plan = week["daily_plans"][0]
    entry = log(token, plan)
    before = intake(token)
    assert request("PATCH", "/users/profile", token, {"meals_per_day": 3}).status_code == 200
    week_path = f"/weekly-meal-plans/{week['weekly_plan_id']}"
    assert request("GET", week_path, token).json() == week
    listed = request("GET", "/weekly-meal-plans", token).json()
    assert week['weekly_plan_id'] in {w['weekly_plan_id'] for w in listed['items']}
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json() == [entry]
    assert_consumption_conflict(request("DELETE", week_path, token))
    assert intake(token) == before
    unconsumed = week['daily_plans'][1]
    swapped = request("POST", f"/meal-plans/{unconsumed['meal_plan_id']}/items/{unconsumed['meals'][0]['id']}/swap", token, {})
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()['meal_plan_id'] == unconsumed['meal_plan_id']
    grocery = request("POST", week_path + "/grocery-list", token, {})
    assert grocery.status_code == 201, grocery.text
    regenerated = request("POST", f"/grocery-lists/{grocery.json()['grocery_list_id']}/regenerate", token, {})
    assert regenerated.status_code == 200, regenerated.text
    assert intake(token) == before


def test_partial_consumption_allows_only_unlogged_swaps_in_place(consumption_user):
    db, token, user_id = consumption_user
    plan = make_plan(token)
    entry = log(token, plan)
    prefix = f"/meal-plans/{plan['meal_plan_id']}"
    blocked = request("POST", f"{prefix}/items/{plan['meals'][0]['id']}/swap", token, {})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "MEAL_PLAN_ITEM_ALREADY_LOGGED"
    swapped = request("POST", f"{prefix}/items/{plan['meals'][1]['id']}/swap", token, {})
    assert swapped.status_code == 200, swapped.text
    changed = swapped.json()
    assert changed["meal_plan_id"] == plan["meal_plan_id"]
    assert [m["id"] for m in changed["meals"]] == [m["id"] for m in plan["meals"]]
    assert changed["meals"][0] == plan["meals"][0]
    assert changed["meals"][1]["recipe_id"] != plan["meals"][1]["recipe_id"]
    assert request("GET", f"{prefix}/logs", token).json() == [entry]
    second = log(token, changed, 1)
    calories = sum(n["amount"] for e in (entry, second) for n in e["nutrients"] if n["code"] == "calories")
    assert intake(token)["calories"] == pytest.approx(calories)
    assert db.query(MealLog).filter(MealLog.user_id == user_id).count() == 2


@pytest.mark.parametrize("source", ["recipe", "snack"])
def test_genuine_repeated_food_consumption_counts_twice(consumption_user, source):
    db, token, _ = consumption_user
    plan = make_plan(token)
    if source == "recipe":
        body = {"type": "corrected", "source_type": "recipe", "recipe_id": plan["meals"][0]["recipe_id"], "servings": 1}
        first = log(token, plan, 0, body)
        once = intake(token)["calories"]
        second = log(token, plan, 1, body)
        assert first["meal_log_id"] != second["meal_log_id"]
    else:
        body = {"log_date": str(DAY), "name": "Repeated snack", "calories": 123,
                "protein_g": 3, "carbs_g": 15, "fat_g": 6}
        first = request("POST", "/nutrition/snacks", token, body)
        assert first.status_code == 201, first.text
        once = intake(token)["calories"]
        second = request("POST", "/nutrition/snacks", token, body)
        assert second.status_code == 201, second.text
        assert first.json()["id"] != second.json()["id"]
    if source == "recipe":
        legacy_archive(db, plan)
    else:
        archive(token, plan)
    assert intake(token)["calories"] == pytest.approx(2 * once)
    if source == "snack":
        make_plan(token)  # Standalone food logs do not duplicate plan item identities.


def test_consumption_guard_is_scoped_to_user_and_date(consumption_user, auth_db):
    db, token, _ = consumption_user
    plan = make_plan(token)
    log(token, plan)
    legacy_archive(db, plan)
    make_plan(token, DAY + timedelta(days=1))
    _, track = auth_db
    other = register_and_login(track(unique_email("other-consumer")))
    create_profile(other, equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    make_plan(other)
    assert intake(other)["calories"] == 0


@pytest.mark.parametrize("first_operation,second_operation", [
    ("log", "archive"), ("archive", "log"), ("log", "profile"), ("profile", "log"), ("log", "log"),
])
def test_concurrent_logging_and_replacement_serialize_with_fresh_plan_state(
    consumption_user, first_operation, second_operation,
):
    db, token, user_id = consumption_user
    plan = make_plan(token)
    plan_id, item_id = UUID(plan["meal_plan_id"]), UUID(plan["meals"][0]["id"])
    first_at_commit, release_first, second_connected = Event(), Event(), Event()
    second_pid = []

    def perform(operation, first):
        with SessionLocal() as session:
            session.execute(text("SET LOCAL lock_timeout = '10s'"))
            user = session.get(User, user_id)
            # Cache state before waiting, as authentication/callers may do.
            cached = get_meal_plan_detail(session, user, plan_id)
            assert cached.status == "generated"
            if first:
                def pause_before_commit(_):
                    first_at_commit.set()
                    assert release_first.wait(10), "Timed out releasing first writer"

                event.listen(session, "before_commit", pause_before_commit, once=True)
            else:
                second_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                second_connected.set()
            try:
                if operation == "log":
                    entry = log_meal_plan_item(session, user, plan_id, item_id, MealLogRequest(type="ate_as_planned"))
                    return str(entry.id)
                if operation == "archive":
                    archive_meal_plan(session, user, plan_id)
                else:
                    update_profile(session, user, UserProfileUpdateRequest(meals_per_day=3))
                replacement = create_daily_meal_plan(session, user, MealPlanCreateRequest(plan_date=DAY))
                return str(replacement.id)
            except APIErrorException as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(perform, first_operation, True)
        try:
            assert first_at_commit.wait(10), "First writer never reached commit"
            second = executor.submit(perform, second_operation, False)
            assert second_connected.wait(10), "Second writer never connected"
            deadline = monotonic() + 5
            with SessionLocal() as observer:
                while monotonic() < deadline:
                    if observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": second_pid[0]}):
                        break
                    Event().wait(0.01)
                else:
                    pytest.fail("Second writer did not wait on the first writer's database lock")
        finally:
            release_first.set()
        first_result, second_result = first.result(timeout=15), second.result(timeout=15)

    db.expire_all()
    logs = db.query(MealLog).filter(MealLog.user_id == user_id).all()
    plans = db.query(MealPlan).filter(MealPlan.user_id == user_id).all()
    if first_operation == "log":
        assert len(logs) == 1
        assert first_result == str(logs[0].id)
        if second_operation == "log":
            assert second_result == first_result
        else:
            assert second_result == ("MEAL_PLAN_CONSUMPTION_EXISTS" if second_operation == "archive" else "PLAN_ALREADY_EXISTS")
        assert len(plans) == 1
        assert intake(token)["calories"] == pytest.approx(plan["meals"][0]["nutrition"]["calories"])
    else:
        assert second_result == "MEAL_PLAN_ARCHIVED"
        assert logs == []
        assert len(plans) == 2
        assert sum(p.status == "generated" for p in plans) == 1
        assert first_result != str(plan_id)
        assert intake(token)["calories"] == 0


def test_profile_archive_conflict_keeps_remaining_meals_accessible(consumption_user):
    _, token, _ = consumption_user
    plan = make_plan(token)
    first = log(token, plan)
    assert request("PATCH", "/users/profile", token, {"weight_kg": 90}).status_code == 200
    prefix = f"/meal-plans/{plan['meal_plan_id']}"
    assert_consumption_conflict(request("DELETE", prefix, token))
    assert request("GET", prefix, token).json() == plan
    second = log(token, plan, 1)
    swapped = request("POST", f"{prefix}/items/{plan['meals'][2]['id']}/swap", token, {})
    assert swapped.status_code == 200, swapped.text
    assert request("GET", prefix + "/logs", token).json() == [first, second]
    assert swapped.json()["meals"][:2] == plan["meals"][:2]
    expected = sum(n["amount"] for entry in (first, second) for n in entry["nutrients"] if n["code"] == "calories")
    assert intake(token)["calories"] == pytest.approx(expected)


@pytest.mark.parametrize("operation", ["daily", "weekly", "swap"])
def test_solving_releases_user_lock_and_rejects_changed_profile(consumption_user, monkeypatch, operation):
    _, token, user_id = consumption_user
    plan = make_plan(token) if operation == "swap" else None
    if plan:
        log(token, plan)  # Retain the day when the profile changes during solving.
    started, release = Event(), Event()
    service = meal_swap_service if operation == "swap" else meal_plan_service
    name = "solve_daily_plan" if operation == "swap" else "solve_daily_plan_preview"
    solve = getattr(service, name)

    def paused(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10)
        return solve(*args, **kwargs)

    monkeypatch.setattr(service, name, paused)

    def generate():
        with SessionLocal() as session:
            user = session.get(User, user_id)
            try:
                if operation == "daily":
                    create_daily_meal_plan(session, user, MealPlanCreateRequest(plan_date=DAY))
                elif operation == "weekly":
                    weekly_plan_service.create_weekly_plan(session, user, WeeklyMealPlanCreateRequest(start_date=DAY))
                else:
                    meal_swap_service.swap_meal_plan_item(
                        session, user, UUID(plan["meal_plan_id"]), UUID(plan["meals"][1]["id"]), MealSwapRequest(),
                    )
            except APIErrorException as exc:
                return exc.code
            pytest.fail("Stale planning result was saved")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(generate)
        try:
            assert started.wait(10)
            with SessionLocal() as observer:
                # Acquiring the real lock must succeed while the solver is paused.
                meal_plan_consumption_service.lock_user_meal_plans(observer, user_id)
                observer.rollback()
            changed = request("PATCH", "/users/profile", token, {"weight_kg": 90})
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        assert future.result(timeout=20) == "MEAL_PLAN_INPUTS_CHANGED"


def test_logging_continues_while_a_different_week_is_being_solved(consumption_user, monkeypatch):
    _, token, user_id = consumption_user
    plan = make_plan(token)
    log(token, plan)
    started, release = Event(), Event()
    solve = meal_plan_service.solve_daily_plan_preview

    def paused(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10)
        return solve(*args, **kwargs)

    monkeypatch.setattr(meal_plan_service, "solve_daily_plan_preview", paused)

    def generate():
        with SessionLocal() as session:
            user = session.get(User, user_id)
            week = weekly_plan_service.create_weekly_plan(
                session, user, WeeklyMealPlanCreateRequest(start_date=DAY + timedelta(days=7)),
            )
            return week.id

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(generate)
        try:
            assert started.wait(10)
            second = log(token, plan, 1)
        finally:
            release.set()
        assert future.result(timeout=20)
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json()[1] == second


def test_logging_wins_over_a_prepared_swap(consumption_user, monkeypatch):
    _, token, user_id = consumption_user
    plan = make_plan(token)
    log(token, plan)
    started, release = Event(), Event()
    solve = meal_swap_service.solve_daily_plan

    def paused(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return solve(*args, **kwargs)

    monkeypatch.setattr(meal_swap_service, "solve_daily_plan", paused)

    def swap():
        with SessionLocal() as session:
            try:
                meal_swap_service.swap_meal_plan_item(
                    session, session.get(User, user_id), UUID(plan["meal_plan_id"]),
                    UUID(plan["meals"][1]["id"]), MealSwapRequest(),
                )
            except APIErrorException as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(swap)
        try:
            assert started.wait(10)
            entry = log(token, plan, 1)
        finally:
            release.set()
        assert future.result(timeout=15) == "MEAL_PLAN_ITEM_ALREADY_LOGGED"
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}", token).json() == plan
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json()[1] == entry


def test_lock_contention_returns_retryable_api_error_and_rolls_back(consumption_user, monkeypatch):
    _, token, user_id = consumption_user
    plan = make_plan(token)
    monkeypatch.setattr(meal_plan_consumption_service, "LOCK_WAIT_MILLISECONDS", 100)
    with SessionLocal() as holder:
        meal_plan_consumption_service.lock_user_meal_plans(holder, user_id)
        response = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{plan['meals'][0]['id']}/log", token,
                           {"type": "ate_as_planned"})
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "MEAL_PLAN_BUSY"
        assert response.json()["error"]["details"]["retryable"] is True
        assert response.headers["Retry-After"] == "1"
        with SessionLocal() as waiter:
            with pytest.raises(APIErrorException) as caught:
                meal_plan_consumption_service.lock_user_meal_plans(waiter, user_id)
            assert caught.value.code == "MEAL_PLAN_BUSY"
            assert not waiter.in_transaction()
        holder.rollback()
    assert request("GET", f"/meal-plans/{plan['meal_plan_id']}/logs", token).json() == []
    log(token, plan)
    with SessionLocal() as session:
        session.execute(text("SET LOCAL lock_timeout = '50ms'"))
        meal_plan_consumption_service.lock_user_meal_plans(session, user_id)
        assert session.scalar(text("SHOW lock_timeout")) == "50ms"


@pytest.mark.parametrize("operations", [("daily", "daily"), ("daily", "weekly"), ("weekly", "weekly")])
def test_concurrent_creations_recheck_eligibility_before_atomic_save(consumption_user, monkeypatch, operations):
    db, _, user_id = consumption_user
    barrier = Barrier(2)
    prepare = meal_plan_service.prepare_daily_meal_plan

    def synchronized(snapshot, user, payload, **kwargs):
        result = prepare(snapshot, user, payload, **kwargs)
        if payload.plan_date == DAY:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(meal_plan_service, "prepare_daily_meal_plan", synchronized)
    monkeypatch.setattr(weekly_plan_service, "prepare_daily_meal_plan", synchronized)

    def generate(operation):
        with SessionLocal() as session:
            user = session.get(User, user_id)
            try:
                if operation == "daily":
                    create_daily_meal_plan(session, user, MealPlanCreateRequest(plan_date=DAY))
                else:
                    weekly_plan_service.create_weekly_plan(session, user, WeeklyMealPlanCreateRequest(start_date=DAY))
                return "created"
            except APIErrorException as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(generate, operation) for operation in operations]
        results = [future.result(timeout=25) for future in futures]
    assert results.count("created") == 1
    assert next(result for result in results if result != "created") in {
        "PLAN_ALREADY_EXISTS", "WEEKLY_PLAN_ALREADY_EXISTS", "DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK",
    }
    plans = db.query(MealPlan).filter(MealPlan.user_id == user_id).all()
    assert len(plans) in {1, 7}
    assert len({plan.plan_date for plan in plans}) == len(plans)
    weeks = db.query(WeeklyMealPlan).filter(WeeklyMealPlan.user_id == user_id).all()
    assert len(weeks) == (1 if len(plans) == 7 else 0)


def test_weekly_persistence_failure_rolls_back_every_day(consumption_user, monkeypatch):
    db, _, user_id = consumption_user
    persist = weekly_plan_service.persist_prepared_daily_plan

    def fail_on_fifth_day(session, user, prepared, **kwargs):
        plan = persist(session, user, prepared, **kwargs)
        if prepared.plan_date == DAY + timedelta(days=4):
            raise RuntimeError("forced persistence failure after five flushed days")
        return plan

    monkeypatch.setattr(weekly_plan_service, "persist_prepared_daily_plan", fail_on_fifth_day)
    with pytest.raises(RuntimeError, match="forced persistence failure"):
        weekly_plan_service.create_weekly_plan(
            db, db.get(User, user_id), WeeklyMealPlanCreateRequest(start_date=DAY),
        )
    assert db.query(MealPlan).filter(MealPlan.user_id == user_id).count() == 0
    assert db.query(WeeklyMealPlan).filter(WeeklyMealPlan.user_id == user_id).count() == 0


def test_planning_api_works_with_one_database_connection(consumption_user):
    _, token, _ = consumption_user
    limited = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.5,
                            isolation_level="READ COMMITTED")

    def limited_db():
        with Session(limited, autoflush=False, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = limited_db
    try:
        plan = make_plan(token)
        response = request("POST", f"/meal-plans/{plan['meal_plan_id']}/items/{plan['meals'][0]['id']}/swap", token, {})
        assert response.status_code == 200, response.text
        response = request("POST", "/weekly-meal-plans", token, {"start_date": str(DAY + timedelta(days=7))})
        assert response.status_code == 201, response.text
        assert limited.pool.checkedout() == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        limited.dispose()


def test_swap_freezes_ingredients_with_nutrients_before_catalog_changes(consumption_user, monkeypatch):
    db, token, user_id = consumption_user
    plan = make_plan(token)
    target = plan["meals"][0]
    candidates = request("POST", "/recipes/candidates/preview", token, {"meal_type": target["meal_type"]})
    assert candidates.status_code == 200, candidates.text
    selected_ids = {meal["recipe_id"] for meal in plan["meals"]}
    candidate_id = next(c["recipe_id"] for c in candidates.json()["candidates"] if c["recipe_id"] not in selected_ids)
    recipe = db.get(Recipe, UUID(candidate_id))
    original = [(ingredient, float(ingredient.quantity_grams)) for ingredient in recipe.ingredients]
    quantities = {}
    for ingredient, quantity in original:
        quantities[ingredient.food_id] = quantities.get(ingredient.food_id, 0) + quantity
    started, release = Event(), Event()
    solve = meal_swap_service.solve_daily_plan

    def paused(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return solve(*args, **kwargs)

    monkeypatch.setattr(meal_swap_service, "solve_daily_plan", paused)

    def swap():
        with SessionLocal() as session:
            result = meal_swap_service.swap_meal_plan_item(
                session, session.get(User, user_id), UUID(plan["meal_plan_id"]), UUID(target["id"]),
                MealSwapRequest(recipe_id=UUID(candidate_id)),
            )
            item = next(item for item in result.items if item.id == UUID(target["id"]))
            return item.servings, {ingredient.food_id: ingredient.quantity_grams for ingredient in item.ingredient_snapshots}

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(swap)
            try:
                assert started.wait(10)
                for ingredient, quantity in original:
                    ingredient.quantity_grams = quantity * 2
                db.commit()
            finally:
                release.set()
            servings, saved = future.result(timeout=15)
        assert saved == pytest.approx({food_id: quantity * servings for food_id, quantity in quantities.items()})
    finally:
        for ingredient, quantity in original:
            ingredient.quantity_grams = quantity
        db.commit()
