"""Central PM2.5 AQI definitions based on the U.S. EPA standard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PM25AQIBreakpoint:
    """One PM2.5 concentration-to-AQI interval."""

    concentration_low: float
    concentration_high: float
    aqi_low: int
    aqi_high: int
    category: str
    color_name: str
    color_hex: str
    severity_rank: int


PM25_AQI_BREAKPOINTS: tuple[PM25AQIBreakpoint, ...] = (
    PM25AQIBreakpoint(
        concentration_low=0.0,
        concentration_high=9.0,
        aqi_low=0,
        aqi_high=50,
        category="Good",
        color_name="Green",
        color_hex="#00E400",
        severity_rank=0,
    ),
    PM25AQIBreakpoint(
        concentration_low=9.1,
        concentration_high=35.4,
        aqi_low=51,
        aqi_high=100,
        category="Moderate",
        color_name="Yellow",
        color_hex="#FFFF00",
        severity_rank=1,
    ),
    PM25AQIBreakpoint(
        concentration_low=35.5,
        concentration_high=55.4,
        aqi_low=101,
        aqi_high=150,
        category="Unhealthy for Sensitive Groups",
        color_name="Orange",
        color_hex="#FF7E00",
        severity_rank=2,
    ),
    PM25AQIBreakpoint(
        concentration_low=55.5,
        concentration_high=125.4,
        aqi_low=151,
        aqi_high=200,
        category="Unhealthy",
        color_name="Red",
        color_hex="#FF0000",
        severity_rank=3,
    ),
    PM25AQIBreakpoint(
        concentration_low=125.5,
        concentration_high=225.4,
        aqi_low=201,
        aqi_high=300,
        category="Very Unhealthy",
        color_name="Purple",
        color_hex="#8F3F97",
        severity_rank=4,
    ),
    PM25AQIBreakpoint(
        concentration_low=225.5,
        concentration_high=325.4,
        aqi_low=301,
        aqi_high=500,
        category="Hazardous",
        color_name="Maroon",
        color_hex="#7E0023",
        severity_rank=5,
    ),
)


AQI_STANDARD_NAME = "U.S. EPA PM2.5 AQI"
AQI_STANDARD_VERSION = "May 2026"
AQI_CONCENTRATION_UNIT = "µg/m³"
AQI_MAX_STANDARD_VALUE = 500
AQI_BEYOND_CATEGORY = "Beyond the AQI"