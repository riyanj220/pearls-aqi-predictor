"""System health, model, pipeline, and infrastructure components."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from dashboard.utils.formatting import (
    format_boolean_status,
    format_freshness,
    format_timestamp,
)


PRODUCTION_MODEL = {
    "version": 1,
    "model_type": "XGBRegressor",
    "model_name": "xgboost_shallower",
    "strategy": (
        "hybrid_persistence_1_12_"
        "xgboost_shallower_13_72"
    ),
    "feature_count": 56,
    "best_iteration": 323,
    "training_date_utc": (
        "2026-07-26T09:37:43.161320+00:00"
    ),
    "routing": {
        "short_horizon": "Current PM2.5 persistence",
        "short_range": "1–12 hours",
        "long_horizon": "XGBoost regression",
        "long_range": "13–72 hours",
    },
    "test_metrics": {
        "mae": 3.715506901271162,
        "rmse": 4.975563144569727,
        "r2": -0.003985667037644358,
    },
    "validation_metrics": {
        "mae": 6.695642304681119,
        "rmse": 9.419552655549651,
        "r2": 0.06661111029588762,
    },
    "test_baselines": {
        "current_persistence": {
            "mae": 3.8353690130576856,
            "rmse": 5.28309937441166,
            "r2": -0.13193265230490026,
        },
        "previous_day_persistence": {
            "mae": 4.543849348417585,
            "rmse": 6.117523920308621,
            "r2": -0.517729518158885,
        },
    },
    "rmse_improvement_percent": (
        5.821132786777854
    ),
    "row_counts": {
        "train": 364_798,
        "validation": 71_256,
        "test": 76_813,
    },
    "data_ranges": {
        "train": (
            "9 Jul 2025",
            "18 Mar 2026",
        ),
        "validation": (
            "21 Mar 2026",
            "27 May 2026",
        ),
        "test": (
            "30 May 2026",
            "23 Jul 2026",
        ),
    },
}


def normalize_status(
    value: Any,
) -> str:
    """Convert internal status values into readable labels."""

    if value is None:
        return "Unknown"

    normalized = str(value).upper()

    replacements = {
        "READY_WITH_LIMITATIONS": "Ready",
        "AQI_ALERT_PIPELINE_APPROVED": "Approved",
        "AQI_ALERT_PIPELINE_APPROVED_WITH_LIMITATIONS": (
            "Approved"
        ),
        "PASSED": "Passed",
        "ALIVE": "Online",
        "FRESH": "Fresh",
        "AGING": "Aging",
        "STALE": "Stale",
    }

    if normalized in replacements:
        return replacements[
            normalized
        ]

    return normalized.replace(
        "_",
        " ",
    ).title()


def _system_is_healthy(
    *,
    liveness: dict[str, Any],
    readiness: dict[str, Any],
    pipeline: dict[str, Any],
) -> bool:
    """Return whether core serving conditions are fully healthy."""

    live_status = normalize_status(
        liveness.get(
            "status"
        )
    )

    ready_status = normalize_status(
        readiness.get(
            "status"
        )
    )

    freshness_status = normalize_status(
        readiness.get(
            "freshness",
            {},
        ).get(
            "status"
        )
    )

    source_degraded = bool(
        readiness.get(
            "source_degraded",
            False,
        )
    )

    artifact_ok = bool(
        pipeline.get(
            "artifact_consistency_passed",
            False,
        )
    )

    return (
        live_status == "Online"
        and ready_status == "Ready"
        and freshness_status
        in {
            "Fresh",
            "Aging",
        }
        and not source_degraded
        and artifact_ok
    )


def render_system_hero(
    *,
    liveness: dict[str, Any],
    readiness: dict[str, Any],
    pipeline: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render the current production serving posture."""

    healthy = _system_is_healthy(
        liveness=liveness,
        readiness=readiness,
        pipeline=pipeline,
    )

    freshness = readiness.get(
        "freshness",
        {},
    )

    age_hours = freshness.get(
        "age_hours"
    )

    if age_hours is None:
        freshness_text = (
            "Forecast age unavailable"
        )
    elif float(age_hours) < 1:
        freshness_text = (
            f"{round(float(age_hours) * 60)} min old"
        )
    else:
        freshness_text = (
            f"{float(age_hours):.1f}h old"
        )

    generated = format_timestamp(
        pipeline.get(
            "generated_at_utc"
        ),
        timezone_name=timezone_name,
        include_timezone=False,
    )

    row_count = int(
        pipeline.get(
            "forecast_row_count",
            0,
        )
    )

    source_degraded = bool(
        readiness.get(
            "source_degraded",
            False,
        )
    )

    freshness_status = str(
        freshness.get(
            "status",
            "",
        )
    ).upper()

    forecast_available = bool(
        readiness.get(
            "forecast_available",
            False,
        )
    )

    if healthy:
        title = "System operational"
        state = "HEALTHY"
        state_class = "normal"
        accent = "#4ADE80"

        description = (
            "The latest validated forecast is available "
            "and all production serving conditions are normal."
        )

    elif not forecast_available:
        title = "Forecast temporarily unavailable"
        state = "UNAVAILABLE"
        state_class = "warning"
        accent = "#F87171"

        description = (
            "The application is online, but a validated "
            "forecast cannot currently be served."
        )

    elif freshness_status == "STALE":
        title = "Forecast data delayed"
        state = "STALE"
        state_class = "warning"
        accent = "#FACC15"

        description = (
            "Fresh source observations are temporarily delayed. "
            "The most recent validated forecast is still available."
        )

    elif source_degraded:
        title = "System operational with degraded input"
        state = "DEGRADED"
        state_class = "warning"
        accent = "#FACC15"

        description = (
            "A short PM2.5 sensor gap was automatically "
            "recovered. Forecast serving remains operational."
        )

    else:
        title = "System requires attention"
        state = "CHECK"
        state_class = "warning"
        accent = "#FACC15"

        description = (
            "One or more production readiness conditions "
            "require review."
        )

    st.html(
        f"""
        <div
            class="system-hero"
            style="--system-accent:{accent};"
        >
            <div class="system-hero-top">
                <div>
                    <div class="aqi-hero-eyebrow">
                        PRODUCTION STATUS
                    </div>

                    <div class="system-hero-title">
                        {escape(title)}
                    </div>
                </div>

                <div class="alert-state-pill {state_class}">
                    <span class="alert-state-dot"></span>
                    {escape(state)}
                </div>
            </div>

            <p class="system-hero-message">
                {escape(description)}
            </p>

            <div class="system-facts">
                <div class="system-fact">
                    <span>Forecast</span>
                    <strong>{row_count} hours</strong>
                </div>

                <div class="system-fact">
                    <span>Freshness</span>
                    <strong>{escape(freshness_text)}</strong>
                </div>

                <div class="system-fact">
                    <span>Generated</span>
                    <strong>{escape(generated)}</strong>
                </div>

                <div class="system-fact">
                    <span>Model</span>
                    <strong>Version {PRODUCTION_MODEL["version"]}</strong>
                </div>
            </div>
        </div>
        """
    )


