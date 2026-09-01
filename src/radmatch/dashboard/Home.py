#!/usr/bin/env python3
"""Landing page for the RadMatch Evaluation Dashboard."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from radmatch.dashboard.common import shared
from radmatch.dashboard.common.constants import (
    CONFIG_REPORTS_GT_PATH,
    CONFIG_REPORTS_PRED_PATH,
    CONFIG_RESULTS_PATH,
    QUERY_PARAM_REPORTS_GT,
    QUERY_PARAM_REPORTS_PRED,
    QUERY_PARAM_RESULTS,
)


def _seed_session_state_from_query_params() -> None:
    """Copy query parameters into session state so they survive st.switch_page() navigation."""
    params = st.query_params
    for param, config_key in (
        (QUERY_PARAM_RESULTS, CONFIG_RESULTS_PATH),
        (QUERY_PARAM_REPORTS_GT, CONFIG_REPORTS_GT_PATH),
        (QUERY_PARAM_REPORTS_PRED, CONFIG_REPORTS_PRED_PATH),
    ):
        value = params.get(param)
        if value and config_key not in st.session_state:
            st.session_state[config_key] = value


def main() -> None:
    """Main entry point for dashboard home page."""
    _seed_session_state_from_query_params()
    shared.set_base_page_config("RadMatch Evaluation Dashboard")
    shared.inject_styles()

    st.title("RadMatch Evaluation Dashboard")
    st.caption("Inspect the findings, matches and attribute errors behind a RadMatch score")

    st.write(
        "RadMatch scores a report by extracting its findings, matching them against the "
        "ground truth, and judging each matched pair on seven attribute dimensions. Every "
        "step is recorded, so a score is never a black box — this dashboard reads those "
        "records back. Start from the dataset-level numbers, then drill into the individual "
        "report, finding pair and attribute error that produced them."
    )

    st.markdown("<style>.stButton>button { height: 80px; font-weight: 600; }</style>", unsafe_allow_html=True)
    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

    st.markdown("### Pages")
    shared.render_hero_row(
        "🔎",
        "Results Explorer",
        "Per-report drill-down: ground-truth and predicted findings side by side, coloured "
        "by match outcome, with the attribute errors and judge reasoning behind each pair.",
        "pages/1-Results_Explorer.py",
        "open_re",
    )
    shared.render_hero_row(
        "📊",
        "Performance Summary",
        "Dataset-level view: actionable errors, safety precision and recall, the match-outcome "
        "breakdown, and the same metrics per finding subset.",
        "pages/2-Performance_Summary.py",
        "open_ss",
    )

    st.markdown("---")

    results_dir = st.session_state.get(CONFIG_RESULTS_PATH, "")
    if results_dir:
        st.caption(f"Results directory: `{Path(results_dir).expanduser().resolve()}`")


if __name__ == "__main__":
    main()
