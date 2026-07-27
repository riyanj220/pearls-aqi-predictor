import numpy as np
import pytest

from app.aqi.pm25_aqi import (
    PM25AQIConversionError,
    calculate_pm25_aqi,
    truncate_pm25,
)


@pytest.mark.parametrize(
    ("concentration", "expected_truncated"),
    [
        (9.09, 9.0),
        (9.19, 9.1),
        (35.49, 35.4),
        (35.59, 35.5),
    ],
)
def test_pm25_is_truncated_to_one_decimal(
    concentration: float,
    expected_truncated: float,
) -> None:
    assert truncate_pm25(concentration) == expected_truncated


@pytest.mark.parametrize(
    ("concentration", "expected_aqi", "expected_category"),
    [
        (0.0, 0, "Good"),
        (9.0, 50, "Good"),
        (9.1, 51, "Moderate"),
        (35.4, 100, "Moderate"),
        (35.5, 101, "Unhealthy for Sensitive Groups"),
        (55.5, 151, "Unhealthy"),
        (125.5, 201, "Very Unhealthy"),
        (225.5, 301, "Hazardous"),
        (325.4, 500, "Hazardous"),
    ],
)
def test_pm25_aqi_boundaries(
    concentration: float,
    expected_aqi: int,
    expected_category: str,
) -> None:
    result = calculate_pm25_aqi(concentration)

    assert result.aqi == expected_aqi
    assert result.category == expected_category


@pytest.mark.parametrize(
    "invalid_value",
    [-1.0, np.inf, -np.inf],
)
def test_invalid_pm25_values_are_rejected(
    invalid_value: float,
) -> None:
    with pytest.raises(PM25AQIConversionError):
        calculate_pm25_aqi(invalid_value)