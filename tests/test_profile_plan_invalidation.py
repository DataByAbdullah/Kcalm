from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from app.models.meal_plan import MealPlan, WeeklyMealPlan
from app.models.user import User
from app.services import meal_plan_invalidation_service, user_profile_service
from tests.test_auth import auth_db
from tests.test_meal_plan_persistence import create_profile, register_and_login, unique_email
from tests.test_scheduled_meal_plans import seeded_schedule_catalog
from tests.test_weight_logs import request


TODAY = date(2026, 11, 6)


@pytest.fixture
def freeze_invalidation_time(monkeypatch):
    def freeze(instant):
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        monkeypatch.setattr(meal_plan_invalidation_service, "datetime", FrozenDateTime)

    freeze(datetime(2026, 11, 6, 12, tzinfo=UTC))
    return freeze


@pytest.fixture
def scheduled_user(auth_db, seeded_schedule_catalog, freeze_invalidation_time):
    db, track = auth_db
    token = register_and_login(track(unique_email("plan-invalidation")))
    create_profile(token, meals_per_day=4, usual_wake_time="07:00", usual_sleep_time="23:00",
                   timezone="UTC", equipment=["stovetop", "oven", "blender", "air_fryer", "microwave", "slow_cooker"])
    return db, token


def generate_plan(token, plan_date=TODAY):
    response = request("POST", "/meal-plans", token, {"plan_date": plan_date.isoformat()})
    assert response.status_code == 201, response.text
    return response.json()


def get_plan(token, plan):
    response = request("GET", f"/meal-plans/{plan['meal_plan_id']}", token)
    assert response.status_code == 200, response.text
    return response.json()


def assert_archived_snapshot(db, token, original):
    stored = get_plan(token, original)
    assert stored["status"] == "archived"
    assert stored["meals"] == original["meals"]
    db.expire_all()
    assert db.get(MealPlan, UUID(original["meal_plan_id"])).status == "archived"


def test_meal_count_change_archives_today_and_allows_regeneration(scheduled_user):
    db, token = scheduled_user
    original = generate_plan(token)
    assert len(original["meals"]) == 4

    updated = request("PATCH", "/users/profile", token, {"meals_per_day": 3})

    assert updated.status_code == 200, updated.text
    assert updated.json()["meals_per_day"] == 3
    assert request("GET", "/users/profile", token).json() == updated.json()
    assert_archived_snapshot(db, token, original)
    listed = request("GET", f"/meal-plans?plan_date={TODAY}", token)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    regenerated = generate_plan(token)
    assert regenerated["meal_plan_id"] != original["meal_plan_id"]
    assert regenerated["status"] == "generated"
    assert [meal["meal_type"] for meal in regenerated["meals"]] == ["breakfast", "lunch", "dinner"]
    assert request("GET", f"/meal-plans?plan_date={TODAY}", token).json()["items"][0]["meal_plan_id"] == regenerated["meal_plan_id"]


def test_wake_change_archives_today_and_regeneration_uses_new_times(scheduled_user):
    db, token = scheduled_user
    original = generate_plan(token)
    assert original["meals"][0]["scheduled_time"] == "08:00:00"

    updated = request("PATCH", "/users/profile", token, {"usual_wake_time": "11:00"})

    assert updated.status_code == 200, updated.text
    assert updated.json()["usual_wake_time"] == "11:00:00"
    assert_archived_snapshot(db, token, original)
    regenerated = generate_plan(token)
    assert [meal["scheduled_time"] for meal in regenerated["meals"]] == [
        "12:00:00", "15:00:00", "18:00:00", "21:00:00",
    ]


@pytest.mark.parametrize("changes", [
    {"usual_sleep_time": "03:00"},
    {"timezone": "Asia/Karachi"},
])
def test_sleep_or_timezone_change_archives_today_and_future_but_preserves_yesterday(scheduled_user, changes):
    db, token = scheduled_user
    yesterday = generate_plan(token, TODAY - timedelta(days=1))
    today = generate_plan(token)
    future = generate_plan(token, TODAY + timedelta(days=4))

    response = request("PATCH", "/users/profile", token, changes)

    assert response.status_code == 200, response.text
    assert get_plan(token, yesterday) == yesterday
    assert_archived_snapshot(db, token, today)
    assert_archived_snapshot(db, token, future)


@pytest.mark.parametrize("same_values", [
    {"meals_per_day": 4},
    {"usual_wake_time": "07:00"},
    {"usual_sleep_time": "23:00:00"},
    {"timezone": "UTC"},
    {"meals_per_day": 4, "usual_wake_time": "07:00:00", "usual_sleep_time": "23:00", "timezone": "UTC"},
])
def test_unchanged_schedule_values_preserve_generated_plan(scheduled_user, same_values):
    _, token = scheduled_user
    original = generate_plan(token)

    response = request("PATCH", "/users/profile", token, same_values)

    assert response.status_code == 200, response.text
    assert get_plan(token, original) == original


def test_unrelated_profile_and_full_name_updates_preserve_generated_plan(scheduled_user):
    _, token = scheduled_user
    original = generate_plan(token)
    for endpoint, changes in (
        ("/users/profile", {"weight_kg": 80, "max_cooking_minutes": 45}),
        ("/users/me", {"full_name": "Updated Name"}),
    ):
        response = request("PATCH", endpoint, token, changes)
        assert response.status_code == 200, response.text
        assert get_plan(token, original) == original


