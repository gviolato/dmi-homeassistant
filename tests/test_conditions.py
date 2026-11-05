"""Tests for DMI weather-code and cloud-cover condition mapping."""

from __future__ import annotations

import pytest

from custom_components.dmi.conditions import (
    condition_from_cloud_cover,
    condition_from_weather_code,
    forecast_condition,
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        # Automatic stations: WMO 4680 + 100
        (100, None),  # no significant weather -> caller uses cloud cover
        (100.0, None),
        (103, None),  # clouds developing
        (110, "fog"),  # mist
        (123, None),  # rain during the preceding hour, not now
        (130, "fog"),
        (141, "rainy"),
        (142, "pouring"),
        (145, "snowy"),
        (151, "rainy"),  # slight drizzle
        (161, "rainy"),  # slight rain
        (163, "pouring"),  # heavy rain
        (167, "snowy-rainy"),  # rain and snow
        (171, "snowy"),
        (181, "rainy"),  # slight rain showers
        (184, "pouring"),
        (189, "hail"),
        (191, "lightning"),
        (192, "lightning-rainy"),
        (196, "hail"),
        # Manned stations: WMO 4677
        (0, None),
        (3, None),
        (10, "fog"),
        (45, "fog"),
        (61, "rainy"),
        (65, "pouring"),
        (73, "snowy"),
        (80, "rainy"),
        (95, "lightning-rainy"),
        # Invalid / out of range
        (None, None),
        ("invalid", None),
        (100.5, None),
        (999, None),
        (-1, None),
    ],
)
def test_condition_from_weather_code(code: object, expected: str | None) -> None:
    """Weather codes map through the WMO table matching their range."""
    assert condition_from_weather_code(code) == expected


@pytest.mark.parametrize(
    ("cover", "is_daytime", "expected"),
    [
        (0.0, True, "sunny"),
        (19.9, True, "sunny"),
        (0.0, False, "clear-night"),
        (20.0, True, "partlycloudy"),
        (20.0, False, "partlycloudy"),
        (60.0, True, "cloudy"),
        (None, True, None),
        ("x", True, None),
    ],
)
def test_condition_from_cloud_cover(cover: object, is_daytime: bool, expected: str | None) -> None:
    """Cloud cover thresholds respect day and night."""
    assert condition_from_cloud_cover(cover, is_daytime=is_daytime) == expected


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"precipitation": 0.0, "cloud_cover": 100.0}, "cloudy"),
        ({"precipitation": 0.04, "cloud_cover": 10.0}, "sunny"),
        ({"precipitation": 0.1, "cloud_cover": 10.0}, "rainy"),
        ({"precipitation": 2.5}, "rainy"),
        ({}, None),
    ],
)
def test_forecast_condition(entry: dict[str, float], expected: str | None) -> None:
    """Only measurable precipitation (>= 0.1 mm/h) makes a forecast hour rainy."""
    assert forecast_condition(entry) == expected
