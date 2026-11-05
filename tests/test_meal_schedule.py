from datetime import time, timezone

import pytest

from app.meal_planning.solver import MealSolverInputError, default_meal_slots
from app.services.meal_schedule_service import schedule_meal_times


@pytest.mark.parametrize("count,expected", [
    (2, ["breakfast", "dinner"]),
    (3, ["breakfast", "lunch", "dinner"]),
    (4, ["breakfast", "lunch", "pre_workout", "dinner"]),
    (5, ["breakfast", "lunch", "snack", "pre_workout", "dinner"]),
])
def test_automatic_slot_mapping_is_ordered_and_required(count, expected):
    slots = default_meal_slots(count)
    assert [slot.meal_type for slot in slots] == expected
    assert all(slot.required for slot in slots)


@pytest.mark.parametrize("count", [1, 6])
def test_automatic_slot_mapping_rejects_invalid_counts(count):
    with pytest.raises(MealSolverInputError):
        default_meal_slots(count)


@pytest.mark.parametrize("count,expected", [
    (1, ["12:00"]),
    (2, ["12:00", "01:00"]),
    (3, ["12:00", "18:30", "01:00"]),
    (4, ["12:00", "16:20", "20:40", "01:00"]),
    (5, ["12:00", "15:15", "18:30", "21:45", "01:00"]),
])
def test_overnight_schedule_is_deterministic_and_spaced_evenly(count, expected):
    expected_times = [time.fromisoformat(value) for value in expected]
    assert schedule_meal_times(time(11), time(3), count) == expected_times
    assert schedule_meal_times(time(11), time(3), count) == expected_times


@pytest.mark.parametrize("wake,sleep,count,expected", [
    (time(7), time(23), 3, [time(8), time(14, 30), time(21)]),
    (time(23), time(7), 3, [time(0), time(2, 30), time(5)]),
    (time(0), time(16), 2, [time(1), time(14)]),
    (time(11, 0, 30), time(3, 0, 30), 4,
     [time(12, 0, 30), time(16, 20, 30), time(20, 40, 30), time(1, 0, 30)]),
    (time(7), time(9), 4, [time(7, 24), time(7, 48), time(8, 12), time(8, 36)]),
    (time(7), time(10), 2, [time(8), time(9)]),
])
def test_daytime_midnight_and_short_awake_windows(wake, sleep, count, expected):
    assert schedule_meal_times(wake, sleep, count) == expected


@pytest.mark.parametrize("wake,sleep,count", [
    (time(7), time(7), 4), (time(7), time(23), 0),
    (time(7, tzinfo=timezone.utc), time(23), 4),
])
def test_invalid_schedule_inputs_are_rejected(wake, sleep, count):
    with pytest.raises(ValueError):
        schedule_meal_times(wake, sleep, count)
