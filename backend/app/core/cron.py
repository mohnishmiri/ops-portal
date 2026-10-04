"""Standard crontab on APScheduler 3, whose from_crontab counts day-of-week from Monday (0=mon), not Sunday."""

from datetime import tzinfo

from apscheduler.triggers.cron import CronTrigger

_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _standard_dow_to_names(field: str) -> str:
    if field in ("*", "?"):
        return "*"

    parts: list[str] = []
    days: set[int] = set()
    for part in field.split(","):
        if any(char.isalpha() for char in part):
            parts.append(part)
            continue
        span, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if span == "*":
            low, high = 0, 6
        elif "-" in span:
            low_text, high_text = span.split("-", 1)
            low, high = int(low_text), int(high_text)
        else:
            low = int(span)
            high = 7 if step_text else low
        if not (0 <= low <= 7 and 0 <= high <= 7 and low <= high and step >= 1):
            raise ValueError(f"Invalid day-of-week field in cron expression: {field!r}")
        days.update(day % 7 for day in range(low, high + 1, step))

    parts.extend(_DOW_NAMES[day] for day in sorted(days))
    return ",".join(parts)


def cron_trigger_from_crontab(expression: str, timezone: tzinfo | str) -> CronTrigger:
    fields = expression.split()
    if len(fields) == 5:
        fields[4] = _standard_dow_to_names(fields[4])
    return CronTrigger.from_crontab(" ".join(fields), timezone=timezone)
