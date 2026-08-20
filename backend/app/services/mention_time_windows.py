from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_MENTION_WINDOWS = [
    {"start": "08:00", "end": "12:00"},
    {"start": "14:00", "end": "18:00"},
]
MENTION_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def normalize_time_windows(windows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    parsed = sorted(
        (_time_to_minutes(window["start"]), _time_to_minutes(window["end"]))
        for window in windows
    )
    if not parsed:
        raise ValueError("Cần ít nhất một khung giờ hoạt động.")
    merged: list[list[int]] = []
    for start, end in parsed:
        if start >= end:
            raise ValueError("Giờ bắt đầu phải sớm hơn giờ kết thúc.")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        {"start": _minutes_to_time(start), "end": _minutes_to_time(end)}
        for start, end in merged
    ]


def next_allowed_at(candidate: datetime, windows: Iterable[Mapping[str, str]]) -> datetime:
    normalized = normalize_time_windows(windows)
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=UTC)
    candidate = candidate.astimezone(UTC)
    local_candidate = candidate.astimezone(MENTION_TIMEZONE)
    for window in normalized:
        start_at = datetime.combine(
            local_candidate.date(),
            _minutes_to_clock(_time_to_minutes(window["start"])),
            tzinfo=MENTION_TIMEZONE,
        )
        end_at = datetime.combine(
            local_candidate.date(),
            _minutes_to_clock(_time_to_minutes(window["end"])),
            tzinfo=MENTION_TIMEZONE,
        )
        if local_candidate < start_at:
            return start_at.astimezone(UTC)
        if start_at <= local_candidate < end_at:
            return candidate

    first_start = _time_to_minutes(normalized[0]["start"])
    next_day = local_candidate.date() + timedelta(days=1)
    return datetime.combine(
        next_day,
        _minutes_to_clock(first_start),
        tzinfo=MENTION_TIMEZONE,
    ).astimezone(UTC)


def _time_to_minutes(value: str) -> int:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Khung giờ phải có định dạng HH:MM.") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Khung giờ không hợp lệ.")
    return hour * 60 + minute


def _minutes_to_time(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _minutes_to_clock(value: int) -> time:
    return time(hour=value // 60, minute=value % 60)
