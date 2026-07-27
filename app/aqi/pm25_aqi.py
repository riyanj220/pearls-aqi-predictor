"""PM2.5 concentration-to-AQI conversion utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor, isfinite
from typing import Any

import numpy as np
import pandas as pd

from app.aqi.config import (
    AQI_BEYOND_CATEGORY,
    AQI_MAX_STANDARD_VALUE,
    PM25_AQI_BREAKPOINTS,
    PM25AQIBreakpoint,
)


class PM25AQIConversionError(ValueError):
    """Raised when PM2.5 cannot be converted safely."""


@dataclass(frozen=True)
class PM25AQIResult:
    """Structured result for one PM2.5-to-AQI conversion."""

    original_pm25_ug_m3: float
    truncated_pm25_ug_m3: float
    aqi: int
    category: str
    color_name: str
    color_hex: str
    severity_rank: int
    is_beyond_aqi: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the result as a regular dictionary."""

        return asdict(self)


def truncate_pm25(
    concentration: float,
) -> float:
    """
    Truncate a non-negative PM2.5 value to one decimal place.

    Truncation is intentionally different from ordinary rounding.
    For example, 9.09 becomes 9.0.
    """

    numeric_value = float(concentration)

    if not isfinite(numeric_value):
        raise PM25AQIConversionError(
            "PM2.5 concentration must be finite."
        )

    if numeric_value < 0:
        raise PM25AQIConversionError(
            "PM2.5 concentration cannot be negative."
        )

    return floor(numeric_value * 10) / 10


def _round_aqi(
    value: float,
) -> int:
    """
    Round a non-negative AQI value to the nearest integer.

    Using floor(value + 0.5) avoids Python's banker's-rounding
    behavior for exact half values.
    """

    return int(floor(value + 0.5))


def _interpolate_aqi(
    concentration: float,
    breakpoint: PM25AQIBreakpoint,
) -> int:
    """Calculate AQI through piecewise linear interpolation."""

    concentration_range = (
        breakpoint.concentration_high
        - breakpoint.concentration_low
    )

    if concentration_range <= 0:
        raise PM25AQIConversionError(
            "Invalid PM2.5 breakpoint configuration."
        )

    aqi_range = (
        breakpoint.aqi_high
        - breakpoint.aqi_low
    )

    interpolated_value = (
        (aqi_range / concentration_range)
        * (
            concentration
            - breakpoint.concentration_low
        )
        + breakpoint.aqi_low
    )

    return _round_aqi(interpolated_value)


def _find_breakpoint(
    truncated_concentration: float,
) -> PM25AQIBreakpoint | None:
    """Find the standard interval containing a concentration."""

    for breakpoint in PM25_AQI_BREAKPOINTS:
        if (
            breakpoint.concentration_low
            <= truncated_concentration
            <= breakpoint.concentration_high
        ):
            return breakpoint

    return None


def calculate_pm25_aqi(
    concentration: float,
) -> PM25AQIResult:
    """
    Convert one PM2.5 concentration to its EPA AQI interpretation.

    Values above the standard AQI 500 concentration are extrapolated
    using the Hazardous interval and marked as Beyond the AQI.
    """

    original_concentration = float(concentration)

    truncated_concentration = truncate_pm25(
        original_concentration
    )

    breakpoint = _find_breakpoint(
        truncated_concentration
    )

    is_beyond_aqi = breakpoint is None

    if is_beyond_aqi:
        hazardous_breakpoint = PM25_AQI_BREAKPOINTS[-1]

        aqi_value = _interpolate_aqi(
            truncated_concentration,
            hazardous_breakpoint,
        )

        category = AQI_BEYOND_CATEGORY
        color_name = hazardous_breakpoint.color_name
        color_hex = hazardous_breakpoint.color_hex
        severity_rank = hazardous_breakpoint.severity_rank
    else:
        assert breakpoint is not None

        aqi_value = _interpolate_aqi(
            truncated_concentration,
            breakpoint,
        )

        category = breakpoint.category
        color_name = breakpoint.color_name
        color_hex = breakpoint.color_hex
        severity_rank = breakpoint.severity_rank

    return PM25AQIResult(
        original_pm25_ug_m3=original_concentration,
        truncated_pm25_ug_m3=truncated_concentration,
        aqi=aqi_value,
        category=category,
        color_name=color_name,
        color_hex=color_hex,
        severity_rank=severity_rank,
        is_beyond_aqi=(
            aqi_value > AQI_MAX_STANDARD_VALUE
        ),
    )


def convert_pm25_series_to_aqi(
    concentrations: pd.Series,
) -> pd.DataFrame:
    """
    Convert a pandas Series of PM2.5 values into AQI columns.

    Missing values remain missing. Invalid finite negative values
    raise a clear conversion error.
    """

    numeric_concentrations = pd.to_numeric(
        concentrations,
        errors="coerce",
    )

    infinite_mask = pd.Series(
        np.isinf(
            numeric_concentrations.to_numpy(
                dtype=float
            )
        ),
        index=numeric_concentrations.index,
    )

    if infinite_mask.any():
        raise PM25AQIConversionError(
            "PM2.5 input contains infinite values."
        )

    negative_mask = numeric_concentrations.lt(0)

    if negative_mask.any():
        raise PM25AQIConversionError(
            "PM2.5 input contains negative values."
        )

    result_records: list[dict[str, Any]] = []

    for concentration in numeric_concentrations:
        if pd.isna(concentration):
            result_records.append(
                {
                    "pm25_ug_m3_original": np.nan,
                    "pm25_ug_m3_truncated": np.nan,
                    "aqi": pd.NA,
                    "aqi_category": pd.NA,
                    "aqi_color_name": pd.NA,
                    "aqi_color_hex": pd.NA,
                    "aqi_severity_rank": pd.NA,
                    "is_beyond_aqi": pd.NA,
                }
            )
            continue

        conversion = calculate_pm25_aqi(
            float(concentration)
        )

        result_records.append(
            {
                "pm25_ug_m3_original": (
                    conversion.original_pm25_ug_m3
                ),
                "pm25_ug_m3_truncated": (
                    conversion.truncated_pm25_ug_m3
                ),
                "aqi": conversion.aqi,
                "aqi_category": conversion.category,
                "aqi_color_name": (
                    conversion.color_name
                ),
                "aqi_color_hex": conversion.color_hex,
                "aqi_severity_rank": (
                    conversion.severity_rank
                ),
                "is_beyond_aqi": (
                    conversion.is_beyond_aqi
                ),
            }
        )

    result_df = pd.DataFrame(
        result_records,
        index=concentrations.index,
    )

    result_df["aqi"] = result_df["aqi"].astype(
        "Int64"
    )

    result_df["aqi_severity_rank"] = (
        result_df["aqi_severity_rank"].astype(
            "Int64"
        )
    )

    result_df["is_beyond_aqi"] = (
        result_df["is_beyond_aqi"].astype(
            "boolean"
        )
    )

    return result_df