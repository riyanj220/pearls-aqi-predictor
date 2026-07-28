"""Shared dashboard constants."""

from __future__ import annotations


AQI_CATEGORIES: tuple[str, ...] = (
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
    "Beyond the AQI",
)


ALERT_LEVELS: tuple[str, ...] = (
    "NORMAL",
    "ADVISORY",
    "WARNING",
    "SEVERE",
    "EMERGENCY",
)


FORECAST_RANGES: tuple[int, ...] = (
    12,
    24,
    48,
    72,
)


SUPPORTED_TIMEZONES: dict[str, str] = {
    "Karachi": "Asia/Karachi",
    "UTC": "UTC",
}


NULL_DISPLAY_VALUE = "Not available"


AQI_COLOR_FALLBACKS: dict[str, str] = {
    "Good": "#00E400",
    "Moderate": "#FFFF00",
    "Unhealthy for Sensitive Groups": "#FF7E00",
    "Unhealthy": "#FF0000",
    "Very Unhealthy": "#8F3F97",
    "Hazardous": "#7E0023",
    "Beyond the AQI": "#7E0023",
}


ALERT_LEVEL_RANKS: dict[str, int] = {
    "NORMAL": 0,
    "ADVISORY": 1,
    "WARNING": 2,
    "SEVERE": 3,
    "EMERGENCY": 4,
}