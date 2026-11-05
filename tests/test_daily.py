"""Tests for aggregating the hourly forecast into daily entries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.dmi.coordinator import DMIDataUpdateCoordinator
from custom_components.dmi.daily import build_daily_forecast

TZ = ZoneInfo("Europe/Copenhagen")


def _hours(start: datetime, count: int, **values: object) -> list[dict[str, object]]:
    """Build hourly entries starting at ``start`` (UTC) with constant values."""
    return [
        {
            "datetime": (start + timedelta(hours=offset)).isoformat().replace("+00:00", "Z"),
            **values,
        }
        for offset in range(count)
    ]


def test_groups_by_local_day_with_high_and_low() -> None:
    """Hours are grouped by Home Assistant's local calendar day, not by UTC date."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)  # 00:00 local on Jan 15
    hourly = _hours(start, 48, cloud_cover=80.0, precipitation=0.0)
    for index, entry in enumerate(hourly):
        entry["temperature"] = float(index % 24)  # 0..23 within each local day

    daily = build_daily_forecast(hourly, start + timedelta(hours=10), TZ)

    assert [entry["datetime"] for entry in daily] == [
        "2024-01-15T00:00:00+01:00",
        "2024-01-16T00:00:00+01:00",
    ]
    assert daily[0]["temperature"] == 23.0
    assert daily[0]["templow"] == 0.0
    assert daily[0]["condition"] == "cloudy"


def test_today_includes_hours_that_already_passed() -> None:
    """Today's low still reflects the cold early-morning hours after they pass."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)
    hourly = _hours(start, 24, temperature=5.0)
    hourly[3]["temperature"] = -2.0  # 03:00 local
    now = start + timedelta(hours=12)  # 12:00 local

    daily = build_daily_forecast(hourly, now, TZ)

    assert daily[0]["templow"] == -2.0


def test_skips_past_days_and_short_future_days() -> None:
    """Yesterday is dropped and a future day with too few model steps is omitted."""
    start = datetime(2024, 1, 13, 23, tzinfo=UTC)  # 00:00 local on Jan 14
    hourly = _hours(start, 24 + 24 + 6, temperature=1.0)  # Jan 14, Jan 15, 6h of Jan 16
    now = datetime(2024, 1, 15, 9, tzinfo=UTC)

    daily = build_daily_forecast(hourly, now, TZ)

    assert [entry["datetime"][:10] for entry in daily] == ["2024-01-15"]


def test_precipitation_wind_and_humidity_aggregation() -> None:
    """Precipitation is summed, wind is the peak hour and humidity is averaged."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)
    hourly = _hours(start, 24, temperature=4.0, precipitation=0.25, humidity=80.0)
    for entry in hourly:
        entry["wind_speed"] = 3.0
        entry["wind_dir"] = 90.0
    hourly[14]["wind_speed"] = 11.0
    hourly[14]["wind_dir"] = 250.0
    hourly[0]["humidity"] = 60.0

    daily = build_daily_forecast(hourly, start, TZ)

    assert daily[0]["precipitation"] == 6.0
    assert daily[0]["condition"] == "rainy"
    assert daily[0]["wind_speed"] == 11.0
    assert daily[0]["wind_dir"] == 250.0
    assert daily[0]["humidity"] == 79


def test_condition_uses_daytime_cloud_cover_when_dry() -> None:
    """A clear day stays sunny even if the night is overcast."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)
    hourly = _hours(start, 24, temperature=2.0, precipitation=0.0)
    for index, entry in enumerate(hourly):
        entry["cloud_cover"] = 5.0 if 8 <= index < 18 else 100.0

    daily = build_daily_forecast(hourly, start, TZ)

    assert daily[0]["condition"] == "sunny"


def test_heavy_rain_day_is_pouring_and_trace_rain_is_not_rainy() -> None:
    """Day totals decide rain: >= 10 mm pouring, < 1 mm falls back to clouds."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)
    wet = _hours(start, 24, temperature=2.0, precipitation=0.5, cloud_cover=100.0)
    dry = _hours(start, 24, temperature=2.0, precipitation=0.02, cloud_cover=40.0)

    assert build_daily_forecast(wet, start, TZ)[0]["condition"] == "pouring"
    assert build_daily_forecast(dry, start, TZ)[0]["condition"] == "partlycloudy"


def test_ignores_entries_without_usable_data() -> None:
    """Entries without timestamps or temperatures do not produce days."""
    hourly = [{"datetime": None}, {"datetime": "nonsense"}, {"datetime": "2024-01-15T10:00:00Z"}]

    assert build_daily_forecast(hourly, datetime(2024, 1, 15, tzinfo=UTC), TZ) == []


def test_coordinator_daily_forecast_uses_whole_cached_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coordinator aggregates the full cached run, including past hours."""
    start = datetime(2024, 1, 14, 23, tzinfo=UTC)  # 00:00 local on Jan 15
    monkeypatch.setattr(
        "custom_components.dmi.coordinator.dt_util",
        SimpleNamespace(
            utcnow=lambda: start + timedelta(hours=12),
            get_default_time_zone=lambda: TZ,
        ),
    )

    cache = SimpleNamespace(_weather_forecast=None)
    assert DMIDataUpdateCoordinator.daily_forecast(cache) == []

    cache._weather_forecast = {"hourly": _hours(start, 24, temperature=3.0)}
    cache._weather_forecast["hourly"][2]["temperature"] = -1.0  # 02:00 local, already past

    daily = DMIDataUpdateCoordinator.daily_forecast(cache)

    assert [(entry["temperature"], entry["templow"]) for entry in daily] == [(3.0, -1.0)]