def render_service_status_cards(
    *,
    liveness: dict[str, Any],
    readiness: dict[str, Any],
    pipeline: dict[str, Any],
) -> None:
    """Render public-facing production health cards."""

    freshness = readiness.get(
        "freshness",
        {},
    )

    columns = st.columns(4)

    with columns[0]:
        st.metric(
            "API",
            normalize_status(
                liveness.get(
                    "status"
                )
            ),
        )

        st.caption(
            "Serving forecast requests"
        )

    with columns[1]:
        st.metric(
            "Forecast service",
            normalize_status(
                readiness.get(
                    "status"
                )
            ),
        )

        st.caption(
            "Latest forecast available"
        )

    with columns[2]:
        st.metric(
            "Freshness",
            normalize_status(
                freshness.get(
                    "status"
                )
            ),
        )

        st.caption(
            format_freshness(
                status=freshness.get(
                    "status"
                ),
                age_hours=freshness.get(
                    "age_hours"
                ),
            )
        )

    with columns[3]:
        artifact_status = (
            format_boolean_status(
                pipeline.get(
                    "artifact_consistency_passed"
                ),
                true_label="Passed",
                false_label="Failed",
            )
        )

        st.metric(
            "Artifact validation",
            artifact_status,
        )

        st.caption(
            "Forecast artifact consistency"
        )


