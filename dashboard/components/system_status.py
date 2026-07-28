"""System status and metadata components."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.utils.formatting import (
    format_boolean_status,
    format_freshness,
    format_timestamp,
)

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
        return replacements[normalized]

    return normalized.replace(
        "_",
        " ",
    ).title()


def render_service_status_cards(
    *,
    liveness: dict[str, Any],
    readiness: dict[str, Any],
    pipeline: dict[str, Any],
) -> None:
    """Render API and pipeline health cards."""

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

    with columns[1]:
        st.metric(
            "Forecast service",
            normalize_status(
                readiness.get(
                    "status"
                )
            ),
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
        st.metric(
            "Forecast rows",
            int(
                pipeline.get(
                    "forecast_row_count",
                    0,
                )
            ),
        )


def render_pipeline_details(
    *,
    pipeline: dict[str, Any],
    timezone_name: str,
) -> None:
    """Render pipeline execution details."""

    st.subheader(
        "Pipeline status"
    )

    details = {
        "Phase 5 status": normalize_status(
            pipeline.get(
                "phase_5_status"
            )
        ),
        "Phase 6 status": normalize_status(
            pipeline.get(
                "phase_6_status"
            )
        ),
        "Phase 5 run": pipeline.get(
            "phase_5_run_id",
            "Not available",
        ),
        "Phase 6 run": pipeline.get(
            "phase_6_run_id",
            "Not available",
        ),
        "Generated": format_timestamp(
            pipeline.get(
                "generated_at_utc"
            ),
            timezone_name=timezone_name,
        ),
        "Artifact consistency": (
            format_boolean_status(
                pipeline.get(
                    "artifact_consistency_passed"
                ),
                true_label="Passed",
                false_label="Failed",
            )
        ),
        "Forecast rows": pipeline.get(
            "forecast_row_count",
            0,
        ),
        "Active alert hours": pipeline.get(
            "active_alert_count",
            0,
        ),
        "Alert episodes": pipeline.get(
            "alert_episode_count",
            0,
        ),
    }

    display_df = pd.DataFrame(
    [
        {
            "Item": str(key),
            "Value": str(value),
        }
        for key, value in details.items()
    ]
    )

    display_df = display_df.astype(
        {
            "Item": "string",
            "Value": "string",
        }
    )

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
    )


def render_metadata(
    *,
    metadata: dict[str, Any],
) -> None:
    """Render public project and source metadata."""

    st.subheader(
        "Project metadata"
    )

    location = metadata.get(
        "location",
        {},
    )

    columns = st.columns(2)

    with columns[0]:
        st.markdown(
            "**Forecast coverage**"
        )

        st.write(
            f"**Location:** "
            f"{location.get('name', 'Not available')}"
        )

        st.write(
            f"**Coordinates:** "
            f"{location.get('latitude', '—')}, "
            f"{location.get('longitude', '—')}"
        )

        st.write(
            f"**Pollutant:** "
            f"{metadata.get('pollutant', 'PM2.5')}"
        )

        st.write(
            f"**Forecast horizon:** "
            f"{metadata.get('forecast_horizon_hours', 72)} hours"
        )

        st.write(
            f"**Timezone:** "
            f"{metadata.get('internal_timezone', 'UTC')}"
        )

    with columns[1]:
        st.markdown(
            "**Data and AQI configuration**"
        )

        st.write(
            f"**Pollution source:** "
            f"{metadata.get('pollution_source', 'OpenAQ')}"
        )

        weather_sources = metadata.get(
            "weather_sources",
            [],
        )

        st.write(
            "**Weather sources:** "
            + (
                ", ".join(weather_sources)
                if weather_sources
                else "Not available"
            )
        )

        st.write(
            f"**AQI standard:** "
            f"{metadata.get('aqi_standard_name', 'Not available')}"
        )

        st.write(
            f"**AQI version:** "
            f"{metadata.get('aqi_standard_version', 'Not available')}"
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

    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if latitude is None or longitude is None:
        st.info(
            "Reference-location coordinates are unavailable."
        )
        return

    latitude = float(latitude)
    longitude = float(longitude)

    location_name = str(
        location.get(
            "name",
            "Zafar Memon DHA",
        )
    )

    st.subheader("Reference location")

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
        f"Reference point: {location_name} "
        f"({latitude:.6f}, {longitude:.6f})"
    )