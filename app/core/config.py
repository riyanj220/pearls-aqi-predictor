"""Central configuration for the Pearls AQI Predictor."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = PROJECT_ROOT / ".env"


load_dotenv(
    dotenv_path=ENV_FILE_PATH,
    override=False,
)

@dataclass(frozen=True)
class Settings:
    """Application and live-inference configuration."""

    # Project identity
    project_name: str = "Pearls AQI Predictor"
    forecast_description: str = (
        "72-hour PM2.5-based AQI forecast for the "
        "Zafar Memon DHA reference location in Karachi."
    )

    # Reference location
    location_name: str = "Zafar Memon DHA"
    latitude: float = 24.814741
    longitude: float = 67.067062

    # OpenAQ identifiers
    openaq_location_id: int = 4814327
    openaq_sensor_id: int = 13387396
    pollutant: str = "pm25"
    pollution_unit: str = "µg/m³"

    # Forecast settings
    timezone: str = "UTC"
    forecast_horizon_hours: int = 72
    persistence_max_horizon: int = 12

    # PM2.5 history requirements
    largest_required_lag_hours: int = 24
    largest_rolling_window_hours: int = 24
    largest_change_period_hours: int = 24

    # Request more than the strict minimum to handle missing recent hours.
    pm25_history_safety_buffer_hours: int = 48

    # The newest usable PM2.5 observation should not exceed this age.
    pm25_freshness_threshold_hours: int = 6

    # HTTP behavior
    request_timeout_seconds: int = 30
    request_retry_count: int = 3

    # Open-Meteo request coverage
    weather_past_hours: int = 12
    weather_forecast_hours: int = 84

    # API endpoints
    openaq_base_url: str = "https://api.openaq.org/v3"
    open_meteo_forecast_url: str = (
        "https://api.open-meteo.com/v1/forecast"
    )

    # Directories
    models_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "models"
    )
    training_data_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "data" / "training"
    )
    explainability_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "explainability"
    )
    error_analysis_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "error_analysis"
    )
    inference_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / "inference"
    )

    @property
    def best_model_path(self) -> Path:
        """Return the selected model artifact path."""
        return self.models_dir / "best_model.joblib"

    @property
    def model_feature_contract_path(self) -> Path:
        """Return the ordered model-feature contract path."""
        return self.models_dir / "model_feature_columns.json"

    @property
    def model_metadata_path(self) -> Path:
        """Return the saved model metadata path."""
        return self.models_dir / "model_metadata.json"

    @property
    def model_selection_report_path(self) -> Path:
        """Return the model-selection report path."""
        return self.models_dir / "model_selection_report.json"

    @property
    def phase_2_feature_contract_path(self) -> Path:
        """Return the Phase 2 feature contract path."""
        return self.training_data_dir / "feature_columns.json"

    @property
    def phase_4_explainability_report_path(self) -> Path:
        """Return the Phase 4 explainability report path."""
        return (
            self.explainability_dir
            / "phase_4_explainability_report.json"
        )

    @property
    def phase_4_error_analysis_report_path(self) -> Path:
        """Return the Phase 4 error-analysis report path."""
        return (
            self.error_analysis_dir
            / "phase_4_error_analysis_report.json"
        )

    @property
    def minimum_pm25_history_hours(self) -> int:
        """Return the strict minimum required PM2.5 history."""
        return max(
            self.largest_required_lag_hours,
            self.largest_rolling_window_hours,
            self.largest_change_period_hours,
        )

    @property
    def requested_pm25_lookback_hours(self) -> int:
        """Return the configured live PM2.5 request window."""
        return (
            self.minimum_pm25_history_hours
            + self.pm25_history_safety_buffer_hours
        )

    @property
    def openaq_api_key(self) -> str | None:
        """Read the OpenAQ API key from the environment."""
        value = os.getenv("OPENAQ_API_KEY")

        if value is None:
            return None

        cleaned_value = value.strip()

        return cleaned_value or None

    def require_openaq_api_key(self) -> str:
        """Return the API key or fail with a safe error."""
        api_key = self.openaq_api_key

        if api_key is None:
            raise RuntimeError(
                "OPENAQ_API_KEY is not configured. "
                "Add it to the project .env file or deployment "
                "environment before running live OpenAQ requests."
            )

        return api_key



settings = Settings()