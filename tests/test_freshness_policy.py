"""SLA de frescura: Boston desconta fins de semana, outras cidades nao."""
from datetime import datetime, timezone

from backend.services.freshness_policy import (
    effective_age_hours,
    raw_age_hours,
    weekend_hours_between,
)


def test_weekend_hours_between_saturday_and_sunday():
    start = datetime(2026, 11, 6, 14, 11, tzinfo=timezone.utc)  # sexta
    end = datetime(2026, 11, 8, 13, 53, tzinfo=timezone.utc)  # domingo
    assert weekend_hours_between(start, end) > 32


def test_boston_weekend_effective_age_is_business_age():
    start = datetime(2026, 11, 6, 14, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 8, 13, 53, tzinfo=timezone.utc)
    raw = raw_age_hours("BOSTON", start, end)
    effective = effective_age_hours("BOSTON", start, end)
    assert raw >= 47
    assert effective < 20


def test_boston_monday_morning_is_still_fresh():
    start = datetime(2026, 11, 6, 14, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)  # segunda 09:00 ET
    assert effective_age_hours("BOSTON", start, end) < 36


def test_other_cities_keep_calendar_age():
    start = datetime(2026, 11, 6, 14, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 8, 13, 53, tzinfo=timezone.utc)
    assert effective_age_hours("NYC", start, end) == raw_age_hours(
        "NYC", start, end
    )
