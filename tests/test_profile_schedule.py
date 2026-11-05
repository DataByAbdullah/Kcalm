from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from tests.test_user_profile import (
    base_profile_payload, create_profile, get_profile, patch_profile, profile_db,
    register_and_login, unique_email,
)


@pytest.fixture
def schedule_user(profile_db):
    db, track = profile_db
    email = track(unique_email("schedule-profile"))
    token = register_and_login(email)
    return db, token, email


@pytest.mark.parametrize("count", [2, 5])
def test_profile_accepts_meal_count_boundaries(schedule_user, count):
    _, token, _ = schedule_user
    created = create_profile(token, {**base_profile_payload(), "meals_per_day": count})
    assert created.status_code == 201, created.text
    assert created.json()["meals_per_day"] == count
    other = 5 if count == 2 else 2
    assert patch_profile(token, {"meals_per_day": other}).json()["meals_per_day"] == other


@pytest.mark.parametrize("count", [1, 6])
def test_profile_rejects_out_of_range_meal_counts(schedule_user, count):
    _, token, _ = schedule_user
    rejected = create_profile(token, {**base_profile_payload(), "meals_per_day": count})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_PROFILE_DATA"
    assert create_profile(token).status_code == 201
    assert patch_profile(token, {"meals_per_day": count}).status_code == 422
    assert get_profile(token).json()["meals_per_day"] == 4


def test_profile_schedule_defaults_and_explicit_values_persist(schedule_user):
    db, token, email = schedule_user
    created = create_profile(token)
    assert created.status_code == 201
    assert created.json()["usual_wake_time"] == "07:00:00"
    assert created.json()["usual_sleep_time"] == "23:00:00"
    assert created.json()["timezone"] == "UTC"
    changed = patch_profile(token, {
        "usual_wake_time": "11:00", "usual_sleep_time": "03:00", "timezone": "Asia/Karachi",
    })
    assert changed.status_code == 200, changed.text
    assert get_profile(token).json() == changed.json()
    profile = db.query(User).filter_by(email=email).one().profile
    assert profile.usual_wake_time == time(11)
    assert profile.usual_sleep_time == time(3)
    assert profile.timezone == "Asia/Karachi"
    assert patch_profile(token, {"usual_wake_time": "10:30"}).status_code == 200
    assert get_profile(token).json()["usual_sleep_time"] == "03:00:00"


def test_profile_create_stores_frontend_schedule(schedule_user):
    db, token, email = schedule_user
    response = create_profile(token, {**base_profile_payload(),
        "usual_wake_time": "11:00", "usual_sleep_time": "03:00", "timezone": "Asia/Karachi",
    })
    assert response.status_code == 201, response.text
    profile = db.query(User).filter_by(email=email).one().profile
    assert profile.usual_wake_time == time(11)
    assert profile.usual_sleep_time == time(3)
    assert profile.timezone == response.json()["timezone"] == "Asia/Karachi"


@pytest.mark.parametrize("zone", ["Invalid/Zone", "", "../UTC", "x" * 65])
def test_invalid_timezone_rejected_on_create_and_update(schedule_user, zone):
    _, token, _ = schedule_user
    assert create_profile(token, {**base_profile_payload(), "timezone": zone}).status_code == 422
    assert create_profile(token).status_code == 201
    assert patch_profile(token, {"timezone": zone}).status_code == 422
    assert get_profile(token).json()["timezone"] == "UTC"


@pytest.mark.parametrize("field,value", [
    ("usual_wake_time", None), ("usual_sleep_time", None), ("timezone", None),
    ("meals_per_day", None), ("usual_wake_time", "11:00+05:00"),
    ("usual_sleep_time", "03:00Z"), ("usual_wake_time", "25:00"),
])
def test_required_schedule_fields_reject_null_or_invalid_times(schedule_user, field, value):
    _, token, _ = schedule_user
    assert create_profile(token, {**base_profile_payload(), field: value}).status_code == 422
    assert create_profile(token).status_code == 201
    before = get_profile(token).json()
    assert patch_profile(token, {field: value}).status_code == 422
    assert get_profile(token).json() == before


def test_equal_wake_sleep_rejected_including_partial_update(schedule_user):
    _, token, _ = schedule_user
    assert create_profile(token, {**base_profile_payload(),
        "usual_wake_time": "11:00", "usual_sleep_time": "11:00",
    }).status_code == 422
    assert create_profile(token, {**base_profile_payload(), "usual_wake_time": "23:00"}).status_code == 422
    assert create_profile(token).status_code == 201
    before = get_profile(token).json()
    for changes in (
        {"usual_wake_time": "23:00"}, {"usual_sleep_time": "07:00"},
        {"usual_wake_time": "11:00", "usual_sleep_time": "11:00"},
    ):
        rejected = patch_profile(token, changes)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "INVALID_PROFILE_DATA"
        assert get_profile(token).json() == before


@pytest.mark.parametrize("target,direction", [
    (90, "lose_weight"), (100, "gain_weight"), (95, "maintain_weight"), (None, None),
])
def test_weight_direction_is_derived_separately_from_nutrition_goal(schedule_user, target, direction):
    _, token, _ = schedule_user
    response = create_profile(token, {**base_profile_payload(),
        "weight_kg": 95, "target_weight_kg": target, "goal": "muscle_gain",
    })
    assert response.status_code == 201, response.text
    assert response.json()["weight_direction"] == direction
    assert response.json()["goal"] == "muscle_gain"
    assert get_profile(token).json()["weight_direction"] == direction
    changed = patch_profile(token, {"weight_kg": 105, "target_weight_kg": 100})
    assert changed.status_code == 200
    assert changed.json()["weight_direction"] == "lose_weight"
    assert changed.json()["goal"] == "muscle_gain"
    assert patch_profile(token, {"target_weight_kg": None}).json()["weight_direction"] is None


@pytest.mark.parametrize("field,value,constraint", [
    ("meals_per_day", 1, "ck_user_profiles_meals_per_day_range"),
    ("meals_per_day", 6, "ck_user_profiles_meals_per_day_range"),
    ("usual_wake_time", time(23), "ck_user_profiles_wake_sleep_different"),
])
def test_profile_database_constraints(schedule_user, field, value, constraint):
    db, token, email = schedule_user
    assert create_profile(token).status_code == 201
    profile = db.query(User).filter_by(email=email).one().profile
    setattr(profile, field, value)
    with pytest.raises(IntegrityError) as error:
        db.flush()
    assert error.value.orig.diag.constraint_name == constraint
    db.rollback()
