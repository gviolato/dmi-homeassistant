"""Aggregate the hourly HARMONIE forecast into a daily forecast.

DMI's open forecast API only publishes hourly model steps (about 2.5 days
ahead), so daily entries are derived locally: one entry per calendar day in
Home Assistant's time zone with the day's high/low temperature, accumulated
precipitation, peak wind and a representative condition.

The aggregation runs on the full cached model run (including hours that have
already passed), so today's high/low covers the whole day where the run
reaches back far enough, not only the remaining hours.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, tzinfo
from typing import Any

from homeassistant.components.weather import ATTR_CONDITION_POURING, ATTR_CONDITION_RAINY
from homeassistant.util import dt as dt_util

from .conditions import condition_from_cloud_cover

# Future days need this many hourly steps to be published; a model run that
# ends early in the morning would otherwise report a misleading daily range.
MIN_HOURS_FOR_FUTURE_DAY = 12

# Local hours treated as "daytime" when choosing a day's sky condition.
DAYTIME_HOURS = range(8, 18)

# Daily precipitation thresholds (mm) for the day's condition.
RAINY_DAY_MM = 1.0
POURING_DAY_MM = 10.0


def _number(entry: dict[str, Any], key: str) -> float | None:
    value = entry.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day_condition(
    precipitation: float | None, items: list[tuple[datetime, dict[str, Any]]]
) -> str | None:
    if precipitation is not None and precipitation >= POURING_DAY_MM:
        return ATTR_CONDITION_POURING
    if precipitation is not None and precipitation >= RAINY_DAY_MM:
        return ATTR_CONDITION_RAINY

    daytime = [entry for local, entry in items if local.hour in DAYTIME_HOURS]
    covers = [
        cover
        for entry in (daytime or [entry for _, entry in items])
        if (cover := _number(entry, "cloud_cover")) is not None
    ]
    if not covers:
        return None
    return condition_from_cloud_cover(sum(covers) / len(covers), is_daytime=True)


def build_daily_forecast(
    hourly: list[dict[str, Any]],
    now: datetime,
    time_zone: tzinfo,
) -> list[dict[str, Any]]:
    """Return daily forecast entries (oldest first) aggregated from hourly steps."""
    days: dict[date, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for entry in hourly:
        timestamp = entry.get("datetime")
        parsed = dt_util.parse_datetime(timestamp) if isinstance(timestamp, str) else None
        if parsed is None:
            continue
        local = parsed.astimezone(time_zone)
        days[local.date()].append((local, entry))

    today = now.astimezone(time_zone).date()
    daily: list[dict[str, Any]] = []
    for day in sorted(days):
        if day < today:
            continue
        items = sorted(days[day], key=lambda item: item[0])
        if day > today and len(items) < MIN_HOURS_FOR_FUTURE_DAY:
            continue

        temperatures = [t for _, e in items if (t := _number(e, "temperature")) is not None]
        if not temperatures:
            continue

        precipitation_values = [
            p for _, e in items if (p := _number(e, "precipitation")) is not None
        ]
        precipitation = round(sum(precipitation_values), 1) if precipitation_values else None

        windiest = max(
            (e for _, e in items if _number(e, "wind_speed") is not None),
            key=lambda e: _number(e, "wind_speed") or 0.0,
            default=None,
        )
        humidities = [h for _, e in items if (h := _number(e, "humidity")) is not None]

        entry: dict[str, Any] = {
            "datetime": datetime.combine(day, datetime.min.time(), time_zone).isoformat(),
            "temperature": max(temperatures),
            "templow": min(temperatures),
        }
        if precipitation is not None:
            entry["precipitation"] = precipitation
        if windiest is not None:
            entry["wind_speed"] = _number(windiest, "wind_speed")
            if (bearing := _number(windiest, "wind_dir")) is not None:
                entry["wind_dir"] = bearing
        if humidities:
            entry["humidity"] = round(sum(humidities) / len(humidities))
        if (condition := _day_condition(precipitation, items)) is not None:
            entry["condition"] = condition
        daily.append(entry)

    return daily
