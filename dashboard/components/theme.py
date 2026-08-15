"""Shared visual theme for the Streamlit dashboard."""

from __future__ import annotations

import streamlit as st


def apply_dashboard_theme() -> None:
    """Apply dashboard-wide presentation styling.

    Styling is deliberately limited to presentation concerns.
    It does not alter application or forecast behavior.
    """

    st.html(
        """
        <style>
        /* ---------------------------------------------------------
           App shell
        --------------------------------------------------------- */

        .stApp {
            background:
                radial-gradient(
                    circle at 55% -15%,
                    rgba(30, 64, 175, 0.08),
                    transparent 30rem
                ),
                #0b0f15;
        }

        .block-container {
            max-width: 1240px;
            padding-top: 2.3rem;
            padding-bottom: 4rem;
        }

        [data-testid="stSidebar"] {
            background: #111720;
            border-right: 1px solid rgba(148, 163, 184, 0.10);
        }

        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1.2rem;
        }

        /* ---------------------------------------------------------
           Reduce Streamlit product chrome
        --------------------------------------------------------- */

        [data-testid="stAppDeployButton"] {
            display: none;
        }

        #MainMenu {
            visibility: hidden;
        }

        footer {
            visibility: hidden;
        }

        /* Keep header available for layout but unobtrusive. */
        header[data-testid="stHeader"] {
            background: transparent;
        }

        /* ---------------------------------------------------------
           Typography
        --------------------------------------------------------- */

        h1,
        h2,
        h3 {
            letter-spacing: -0.025em;
        }

        h1 {
            font-weight: 700 !important;
        }

        h2 {
            font-weight: 650 !important;
        }

        h3 {
            font-weight: 600 !important;
        }

        p,
        label,
        [data-testid="stCaptionContainer"] {
            line-height: 1.55;
        }

        [data-testid="stCaptionContainer"] {
            color: #8d99aa;
        }

        /* ---------------------------------------------------------
           Metric cards
        --------------------------------------------------------- */

        [data-testid="stMetric"] {
            background:
                linear-gradient(
                    145deg,
                    rgba(255, 255, 255, 0.032),
                    rgba(255, 255, 255, 0.012)
                );
            border: 1px solid rgba(148, 163, 184, 0.13);
            border-radius: 15px;
            padding: 1.05rem 1.1rem;
            min-height: 112px;
            transition:
                border-color 160ms ease,
                transform 160ms ease;
        }

        [data-testid="stMetric"]:hover {
            border-color: rgba(96, 165, 250, 0.25);
            transform: translateY(-1px);
        }

        [data-testid="stMetricLabel"] {
            color: #98a4b5;
            font-size: 0.78rem;
            font-weight: 500;
        }

        [data-testid="stMetricValue"] {
            font-weight: 650;
            letter-spacing: -0.025em;
        }

        /* ---------------------------------------------------------
           Hero
        --------------------------------------------------------- */

        .aqi-hero {
            position: relative;
            overflow: hidden;
            padding: 1.55rem 1.65rem;
            margin: 0.75rem 0 1.05rem 0;
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            background:
                linear-gradient(
                    135deg,
                    rgba(30, 41, 59, 0.82),
                    rgba(13, 18, 27, 0.94)
                );
        }

        .aqi-hero::after {
            content: "";
            position: absolute;
            width: 260px;
            height: 260px;
            right: -110px;
            top: -150px;
            background: var(--hero-accent, #38bdf8);
            filter: blur(90px);
            opacity: 0.13;
            border-radius: 999px;
            pointer-events: none;
        }

        .aqi-hero-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }

        .aqi-hero-eyebrow {
            color: #8d99aa;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.095em;
            font-weight: 650;
            margin-bottom: 0.35rem;
        }

        .aqi-hero-title {
            color: #f8fafc;
            font-size: 1.35rem;
            font-weight: 650;
            margin: 0;
        }

        .aqi-live-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            padding: 0.34rem 0.65rem;
            border: 1px solid rgba(74, 222, 128, 0.22);
            border-radius: 999px;
            background: rgba(22, 163, 74, 0.10);
            color: #86efac;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            white-space: nowrap;
        }

        .aqi-live-dot {
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: #4ade80;
            box-shadow: 0 0 0 4px rgba(74, 222, 128, 0.10);
        }

        .aqi-hero-main {
            display: flex;
            align-items: flex-end;
            gap: 1rem;
            margin-top: 1.35rem;
        }

        .aqi-value {
            color: #ffffff;
            font-size: 3.25rem;
            line-height: 0.95;
            font-weight: 720;
            letter-spacing: -0.055em;
        }

        .aqi-value-label {
            color: #94a3b8;
            font-size: 0.78rem;
            margin-top: 0.4rem;
        }

        .aqi-category {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.42rem 0.72rem;
            margin-bottom: 0.15rem;
            font-size: 0.76rem;
            font-weight: 700;
            color: var(--category-color, #4ade80);
            border: 1px solid color-mix(
                in srgb,
                var(--category-color, #4ade80) 28%,
                transparent
            );
            background: color-mix(
                in srgb,
                var(--category-color, #4ade80) 10%,
                transparent
            );
        }

        .aqi-hero-message {
            color: #c5ced9;
            max-width: 620px;
            margin-top: 1rem;
            margin-bottom: 0;
            font-size: 0.93rem;
        }

        /* ---------------------------------------------------------
           Status strip
        --------------------------------------------------------- */

        .status-strip {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin: 0 0 1.25rem 0;
        }

        .status-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.44rem 0.68rem;
            border-radius: 999px;
            border: 1px solid rgba(148, 163, 184, 0.12);
            background: rgba(255, 255, 255, 0.025);
            color: #aeb8c7;
            font-size: 0.76rem;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 999px;
            background: #60a5fa;
        }

        .status-dot.success {
            background: #4ade80;
        }

        /* ---------------------------------------------------------
           Section headings
        --------------------------------------------------------- */

        .section-kicker {
            color: #60a5fa;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }

        .section-title {
            color: #f8fafc;
            font-size: 1.35rem;
            font-weight: 650;
            letter-spacing: -0.025em;
            margin-bottom: 0.2rem;
        }

        .section-description {
            color: #8d99aa;
            font-size: 0.86rem;
            margin-bottom: 1rem;
        }

        /* ---------------------------------------------------------
           Plotly containers
        --------------------------------------------------------- */

        [data-testid="stPlotlyChart"] {
            border: 1px solid rgba(148, 163, 184, 0.11);
            border-radius: 16px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.012);
            padding: 0.2rem;
        }

        /* ---------------------------------------------------------
           Tabs
        --------------------------------------------------------- */

        button[data-baseweb="tab"] {
            padding-left: 0.95rem;
            padding-right: 0.95rem;
            color: #8d99aa;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: #f8fafc;
        }

        [data-baseweb="tab-highlight"] {
            background-color: #60a5fa;
        }

        /* ---------------------------------------------------------
           Inputs
        --------------------------------------------------------- */

        [data-baseweb="select"] > div,
        [data-testid="stSelectbox"] > div > div,
        [data-testid="stMultiSelect"] > div > div {
            border-radius: 10px;
        }

        [data-testid="stSidebar"] button {
            border-radius: 10px;
        }

        /* ---------------------------------------------------------
        Sidebar refinement
        --------------------------------------------------------- */

        [data-testid="stSidebar"] {
            background:
                linear-gradient(
                    180deg,
                    #111720 0%,
                    #10161f 100%
                );
        }

        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.7rem;
        }

        .sidebar-section-label {
            color: #60a5fa;
            font-size: 0.67rem;
            font-weight: 700;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            margin-bottom: 0.18rem;
        }

        .sidebar-section-title {
            color: #f1f5f9;
            font-size: 1.05rem;
            font-weight: 650;
            letter-spacing: -0.015em;
            margin-bottom: 0.1rem;
        }

        [data-testid="stSidebar"] label {
            color: #cbd5e1;
            font-size: 0.79rem;
            font-weight: 500;
        }

        /* Make sidebar inputs quieter than primary content. */

        [data-testid="stSidebar"] [data-baseweb="select"] > div {
            min-height: 2.45rem;
            background: rgba(5, 10, 17, 0.58);
            border-color: rgba(148, 163, 184, 0.10);
        }

        [data-testid="stSidebar"] [data-baseweb="select"] > div:hover {
            border-color: rgba(96, 165, 250, 0.24);
        }

        /* Advanced filter container */

        [data-testid="stSidebar"] [data-testid="stExpander"] {
            border: 1px solid rgba(148, 163, 184, 0.10);
            border-radius: 11px;
            background: rgba(255, 255, 255, 0.012);
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] summary {
            font-size: 0.82rem;
            color: #cbd5e1;
        }

        /* Secondary refresh action */

        [data-testid="stSidebar"] .stButton > button {
            background: transparent;
            border: 1px solid rgba(148, 163, 184, 0.18);
            color: #cbd5e1;
            min-height: 2.45rem;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(96, 165, 250, 0.07);
            border-color: rgba(96, 165, 250, 0.30);
            color: #f8fafc;
        }

        /* Sidebar captions should remain secondary. */

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: #64748b;
            font-size: 0.74rem;
        }

        /* ---------------------------------------------------------
           Alerts / messages
        --------------------------------------------------------- */

        [data-testid="stAlert"] {
            border-radius: 13px;
        }

        /* ---------------------------------------------------------
           Divider
        --------------------------------------------------------- */

        hr {
            border-color: rgba(148, 163, 184, 0.10) !important;
        }

        /* ---------------------------------------------------------
           Dataframe
        --------------------------------------------------------- */

        [data-testid="stDataFrame"] {
            border: 1px solid rgba(148, 163, 184, 0.11);
            border-radius: 14px;
            overflow: hidden;
        }

        /* ---------------------------------------------------------
        Alert hero
        --------------------------------------------------------- */

        .alert-hero {
            position: relative;
            overflow: hidden;
            padding: 1.55rem 1.65rem;
            margin: 0.75rem 0 1.05rem 0;
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            background:
                linear-gradient(
                    135deg,
                    rgba(30, 41, 59, 0.82),
                    rgba(13, 18, 27, 0.94)
                );
        }

        .alert-hero::after {
            content: "";
            position: absolute;
            width: 270px;
            height: 270px;
            right: -110px;
            top: -150px;
            background: var(--alert-accent, #4ade80);
            filter: blur(95px);
            opacity: 0.13;
            border-radius: 999px;
            pointer-events: none;
        }

        .alert-hero-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }

        .alert-hero-title {
            color: #f8fafc;
            font-size: 1.35rem;
            font-weight: 650;
            letter-spacing: -0.025em;
        }

        .alert-state-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            padding: 0.34rem 0.65rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            white-space: nowrap;
        }

        .alert-state-pill.normal {
            color: #86efac;
            border: 1px solid rgba(74, 222, 128, 0.22);
            background: rgba(22, 163, 74, 0.10);
        }

        .alert-state-pill.warning {
            color: #fde68a;
            border: 1px solid rgba(250, 204, 21, 0.25);
            background: rgba(202, 138, 4, 0.10);
        }

        .alert-state-pill.danger {
            color: #fca5a5;
            border: 1px solid rgba(248, 113, 113, 0.25);
            background: rgba(220, 38, 38, 0.10);
        }

        .alert-state-dot {
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: currentColor;
            box-shadow:
                0 0 0 4px
                color-mix(
                    in srgb,
                    currentColor 10%,
                    transparent
                );
        }

        .alert-hero-main {
            display: flex;
            align-items: flex-end;
            gap: 1rem;
            margin-top: 1.35rem;
        }

        .alert-main-value {
            color: #ffffff;
            font-size: 3rem;
            line-height: 0.95;
            font-weight: 720;
            letter-spacing: -0.05em;
        }

        .alert-main-label {
            color: #94a3b8;
            font-size: 0.78rem;
            margin-top: 0.42rem;
        }

        .alert-category-pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.42rem 0.72rem;
            margin-bottom: 0.1rem;
            font-size: 0.76rem;
            font-weight: 700;
            color: var(--category-color, #4ade80);
            border:
                1px solid
                color-mix(
                    in srgb,
                    var(--category-color, #4ade80) 28%,
                    transparent
                );
            background:
                color-mix(
                    in srgb,
                    var(--category-color, #4ade80) 9%,
                    transparent
                );
        }

        .alert-hero-message {
            color: #c5ced9;
            max-width: 690px;
            margin-top: 1rem;
            margin-bottom: 0;
            font-size: 0.93rem;
        }


        /* ---------------------------------------------------------
        No-alert state
        --------------------------------------------------------- */

        .alert-empty-state {
            display: flex;
            align-items: flex-start;
            gap: 1rem;
            padding: 1.25rem 1.3rem;
            border-radius: 15px;
            border: 1px solid rgba(148, 163, 184, 0.12);
            background: rgba(255, 255, 255, 0.018);
        }

        .alert-empty-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 34px;
            width: 34px;
            height: 34px;
            border-radius: 999px;
            color: #86efac;
            border: 1px solid rgba(74, 222, 128, 0.20);
            background: rgba(22, 163, 74, 0.08);
            font-size: 0.85rem;
            font-weight: 700;
        }

        .alert-empty-title {
            color: #e5e7eb;
            font-size: 0.94rem;
            font-weight: 600;
            margin-bottom: 0.28rem;
        }

        .alert-empty-description {
            color: #8d99aa;
            font-size: 0.82rem;
            max-width: 650px;
            line-height: 1.55;
        }


        /* ---------------------------------------------------------
        Alert episodes
        --------------------------------------------------------- */

        .episode-heading {
            display: flex;
            align-items: stretch;
            gap: 0.8rem;
            margin-bottom: 0.85rem;
        }

        .episode-accent {
            width: 3px;
            border-radius: 999px;
            background: var(--episode-accent, #60a5fa);
        }

        .episode-kicker {
            color: var(--episode-accent, #60a5fa);
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }

        .episode-title {
            color: #f8fafc;
            font-size: 1.12rem;
            font-weight: 650;
            margin-top: 0.12rem;
        }

        .episode-status-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin: 0.8rem 0 1rem 0;
        }

        .episode-status-badge {
            border-radius: 999px;
            padding: 0.3rem 0.55rem;
            border: 1px solid rgba(148, 163, 184, 0.14);
            background: rgba(255, 255, 255, 0.025);
            color: #aeb8c7;
            font-size: 0.72rem;
        }


        /* ---------------------------------------------------------
        AQI guide
        --------------------------------------------------------- */

        .aqi-guide-card {
            min-height: 150px;
            padding: 1rem;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-top: 2px solid var(--guide-color, #60a5fa);
            background:
                linear-gradient(
                    145deg,
                    color-mix(
                        in srgb,
                        var(--guide-color, #60a5fa) 5%,
                        transparent
                    ),
                    rgba(255, 255, 255, 0.012)
                );
        }

        .aqi-guide-range {
            color: var(--guide-color, #60a5fa);
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.05em;
        }

        .aqi-guide-category {
            color: #f8fafc;
            font-size: 0.94rem;
            font-weight: 650;
            margin-top: 0.45rem;
            line-height: 1.25;
        }

        .aqi-guide-description {
            color: #8d99aa;
            font-size: 0.77rem;
            line-height: 1.5;
            margin-top: 0.55rem;
        }


        /* ---------------------------------------------------------
        AQI explainers
        --------------------------------------------------------- */

        .aqi-explainer-card {
            height: 100%;
            padding: 1.15rem 1.2rem;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.12);
            background: rgba(255, 255, 255, 0.018);
        }

        .aqi-explainer-label {
            color: #60a5fa;
            font-size: 0.67rem;
            font-weight: 700;
            letter-spacing: 0.09em;
        }

        .aqi-explainer-title {
            color: #f8fafc;
            font-size: 1rem;
            font-weight: 650;
            margin-top: 0.42rem;
        }

        .aqi-explainer-body {
            color: #8d99aa;
            font-size: 0.81rem;
            line-height: 1.55;
            margin-top: 0.55rem;
        }


        /* ---------------------------------------------------------
        Alert methodology
        --------------------------------------------------------- */

        .method-step {
            display: grid;
            grid-template-columns: 42px 1fr;
            gap: 0.85rem;
            padding: 0.9rem 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
        }

        .method-step:last-child {
            border-bottom: 0;
        }

        .method-step-number {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 34px;
            height: 34px;
            border-radius: 10px;
            background: rgba(96, 165, 250, 0.08);
            border: 1px solid rgba(96, 165, 250, 0.16);
            color: #60a5fa;
            font-size: 0.7rem;
            font-weight: 700;
        }

        .method-step-title {
            color: #f1f5f9;
            font-size: 0.9rem;
            font-weight: 600;
        }

        .method-step-description {
            color: #8d99aa;
            font-size: 0.8rem;
            line-height: 1.55;
            margin-top: 0.2rem;
        }

        /* ---------------------------------------------------------
           Responsive hero
        --------------------------------------------------------- */

        @media (max-width: 760px) {
            .block-container {
                padding-top: 1.5rem;
            }

            .aqi-hero {
                padding: 1.2rem;
            }

            .aqi-value {
                font-size: 2.65rem;
            }

            .aqi-hero-top {
                flex-direction: column;
            }

            .alert-hero {
                padding: 1.2rem;
            }

            .alert-hero-top {
                flex-direction: column;
            }

            .alert-main-value {
                font-size: 2.55rem;
            }

            .aqi-guide-card {
                min-height: auto;
            }
        }
        </style>
        """
    )