def test_invalid_schedule_update_preserves_profile_and_plan(scheduled_user):
    _, token = scheduled_user
    original = generate_plan(token)
    profile = request("GET", "/users/profile", token).json()

    response = request("PATCH", "/users/profile", token, {"usual_wake_time": "23:00", "meals_per_day": 3})

    assert response.status_code == 422
    assert request("GET", "/users/profile", token).json() == profile
    assert get_plan(token, original) == original


@pytest.mark.parametrize("instant,updated_zone,local_today", [
    (datetime(2026, 11, 6, 23, 30, tzinfo=UTC), "Asia/Karachi", date(2026, 11, 7)),
    (datetime(2026, 11, 6, 1, 30, tzinfo=UTC), "America/Los_Angeles", date(2026, 11, 5)),
])
def test_invalidation_uses_updated_timezone_across_utc_date_boundary(
    scheduled_user, freeze_invalidation_time, instant, updated_zone, local_today,
):
    db, token = scheduled_user
    freeze_invalidation_time(instant)
    yesterday = generate_plan(token, local_today - timedelta(days=1))
    today = generate_plan(token, local_today)
    future = generate_plan(token, local_today + timedelta(days=1))

    response = request("PATCH", "/users/profile", token, {"timezone": updated_zone})

    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == updated_zone
    assert get_plan(token, yesterday) == yesterday
    assert_archived_snapshot(db, token, today)
    assert_archived_snapshot(db, token, future)


def test_overlapping_week_archives_without_changing_historical_children(scheduled_user):
    db, token = scheduled_user
    response = request("POST", "/weekly-meal-plans", token, {"start_date": (TODAY - timedelta(days=3)).isoformat()})
    assert response.status_code == 201, response.text
    original_week = response.json()
    # A generated, entirely historical week must also remain unchanged.
    historical_response = request("POST", "/weekly-meal-plans", token, {"start_date": (TODAY - timedelta(days=10)).isoformat()})
    assert historical_response.status_code == 201, historical_response.text
    historical_week = historical_response.json()
    assert request("PATCH", "/users/profile", token, {"meals_per_day": 4}).status_code == 200
    path = f"/weekly-meal-plans/{original_week['weekly_plan_id']}"
    assert request("GET", path, token).json() == original_week

    updated = request("PATCH", "/users/profile", token, {"meals_per_day": 3})

    assert updated.status_code == 200, updated.text
    db.expire_all()
    assert db.get(WeeklyMealPlan, UUID(original_week["weekly_plan_id"])).status == "archived"
    archived = request("GET", path, token)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    for original_day in original_week["daily_plans"]:
        if date.fromisoformat(original_day["plan_date"]) < TODAY:
            assert get_plan(token, original_day) == original_day
        else:
            assert_archived_snapshot(db, token, original_day)
        child = db.get(MealPlan, UUID(original_day["meal_plan_id"]))
        assert str(child.weekly_plan_id) == original_week["weekly_plan_id"]
    historical_path = f"/weekly-meal-plans/{historical_week['weekly_plan_id']}"
    assert request("GET", historical_path, token).json() == historical_week
    listed = request("GET", "/weekly-meal-plans", token)
    assert [week["weekly_plan_id"] for week in listed.json()["items"]] == [historical_week["weekly_plan_id"]]


def test_date_overlapping_week_archives_even_without_child_relationship(scheduled_user):
    db, token = scheduled_user
    today = generate_plan(token)
    user_id = db.get(MealPlan, UUID(today["meal_plan_id"])).user_id
    week = WeeklyMealPlan(user_id=user_id, start_date=TODAY - timedelta(days=1),
                          end_date=TODAY + timedelta(days=5), status="generated")
    db.add(week)
    db.commit()
    week_id = week.id

    response = request("PATCH", "/users/profile", token, {"usual_sleep_time": "22:00"})

    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(WeeklyMealPlan, week_id).status == "archived"
    assert_archived_snapshot(db, token, today)


def test_schedule_change_does_not_invalidate_another_users_plans(scheduled_user, auth_db):
    db, token = scheduled_user
    own_plan = generate_plan(token)
    _, track = auth_db
    other_token = register_and_login(track(unique_email("other-schedule")))
    create_profile(other_token)
    other_plan = generate_plan(other_token)
    other_user_id = db.get(MealPlan, UUID(other_plan["meal_plan_id"])).user_id
    other_week = WeeklyMealPlan(user_id=other_user_id, start_date=TODAY,
                                end_date=TODAY + timedelta(days=6), status="generated")
    db.add(other_week)
    db.commit()
    other_week_id = other_week.id

    response = request("PATCH", "/users/profile", token, {"meals_per_day": 3})

    assert response.status_code == 200, response.text
    assert_archived_snapshot(db, token, own_plan)
    assert get_plan(other_token, other_plan) == other_plan
    assert db.get(WeeklyMealPlan, other_week_id).status == "generated"


def test_invalidation_failure_rolls_back_profile_and_plan_changes(scheduled_user, monkeypatch):
    db, token = scheduled_user
    original = generate_plan(token)
    plan = db.get(MealPlan, UUID(original["meal_plan_id"]))
    user = db.get(User, plan.user_id)
    invalidate = user_profile_service.invalidate_future_meal_plans

    def fail_after_invalidation(*args, **kwargs):
        invalidate(*args, **kwargs)
        raise RuntimeError("Simulated transaction failure")

    monkeypatch.setattr(user_profile_service, "invalidate_future_meal_plans", fail_after_invalidation)
    with pytest.raises(RuntimeError, match="Simulated transaction failure"):
        request("PATCH", "/users/profile", token, {"meals_per_day": 3})

    db.expire_all()
    assert user.profile.meals_per_day == 4
    assert get_plan(token, original) == original