def render_operational_overview(
    *,
    pipeline: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render useful forecast execution information."""

    st.html(
        """
        <div class="section-kicker">
            CURRENT PUBLICATION
        </div>

        <div class="section-title">
            Latest forecast delivery
        </div>

        <div class="section-description">
            Public-facing information about the
            currently published forecast artifact.
        </div>
        """
    )

    columns = st.columns(4)

    with columns[0]:
        st.metric(
            "Forecast rows",
            int(
                pipeline.get(
                    "forecast_row_count",
                    0,
                )
            ),
        )

        st.caption(
            "Hourly predictions"
        )

    with columns[1]:
        st.metric(
            "Active alert hours",
            int(
                pipeline.get(
                    "active_alert_count",
                    0,
                )
            ),
        )

        st.caption(
            "Triggered forecast hours"
        )

    with columns[2]:
        st.metric(
            "Alert episodes",
            int(
                pipeline.get(
                    "alert_episode_count",
                    0,
                )
            ),
        )

        st.caption(
            "Grouped alert events"
        )

    with columns[3]:
        st.metric(
            "Generated",
            format_timestamp(
                pipeline.get(
                    "generated_at_utc"
                ),
                timezone_name=timezone_name,
                include_timezone=False,
            ),
        )

        st.caption(
            "Latest publication"
        )


def render_model_strategy() -> None:
    """Render the production forecasting strategy."""

    routing = PRODUCTION_MODEL[
        "routing"
    ]

    st.html(
        """
        <div class="section-kicker">
            PRODUCTION MODEL
        </div>

        <div class="section-title">
            Hybrid horizon-aware forecasting
        </div>

        <div class="section-description">
            The production strategy routes short
            and longer forecast horizons to the
            approach that performed best during
            chronological validation.
        </div>
        """
    )

    left, right = st.columns(
        2,
        gap="large",
    )

    with left:
        st.html(
            f"""
            <div class="model-route-card">
                <div class="model-route-range">
                    {escape(routing["short_range"])}
                </div>

                <div class="model-route-title">
                    {escape(routing["short_horizon"])}
                </div>

                <div class="model-route-body">
                    Immediate PM2.5 conditions showed
                    strong persistence, making the most
                    recent observed concentration the
                    stronger short-range strategy.
                </div>
            </div>
            """
        )

    with right:
        st.html(
            f"""
            <div class="model-route-card">
                <div class="model-route-range">
                    {escape(routing["long_range"])}
                </div>

                <div class="model-route-title">
                    {escape(routing["long_horizon"])}
                </div>

                <div class="model-route-body">
                    A shallower XGBoost regressor captures
                    nonlinear PM2.5, weather, temporal,
                    rolling, and horizon relationships
                    across medium and long ranges.
                </div>
            </div>
            """
        )

    st.markdown("")

    details = st.columns(4)

    with details[0]:
        st.metric(
            "Model version",
            PRODUCTION_MODEL[
                "version"
            ],
        )

        st.caption(
            "Production registry version"
        )

    with details[1]:
        st.metric(
            "Input features",
            PRODUCTION_MODEL[
                "feature_count"
            ],
        )

        st.caption(
            "Ordered feature contract"
        )

    with details[2]:
        st.metric(
            "Boosting iteration",
            PRODUCTION_MODEL[
                "best_iteration"
            ],
        )

        st.caption(
            "Best validation iteration"
        )

    with details[3]:
        st.metric(
            "Long-range model",
            "XGBoost",
        )

        st.caption(
            "xgboost_shallower"
        )


def render_model_evaluation() -> None:
    """Render final untouched test performance."""

    test = PRODUCTION_MODEL[
        "test_metrics"
    ]

    improvement = PRODUCTION_MODEL[
        "rmse_improvement_percent"
    ]

    st.html(
        """
        <div class="section-kicker">
            FINAL EVALUATION
        </div>

        <div class="section-title">
            Untouched chronological test performance
        </div>

        <div class="section-description">
            Final performance was measured once on
            the latest held-out historical period
            after model selection was complete.
        </div>
        """
    )

    columns = st.columns(4)

    with columns[0]:
        st.metric(
            "Test MAE",
            f"{test['mae']:.2f} µg/m³",
        )

        st.caption(
            "Mean absolute error"
        )

    with columns[1]:
        st.metric(
            "Test RMSE",
            f"{test['rmse']:.2f} µg/m³",
        )

        st.caption(
            "Root mean squared error"
        )

    with columns[2]:
        st.metric(
            "RMSE vs persistence",
            f"{improvement:.2f}% lower",
        )

        st.caption(
            "Compared with current-value persistence"
        )

    with columns[3]:
        st.metric(
            "Test observations",
            f"{PRODUCTION_MODEL['row_counts']['test']:,}",
        )

        st.caption(
            "Held-out forecast rows"
        )

    st.markdown("")

    st.html(
        """
        <div class="benchmark-heading">
            Baseline comparison
        </div>
        """
    )

    current = (
        PRODUCTION_MODEL[
            "test_baselines"
        ][
            "current_persistence"
        ]
    )

    previous = (
        PRODUCTION_MODEL[
            "test_baselines"
        ][
            "previous_day_persistence"
        ]
    )

    benchmark_rows = [
        (
            "Production hybrid",
            test["rmse"],
            "Selected strategy",
        ),
        (
            "Current persistence",
            current["rmse"],
            "Short-range baseline",
        ),
        (
            "Previous-day persistence",
            previous["rmse"],
            "Daily-pattern baseline",
        ),
    ]

    for name, rmse, description in benchmark_rows:
        st.html(
            f"""
            <div class="benchmark-row">
                <div>
                    <div class="benchmark-name">
                        {escape(name)}
                    </div>

                    <div class="benchmark-description">
                        {escape(description)}
                    </div>
                </div>

                <div class="benchmark-value">
                    {rmse:.2f}
                    <span>RMSE</span>
                </div>
            </div>
            """
        )

    with st.expander(
        "Evaluation details",
        expanded=False,
    ):
        st.write(
            f"**Test R²:** "
            f"{test['r2']:.3f}"
        )

        st.write(
            "The chronological test period had "
            "relatively limited PM2.5 variance. "
            "R² was therefore close to zero, while "
            "the selected strategy still improved "
            "MAE and RMSE over persistence baselines."
        )

        st.write(
            "**Selection criterion:** "
            "lowest overall validation RMSE."
        )

        st.write(
            "**Negative XGBoost test predictions:** 0"
        )


def render_training_evaluation_split() -> None:
    """Render chronological train/validation/test information."""

    st.markdown(
        "### Chronological evaluation design"
    )

    columns = st.columns(3)

    labels = [
        (
            "Training",
            "train",
        ),
        (
            "Validation",
            "validation",
        ),
        (
            "Test",
            "test",
        ),
    ]

    for column, (
        label,
        key,
    ) in zip(
        columns,
        labels,
        strict=True,
    ):
        start, end = (
            PRODUCTION_MODEL[
                "data_ranges"
            ][key]
        )

        rows = (
            PRODUCTION_MODEL[
                "row_counts"
            ][key]
        )

        with column:
            st.html(
                f"""
                <div class="dataset-card">
                    <div class="dataset-label">
                        {escape(label)}
                    </div>

                    <div class="dataset-count">
                        {rows:,}
                    </div>

                    <div class="dataset-caption">
                        rows
                    </div>

                    <div class="dataset-range">
                        {escape(start)}
                        <br>
                        ↓
                        <br>
                        {escape(end)}
                    </div>
                </div>
                """
            )


def render_pipeline_architecture(
    *,
    pipeline: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render production workload architecture."""

    st.html(
        """
        <div class="section-kicker">
            PRODUCTION WORKLOADS
        </div>

        <div class="section-title">
            Automated forecasting pipeline
        </div>

        <div class="section-description">
            Four Azure Container Apps Jobs keep the
            production system synchronized, forecasted,
            evaluated, and monitored.
        </div>
        """
    )

    generated = format_timestamp(
        pipeline.get(
            "generated_at_utc"
        ),
        timezone_name=timezone_name,
        include_timezone=False,
    )

    forecast_status = normalize_status(
        pipeline.get(
            "phase_6_status"
        )
    )

    workloads = [
        {
            "title": "Feature synchronization",
            "schedule": "Hourly",
            "status": "Scheduled",
            "description": (
                "Refreshes PM2.5 and weather-derived "
                "feature datasets in Azure Blob Storage."
            ),
        },
        {
            "title": "Forecast publication",
            "schedule": "Every 6 hours",
            "status": forecast_status,
            "description": (
                f"Generates and validates the latest "
                f"72-hour forecast. Current publication: "
                f"{generated}."
            ),
        },
        {
            "title": "Retraining evaluation",
            "schedule": "Daily",
            "status": "Scheduled",
            "description": (
                "Evaluates a challenger model against "
                "the production champion and promotes "
                "only when acceptance criteria are met."
            ),
        },
        {
            "title": "Production monitoring",
            "schedule": "Hourly",
            "status": "Scheduled",
            "description": (
                "Records health snapshots, detects "
                "operational issues, and delivers "
                "incident notifications."
            ),
        },
    ]

    columns = st.columns(2)

    for index, workload in enumerate(
        workloads
    ):
        with columns[index % 2]:
            st.html(
                f"""
                <div class="pipeline-card">
                    <div class="pipeline-card-top">
                        <div class="pipeline-title">
                            {escape(workload["title"])}
                        </div>

                        <div class="pipeline-status">
                            {escape(workload["status"])}
                        </div>
                    </div>

                    <div class="pipeline-schedule">
                        {escape(workload["schedule"])}
                    </div>

                    <div class="pipeline-description">
                        {escape(workload["description"])}
                    </div>
                </div>
                """
            )


def render_system_skeleton() -> None:
    """Render the high-level production data flow."""

    st.markdown(
        "### Production data flow"
    )

    steps = [
        (
            "OpenAQ + Open-Meteo",
            "Observations & weather",
        ),
        (
            "Feature repository",
            "Azure Blob Storage",
        ),
        (
            "Forecast strategy",
            "Persistence + XGBoost",
        ),
        (
            "AQI & alert layer",
            "Interpretation & episodes",
        ),
        (
            "Artifact publication",
            "Validated Azure Blob artifacts",
        ),
        (
            "FastAPI + Streamlit",
            "Serving & presentation",
        ),
    ]

    for index, (
        title,
        subtitle,
    ) in enumerate(
        steps
    ):
        st.html(
            f"""
            <div class="system-flow-step">
                <div class="system-flow-number">
                    {index + 1:02d}
                </div>

                <div>
                    <div class="system-flow-title">
                        {escape(title)}
                    </div>

                    <div class="system-flow-subtitle">
                        {escape(subtitle)}
                    </div>
                </div>
            </div>
            """
        )


def render_metadata(
    *,
    metadata: dict[str, Any],
) -> None:
    """Render public project and source metadata."""

    location = metadata.get(
        "location",
        {},
    )

    st.html(
        """
        <div class="section-kicker">
            DATA SOURCES
        </div>

        <div class="section-title">
            Forecast inputs and standards
        </div>

        <div class="section-description">
            Public data sources and forecast
            configuration used by the production system.
        </div>
        """
    )

    left, right = st.columns(
        2,
        gap="large",
    )

    with left:
        st.html(
            f"""
            <div class="metadata-card">
                <div class="metadata-card-label">
                    FORECAST COVERAGE
                </div>

                <div class="metadata-item">
                    <span>Location</span>
                    <strong>
                        {escape(str(location.get(
                            "name",
                            "Not available",
                        )))}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>Coordinates</span>
                    <strong>
                        {escape(str(location.get(
                            "latitude",
                            "—",
                        )))},
                        {escape(str(location.get(
                            "longitude",
                            "—",
                        )))}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>Pollutant</span>
                    <strong>
                        {escape(str(metadata.get(
                            "pollutant",
                            "PM2.5",
                        )))}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>Forecast horizon</span>
                    <strong>
                        {int(metadata.get(
                            "forecast_horizon_hours",
                            72,
                        ))} hours
                    </strong>
                </div>
            </div>
            """
        )

    with right:
        weather_sources = metadata.get(
            "weather_sources",
            [],
        )

        weather_text = (
            ", ".join(weather_sources)
            if weather_sources
            else "Not available"
        )

        st.html(
            f"""
            <div class="metadata-card">
                <div class="metadata-card-label">
                    DATA & AQI
                </div>

                <div class="metadata-item">
                    <span>PM2.5 source</span>
                    <strong>
                        {escape(str(metadata.get(
                            "pollution_source",
                            "OpenAQ",
                        )))}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>Weather</span>
                    <strong>
                        {escape(weather_text)}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>AQI standard</span>
                    <strong>
                        {escape(str(metadata.get(
                            "aqi_standard_name",
                            "Not available",
                        )))}
                    </strong>
                </div>

                <div class="metadata-item">
                    <span>AQI version</span>
                    <strong>
                        {escape(str(metadata.get(
                            "aqi_standard_version",
                            "Not available",
                        )))}
                    </strong>
                </div>
            </div>
            """
        )


def render_infrastructure() -> None:
    """Render production infrastructure summary."""

    st.markdown(
        "### Production infrastructure"
    )

    infrastructure = [
        (
            "Feature repository",
            "Azure Blob Storage",
        ),
        (
            "Model registry",
            "Azure Blob Storage",
        ),
        (
            "Artifact repository",
            "Azure Blob Storage",
        ),
        (
            "Scheduled workloads",
            "Azure Container Apps Jobs",
        ),
        (
            "Forecast API",
            "FastAPI",
        ),
        (
            "Dashboard",
            "Streamlit",
        ),
        (
            "Container registry",
            "Azure Container Registry",
        ),
        (
            "Incident delivery",
            "Azure Communication Services",
        ),
    ]

    columns = st.columns(2)

    for index, (
        label,
        value,
    ) in enumerate(
        infrastructure
    ):
        with columns[index % 2]:
            st.html(
                f"""
                <div class="infra-row">
                    <span>{escape(label)}</span>
                    <strong>{escape(value)}</strong>
                </div>
                """
            )


def render_location_map(
    *,
    metadata: dict[str, Any],
) -> None:
    """Render the reference location using an embedded map."""

    location = metadata.get(
        "location",
        {},
    )

    latitude = location.get(
        "latitude"
    )

    longitude = location.get(
        "longitude"
    )

    if (
        latitude is None
        or longitude is None
    ):
        st.info(
            "Reference-location coordinates are unavailable."
        )
        return

    latitude = float(
        latitude
    )

    longitude = float(
        longitude
    )

    location_name = str(
        location.get(
            "name",
            "Zafar Memon DHA",
        )
    )

    st.html(
        """
        <div class="section-kicker">
            REFERENCE LOCATION
        </div>

        <div class="section-title">
            Monitoring location
        </div>

        <div class="section-description">
            The forecast represents one validated
            reference point rather than all of Karachi.
        </div>
        """
    )

    map_url = (
        "https://maps.google.com/maps"
        f"?q={latitude},{longitude}"
        "&z=13"
        "&output=embed"
    )

    st.iframe(
        map_url,
        width="stretch",
        height=420,
    )

    st.caption(
        f"Reference point · {location_name} "
        f"({latitude:.6f}, {longitude:.6f})"
    )