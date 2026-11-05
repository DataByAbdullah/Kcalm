"""Deterministic local wall-clock schedules, independent of the server date/clock."""
from datetime import time


MINUTE_MICROSECONDS = 60 * 1_000_000
DAY_MICROSECONDS = 24 * 60 * MINUTE_MICROSECONDS


def time_microseconds(value: time) -> int:
    return ((value.hour * 60 + value.minute) * 60 + value.second) * 1_000_000 + value.microsecond


def local_time(microseconds: int) -> time:
    seconds, fraction = divmod(microseconds % DAY_MICROSECONDS, 1_000_000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return time(hours, minutes, seconds, fraction)


def schedule_meal_times(wake_time: time, sleep_time: time, meal_count: int) -> list[time]:
    if meal_count < 1:
        raise ValueError("At least one meal is required for scheduling.")
    if wake_time.tzinfo is not None or sleep_time.tzinfo is not None:
        raise ValueError("Schedules require local times without UTC offsets.")
    wake = time_microseconds(wake_time)
    awake_window = (time_microseconds(sleep_time) - wake) % DAY_MICROSECONDS
    if not awake_window:
        raise ValueError("Wake and sleep times must be different.")
    first = wake + 60 * MINUTE_MICROSECONDS
    last = wake + awake_window - 120 * MINUTE_MICROSECONDS
    if last <= first:
        # A window of three hours or less cannot accommodate both buffers.
        # Spread meals strictly inside that window instead of reversing time.
        return [local_time(wake + awake_window * (index + 1) // (meal_count + 1))
                for index in range(meal_count)]
    if meal_count == 1:
        return [local_time(first)]
    intervals = meal_count - 1
    return [local_time(first + ((last - first) * index + intervals // 2) // intervals)
            for index in range(meal_count)]
