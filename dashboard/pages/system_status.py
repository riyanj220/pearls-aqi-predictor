"""Technical system status dashboard page."""

from __future__ import annotations

import streamlit as st

from dashboard.components.states import (
    render_api_error,
)
from dashboard.components.system_status import (
    render_location_map,
    render_metadata,
    render_pipeline_details,
    render_service_status_cards,
)
from dashboard.components.theme import (
    apply_dashboard_theme,
)
from dashboard.services.api_client import (
    DashboardAPIError,
    cached_liveness,
    cached_metadata,
    cached_pipeline_status,
    cached_readiness,
    clear_dashboard_api_cache,
)
from dashboard.utils.constants import (
    SUPPORTED_TIMEZONES,
)


def render_system_status_page() -> None:
    """Render service, pipeline, and metadata status."""

    apply_dashboard_theme()

    st.markdown(
        """
        <div class="section-kicker">
            Operations
        </div>
        <div class="section-title">
            System status
        </div>
        <div class="section-description">
            Operational health of the API,
            forecast pipeline, artifacts, and
            source configuration.
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            "### System controls"
        )

        timezone_label = st.selectbox(
            "Display timezone",
            options=list(
                SUPPORTED_TIMEZONES.keys()
            ),
            index=0,
            key="system_timezone",
        )

        st.divider()

        if st.button(
            "↻ Refresh status",
            width="stretch",
        ):
            clear_dashboard_api_cache()
            st.rerun()

    timezone_name = (
        SUPPORTED_TIMEZONES[
            timezone_label
        ]
    )

    try:
        with st.spinner(
            "Loading system status..."
        ):
            liveness = (
                cached_liveness()
            )

            readiness = (
                cached_readiness()
            )

            pipeline = (
                cached_pipeline_status()
            )

            metadata = (
                cached_metadata()
            )

    except DashboardAPIError as error:
        render_api_error(error)
        return

    render_service_status_cards(
        liveness=liveness,
        readiness=readiness,
        pipeline=pipeline,
    )

    st.divider()

    render_pipeline_details(
        pipeline=pipeline,
        timezone_name=timezone_name,
    )

    st.divider()

    render_metadata(
        metadata=metadata,
    )

    st.divider()

    render_location_map(
        metadata=metadata,
    )

    limitations = metadata.get(
        "known_limitations",
        [],
    )

    if limitations:
        with st.expander(
            "Technical notes",
            expanded=False,
        ):
            for limitation in limitations:
                st.write(
                    f"- {limitation}"
                )