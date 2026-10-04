from datetime import UTC, datetime

import pytest

from app.core.cron import cron_trigger_from_crontab

SUNDAY = datetime(2026, 10, 4, 0, 0, tzinfo=UTC)


def _fire_days(expression: str, count: int = 7) -> list[str]:
    trigger = cron_trigger_from_crontab(expression, timezone=UTC)
    days, previous, now = [], None, SUNDAY
    for _ in range(count):
        previous = trigger.get_next_fire_time(previous, now)
        now = previous
        days.append(previous.strftime("%a"))
    return days


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 9 * * 1", ["Mon"]),
        ("0 9 * * 0", ["Sun"]),
        ("0 9 * * 7", ["Sun"]),
        ("0 9 * * 1-5", ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        ("0 9 * * 5-7", ["Fri", "Sat", "Sun"]),
        ("0 9 * * 0,6", ["Sun", "Sat"]),
        ("0 9 * * */2", ["Sun", "Tue", "Thu", "Sat"]),
        ("0 9 * * mon-fri", ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        ("0 9 * * *", ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]),
    ],
)
def test_day_of_week_follows_standard_cron(expression, expected):
    assert sorted(set(_fire_days(expression, 14))) == sorted(expected)


def test_first_fire_of_monday_schedule_is_monday():
    assert _fire_days("30 6 * * 1", 1) == ["Mon"]


@pytest.mark.parametrize("expression", ["0 9 * * 8", "0 9 * * 5-2", "0 9 * *"])
def test_invalid_expressions_are_rejected(expression):
    with pytest.raises(ValueError):
        cron_trigger_from_crontab(expression, timezone=UTC)
