from datetime import UTC, datetime

from app.services.mention_time_windows import next_allowed_at, normalize_time_windows


def test_overlapping_and_touching_windows_are_merged() -> None:
    assert normalize_time_windows(
        [
            {"start": "14:00", "end": "18:00"},
            {"start": "08:00", "end": "12:00"},
            {"start": "11:30", "end": "14:00"},
            {"start": "09:00", "end": "10:00"},
        ]
    ) == [{"start": "08:00", "end": "18:00"}]


def test_next_allowed_time_uses_vietnam_business_hours() -> None:
    windows = [
        {"start": "08:00", "end": "12:00"},
        {"start": "14:00", "end": "18:00"},
    ]

    assert next_allowed_at(datetime(2026, 8, 17, 3, 0, tzinfo=UTC), windows) == datetime(
        2026, 8, 17, 3, 0, tzinfo=UTC
    )
    assert next_allowed_at(datetime(2026, 8, 17, 6, 0, tzinfo=UTC), windows) == datetime(
        2026, 8, 17, 7, 0, tzinfo=UTC
    )
    assert next_allowed_at(datetime(2026, 8, 17, 12, 0, tzinfo=UTC), windows) == datetime(
        2026, 8, 18, 1, 0, tzinfo=UTC
    )
