"""Technical transparency and production system status page."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from dashboard.components.states import (
    render_api_error,
)
from dashboard.components.system_status import (
    render_infrastructure,
    render_location_map,
    render_metadata,
    render_model_evaluation,
    render_model_strategy,
    render_operational_overview,
    render_pipeline_architecture,
    render_service_status_cards,
    render_system_hero,
    render_system_skeleton,
    render_training_evaluation_split,
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
from dashboard.utils.formatting import (
    format_timestamp,
    utc_now,
)


def _render_system_sidebar() -> str:
    """Render system-page controls and return timezone."""

    st.sidebar.html(
        """
        <div class="sidebar-section-label">
            OPERATIONS VIEW
        </div>

        <div class="sidebar-section-title">
            System controls
        </div>
        """
    )

    st.sidebar.caption(
        "Review production health and technical "
        "information in your preferred timezone."
    )

    timezone_label = (
        st.sidebar.selectbox(
            "Display timezone",
            options=list(
                SUPPORTED_TIMEZONES.keys()
            ),
            index=0,
            key="system_timezone",
        )
    )

    timezone_name = (
        SUPPORTED_TIMEZONES[
            timezone_label
        ]
    )

    st.sidebar.divider()

    refresh_clicked = (
        st.sidebar.button(
            "↻  Refresh status",
            help=(
                "Fetch the latest available "
                "production status."
            ),
            key="system_refresh",
            width="stretch",
        )
    )

    if refresh_clicked:
        clear_dashboard_api_cache()

        st.session_state[
            "last_system_refresh_utc"
        ] = utc_now()

        st.rerun()

    last_refresh = (
        st.session_state.get(
            "last_system_refresh_utc"
        )
    )

    if isinstance(
        last_refresh,
        datetime,
    ):
        st.sidebar.caption(
            "Manually refreshed "
            + format_timestamp(
                last_refresh,
                timezone_name=timezone_name,
            )
        )
    else:
        st.sidebar.caption(
            "Status data is cached briefly "
            "for responsive browsing."
        )

    return timezone_name


def _render_page_heading() -> None:
    """Render page heading consistent with Forecast and Alerts."""

    st.html(
        """
        <div class="section-kicker">
            OPERATIONS
        </div>

        <div>
            <h1 style="
                margin:0;
                font-size:2.15rem;
            ">
                System status
            </h1>

            <div style="
                color:#8d99aa;
                margin-top:0.35rem;
                font-size:0.92rem;
            ">
                Production health, model performance,
                pipeline activity, and technical transparency
            </div>
        </div>
        """
    )


def render_system_status_page() -> None:
    """Render the production technical transparency page."""

    apply_dashboard_theme()

    timezone_name = (
        _render_system_sidebar()
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

    _render_page_heading()

    st.markdown("")

    render_system_hero(
        liveness=liveness,
        readiness=readiness,
        pipeline=pipeline,
        timezone_name=timezone_name,
    )

    render_service_status_cards(
        liveness=liveness,
        readiness=readiness,
        pipeline=pipeline,
    )

    st.markdown("")

    (
        overview_tab,
        model_tab,
        pipelines_tab,
        infrastructure_tab,
    ) = st.tabs(
        [
            "Overview",
            "Model & Evaluation",
            "Pipelines",
            "Data & Infrastructure",
        ]
    )

    with overview_tab:
        st.markdown("")

        render_operational_overview(
            pipeline=pipeline,
            timezone_name=timezone_name,
        )

        st.divider()

        render_system_skeleton()

        limitations = (
            metadata.get(
                "known_limitations",
                [],
            )
        )

        if limitations:
            st.markdown("")

            with st.expander(
                "Technical notes",
                expanded=False,
            ):
                for limitation in limitations:
                    st.write(
                        f"- {limitation}"
                    )

    with model_tab:
        st.markdown("")

        render_model_strategy()

        st.divider()

        render_model_evaluation()

        st.divider()

        render_training_evaluation_split()

    with pipelines_tab:
        st.markdown("")

        render_pipeline_architecture(
            pipeline=pipeline,
            timezone_name=timezone_name,
        )

        st.divider()

        render_system_skeleton()

        with st.expander(
            "Pipeline interpretation",
            expanded=False,
        ):
            st.write(
                "**Feature synchronization** keeps "
                "the production feature datasets current."
            )

            st.write(
                "**Forecast publication** generates "
                "and validates the latest 72-hour output."
            )

            st.write(
                "**Retraining evaluation** compares "
                "challenger performance with the "
                "current production champion."
            )

            st.write(
                "**Production monitoring** records "
                "health snapshots and manages "
                "incident notification delivery."
            )

    with infrastructure_tab:
        st.markdown("")

        render_metadata(
            metadata=metadata,
        )

        st.divider()

        render_infrastructure()

        st.divider()

        render_location_map(
            metadata=metadata,
        )