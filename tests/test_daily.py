"""Tests for aggregating the hourly forecast into daily entries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.dmi.coordinator import DMIDataUpdateCoordinator
from custom_components.dmi.daily import build_daily_forecast

TZ = ZoneInfo("Europe/Copenhagen")
MIDNIGHT_JAN_15 = datetime(2024, 1, 14, 23, tzinfo=UTC)  # 00:00 local


def _hours(start: datetime, count: int, **values: object) -> list[dict[str, object]]:
    """Build hourly entries starting at ``start`` (UTC) with constant values."""
    return [
        {"datetime": (start + timedelta(hours=offset)).isoformat(), **values}
        for offset in range(count)
    ]


def test_days_follow_local_calendar_and_include_past_hours() -> None:
    """Days are local, include passed hours, and skip yesterday and short future days."""
    # Jan 14 (yesterday), Jan 15 (today) and 6 hours of Jan 16, plus an unusable entry.
    hourly = _hours(MIDNIGHT_JAN_15 - timedelta(days=1), 54, temperature=5.0)
    hourly[24 + 2]["temperature"] = -2.0  # 02:00 local today, already in the past
    hourly[24 + 14]["temperature"] = 9.0
    hourly.append({"datetime": None})

    daily = build_daily_forecast(hourly, MIDNIGHT_JAN_15 + timedelta(hours=12), TZ)

    assert [(d["datetime"], d["temperature"], d["templow"]) for d in daily] == [
        ("2024-01-15T00:00:00+01:00", 9.0, -2.0)
    ]


def test_precipitation_wind_and_humidity_aggregation() -> None:
    """Precipitation is summed, wind is the peak hour and humidity is averaged."""
    hourly = _hours(
        MIDNIGHT_JAN_15, 24, temperature=4.0, precipitation=0.25, humidity=80.0, wind_speed=3.0
    )
    hourly[14].update(wind_speed=11.0, wind_dir=250.0)

    day = build_daily_forecast(hourly, MIDNIGHT_JAN_15, TZ)[0]

    assert (day["precipitation"], day["condition"]) == (6.0, "rainy")
    assert (day["wind_speed"], day["wind_dir"], day["humidity"]) == (11.0, 250.0, 80)


@pytest.mark.parametrize(
    ("precipitation", "daytime_cover", "expected"),
    [
        (0.5, 100.0, "pouring"),  # 12 mm in the day
        (0.02, 40.0, "partlycloudy"),  # trace rain falls back to clouds
        (0.0, 5.0, "sunny"),  # clear day despite an overcast night
    ],
)
def test_day_condition(precipitation: float, daytime_cover: float, expected: str) -> None:
    """Day totals decide rain; otherwise the daytime cloud cover decides."""
    hourly = _hours(MIDNIGHT_JAN_15, 24, temperature=2.0, precipitation=precipitation)
    for hour, entry in enumerate(hourly):
        entry["cloud_cover"] = daytime_cover if 8 <= hour < 18 else 100.0

    assert build_daily_forecast(hourly, MIDNIGHT_JAN_15, TZ)[0]["condition"] == expected


def test_coordinator_aggregates_the_whole_cached_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The coordinator feeds the unfiltered cached run (with past hours) to the aggregation."""
    monkeypatch.setattr(
        "custom_components.dmi.coordinator.dt_util",
        SimpleNamespace(
            utcnow=lambda: MIDNIGHT_JAN_15 + timedelta(hours=12),
            get_default_time_zone=lambda: TZ,
        ),
    )
    cache = SimpleNamespace(_weather_forecast=None)
    assert DMIDataUpdateCoordinator.daily_forecast(cache) == []

    cache._weather_forecast = {"hourly": _hours(MIDNIGHT_JAN_15, 24, temperature=3.0)}
    cache._weather_forecast["hourly"][2]["temperature"] = -1.0

    assert DMIDataUpdateCoordinator.daily_forecast(cache)[0]["templow"] == -1.0
