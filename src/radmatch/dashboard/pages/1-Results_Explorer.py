#!/usr/bin/env python3
"""Results Explorer — per-report drill-down for RadMatch."""

from __future__ import annotations

import html
import random
from typing import TYPE_CHECKING

import streamlit as st

from radmatch import constants as radmatch_constants
from radmatch.dashboard.common import match_details, shared
from radmatch.scoring import metrics

if TYPE_CHECKING:
    import pandas as pd
    from streamlit.delta_generator import DeltaGenerator


def _render_selection_box(report_ids: list[str]) -> str:
    """Bordered 'Selection' container with a report selectbox + prev/next/random
    navigation buttons."""
    with st.container(border=True):
        st.markdown("##### Selection")
        sel_col, btn_col = st.columns([5.2, 2.4])
        # Pin the current selection through reruns; if it dropped out of the
        # filtered list (e.g. filter narrowed), fall back to the first option.
        current = st.session_state.get("report_select")
        if current not in report_ids:
            st.session_state["report_select"] = report_ids[0]
            current = report_ids[0]
        current_idx = report_ids.index(current)
        with btn_col:
            st.markdown("<div style='height:1.8rem;'></div>", unsafe_allow_html=True)
            b_prev, b_next, b_rand = st.columns(3, gap="small")
            with b_prev:
                if st.button("←", width="stretch", disabled=current_idx <= 0, type="primary"):
                    st.session_state["report_select"] = report_ids[max(0, current_idx - 1)]
                    st.rerun()
            with b_next:
                if st.button("→", width="stretch", disabled=current_idx >= len(report_ids) - 1, type="primary"):
                    st.session_state["report_select"] = report_ids[min(len(report_ids) - 1, current_idx + 1)]
                    st.rerun()
            with b_rand:
                if st.button("🎲", width="stretch"):
                    st.session_state["report_select"] = random.choice(report_ids)
                    st.rerun()
        with sel_col:
            return st.selectbox("Report", options=report_ids, key="report_select")


_CLINICAL_SIGNIFICANCE_OPTIONS = ["critical", "urgent", "notable", "routine"]
_MEASUREMENT_OPTIONS = ["size", "count", "attenuation", "ratio", "other"]
_COMPARISON_OPTIONS = ["stable", "improving", "worsening", "new", "resolved"]


def _filter_panel(
    index_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame | None, str, DeltaGenerator, int]:
    """Filters expander.

    Returns (filtered_df_or_None, search_query, count_placeholder, total). The caller
    fills the placeholder once the free-text query has run, since that needs the JSON
    files loaded.
    """
    with st.expander("Filters", expanded=True):
        # Row 0: report count aligned top-right (filled by caller after text search).
        count_placeholder = st.empty()
        # Row 1: free-text search across GT + Pred findings.
        search_query = st.text_input(
            "Search text within GT or Pred findings",
            placeholder="e.g. pneumothorax, left lower lobe, 12 mm nodule",
            key="text_search",
        )

        if index_df is None or index_df.empty:
            return index_df, search_query, count_placeholder, 0

        # Row 2: clinical_significance / measurement_type / comparison.
        col_sig, col_meas, col_comp = st.columns(3)
        with col_sig:
            significance_filters = st.multiselect(
                "Clinical significance",
                options=_CLINICAL_SIGNIFICANCE_OPTIONS,
                key="filter_clinical_significance",
            )
        with col_meas:
            measurement_filters = st.multiselect(
                "Measurement type",
                options=_MEASUREMENT_OPTIONS,
                key="filter_measurement_type",
            )
        with col_comp:
            comparison_filters = st.multiselect(
                "Comparison",
                options=_COMPARISON_OPTIONS,
                key="filter_comparison",
            )

        # Row 3: match outcomes / match scope / actionable errors.
        col_outcome, col_scope, col_err = st.columns(3)
        with col_outcome:
            outcome_filters = st.multiselect(
                "Match outcomes",
                options=list(radmatch_constants.MUC_CATEGORIES),
                key="filter_has_outcome",
            )
        with col_scope:
            scope_filters = st.multiselect(
                "Match scope",
                options=list(radmatch_constants.MATCH_SCOPE_VALUES),
                key="filter_match_scope",
            )
        with col_err:
            max_err = int(index_df["actionable_errors"].max()) if "actionable_errors" in index_df.columns else 0
            err_range = st.slider(
                "Actionable errors",
                0,
                max(max_err, 1),
                (0, max(max_err, 1)),
                step=1,
                key="actionable_err_range",
            )

    df = index_df.copy()
    # Every selected box must be satisfied: `critical` + `urgent` requires a report
    # with at least one of each. Uniform across all the multiselect filters.
    if significance_filters and "clinical_significances" in df.columns:
        df = df[df["clinical_significances"].apply(lambda lst: _all_present(lst, significance_filters))]
    if measurement_filters:
        df = df[df["measurement_types"].apply(lambda lst: _all_present(lst, measurement_filters))]
    if comparison_filters:
        df = df[df["comparisons"].apply(lambda lst: _all_present(lst, comparison_filters))]
    if outcome_filters:
        outcome_cols = [f"muc_{cat.lower()}" for cat in outcome_filters]
        df = df[df[outcome_cols].gt(0).all(axis=1)]
    if scope_filters and "match_scopes" in df.columns:
        df = df[df["match_scopes"].apply(lambda lst: _all_present(lst, scope_filters))]
    df = df[(df["actionable_errors"] >= err_range[0]) & (df["actionable_errors"] <= err_range[1])]
    df = df.sort_values("report_id")

    return df, search_query, count_placeholder, len(index_df)


def _all_present(values: object, selected: list[str]) -> bool:
    """True if every item in `selected` appears in `values`, a list-like parquet cell.
    pyarrow round-trips list<string> as numpy arrays, so coerce before comparing.
    """
    if values is None:
        return False
    return set(selected).issubset(set(map(str, values)))


def _filter_by_finding_text(state: shared.DashboardState, report_ids: list[str], query: str) -> list[str]:
    """Keep only series whose GT or Pred findings contain the case-insensitive substring.

    Matches if the query is found on either side. Uses the
    `@st.cache_data`-memoised `shared.load_findings`, so successive keystrokes
    on the same dataset only pay the disk read once per report.
    """
    q = query.lower().strip()
    if not q:
        return report_ids
    if state.findings_gt_dir is None and state.findings_pred_dir is None:
        return report_ids

    def _has_match(side_dir, rid):
        if side_dir is None:
            return False
        findings = shared.load_findings(str(side_dir / f"{rid}.json"))
        return any(q in str(f.get("text", "")).lower() for f in findings)

    return [
        rid for rid in report_ids if _has_match(state.findings_gt_dir, rid) or _has_match(state.findings_pred_dir, rid)
    ]


def _per_report_metric_cards(per_report: dict[str, object]) -> None:
    """Headline cards for the selected pair: actionable errors, then actionable and
    triage precision/recall, each with a `numerator / denominator` subtitle.
    """
    safety = per_report.get("clinical_safety_summary") or {}
    actionable_errors = per_report.get("actionable_errors_total")

    row1 = st.columns(3)
    row1[0].markdown(
        shared.render_metric_card(
            "Actionable errors",
            shared.format_int(int(actionable_errors)) if actionable_errors is not None else "—",
            card_class="f1-metric-card",
        ),
        unsafe_allow_html=True,
    )
    row1[1].markdown(
        shared.render_metric_card(
            "Actionable Precision",
            shared.format_precision_metric(safety, "actionable"),
            card_class="safety-metric-card",
            subtitle=shared.format_precision_subtitle(safety, "actionable"),
        ),
        unsafe_allow_html=True,
    )
    row1[2].markdown(
        shared.render_metric_card(
            "Actionable Recall",
            shared.format_recall_metric(safety, "actionable"),
            card_class="safety-metric-card",
            subtitle=shared.format_recall_subtitle(safety, "actionable"),
        ),
        unsafe_allow_html=True,
    )

    row2 = st.columns(3)
    row2[0].markdown(
        shared.render_metric_card(
            "Triage Precision",
            shared.format_precision_metric(safety, "triage"),
            card_class="safety-metric-card",
            subtitle=shared.format_precision_subtitle(safety, "triage"),
        ),
        unsafe_allow_html=True,
    )
    row2[1].markdown(
        shared.render_metric_card(
            "Triage Recall",
            shared.format_recall_metric(safety, "triage"),
            card_class="safety-metric-card",
            subtitle=shared.format_recall_subtitle(safety, "triage"),
        ),
        unsafe_allow_html=True,
    )


_SELECT_KEY_ID = "selected_finding_id"
_SELECT_KEY_IS_GT = "selected_finding_is_gt"
_SELECT_KEY_SAME_SIDE = "selected_highlight_same_side"  # list[str] — selected + same-side siblings
_SELECT_KEY_OTHER_SIDE = "selected_highlight_other_side"  # list[str] — selected's counterparts


def _clear_selection() -> None:
    for k in (_SELECT_KEY_ID, _SELECT_KEY_IS_GT, _SELECT_KEY_SAME_SIDE, _SELECT_KEY_OTHER_SIDE):
        st.session_state.pop(k, None)


def _highlight_sets_for_selection(
    selected_id: str,
    same_side_idx: dict[str, shared.PerPairMatchInfo],
    other_side_idx: dict[str, shared.PerPairMatchInfo],
) -> tuple[list[str], list[str]]:
    """Two-hop walk: selected → counterparts → siblings (same-side findings
    that share a counterpart). Used for sibling-aware highlighting."""
    info = same_side_idx.get(selected_id)
    if info is None:
        return [selected_id], []
    other_side_ids = [c.counterpart_id for c in info.counterparts]
    same_side: set[str] = {selected_id}
    for cp_id in other_side_ids:
        cp_info = other_side_idx.get(cp_id)
        if cp_info is None:
            continue
        same_side.update(c.counterpart_id for c in cp_info.counterparts)
    return sorted(same_side), other_side_ids


_SUBSET_FILTER_OPTIONS = ["all", "abnormal-regular", "normal-regular", "measurement", "comparison"]
_ERRORS_FILTER_OPTIONS = ["all", "actionable", "triage"]
_TRIAGE_TIERS = frozenset(radmatch_constants.TRIAGE_SIGNIFICANCE_TIERS)
_ACTIONABLE_TIERS = frozenset(radmatch_constants.ACTIONABLE_SIGNIFICANCE_TIERS)


def _matches_subset(finding: dict[str, object], subset: str) -> bool:
    """Subset membership, delegated to the authoritative `metrics.assign_subsets`
    so the dashboard filter never drifts from how scoring assigns subsets."""
    if subset == "all":
        return True
    return subset in metrics.assign_subsets(finding)


def _matches_errors(
    finding: dict[str, object],
    info: shared.PerPairMatchInfo,
    errors_filter: str,
    counterpart_findings: dict[str, dict[str, object]] | None = None,
) -> bool:
    """Keep findings whose effective match is an error at the chosen tier.

    Matched INC needs *either* side's significance to align with
    `compute_actionable_errors` — a status inversion is actionable whichever side
    carries the higher tier. Without `counterpart_findings` only this side is
    checked, which is enough for MIS and SPU but can hide half of an INC pair.
    """
    if errors_filter == "all":
        return True
    pool = _ACTIONABLE_TIERS if errors_filter == "actionable" else _TRIAGE_TIERS
    # MIS / SPU contribute to actionable_errors via the orphan side; the finding
    # itself has the significance to check.
    if info.category in ("MIS", "SPU"):
        return finding.get("clinical_significance") in pool
    # `info.category` is best-of-pairs, so a COR finding can still hold a per-pair
    # INC on an actionable counterpart. Check each pair individually.
    side_in_pool = finding.get("clinical_significance") in pool
    for cp in info.counterparts:
        if cp.category != "INC":
            continue
        if side_in_pool:
            return True
        if counterpart_findings is not None:
            counterpart = counterpart_findings.get(cp.counterpart_id)
            if counterpart is not None and counterpart.get("clinical_significance") in pool:
                return True
    return False


def _render_finding_column(
    findings: list[dict[str, object]],
    match_idx: dict[str, shared.PerPairMatchInfo],
    title: str,
    is_gt: bool,
    counterpart_match_idx: dict[str, shared.PerPairMatchInfo],
    errors_filter: str = "all",
    subset_filter: str = "all",
    counterpart_findings: dict[str, dict[str, object]] | None = None,
) -> None:
    """Left or right column of finding cards. Checking a row stores the
    (finding_id, is_gt, same/other highlight sets) in session state, which
    fades all non-highlighted cards across both columns. `errors_filter` and
    `subset_filter` add additional greying."""
    st.markdown(
        f"<div class='gt-pred-header'><b>{title}</b> "
        f"<span style='color:#6b7280;font-size:0.85rem;'>({len(findings)} findings)</span></div>",
        unsafe_allow_html=True,
    )
    if not findings:
        st.caption("(none)")
        return

    sel_id = st.session_state.get(_SELECT_KEY_ID)
    sel_is_gt = st.session_state.get(_SELECT_KEY_IS_GT)
    same_side_set = frozenset(st.session_state.get(_SELECT_KEY_SAME_SIDE) or [])
    other_side_set = frozenset(st.session_state.get(_SELECT_KEY_OTHER_SIDE) or [])
    has_selection = sel_id is not None

    for f in findings:
        fid = f.get("finding_id", "")
        info = match_idx.get(fid, shared.PerPairMatchInfo("MIS" if is_gt else "SPU", []))
        if not has_selection:
            highlighted = False
        elif is_gt == sel_is_gt:
            highlighted = fid in same_side_set
        else:
            highlighted = fid in other_side_set
        out_of_scope = not _matches_subset(f, subset_filter) or not _matches_errors(
            f, info, errors_filter, counterpart_findings=counterpart_findings
        )
        is_greyed = (has_selection and not highlighted) or out_of_scope

        chk_col, card_col = st.columns([0.05, 0.95], gap="small")
        with chk_col:
            chk_key = f"chk_{'gt' if is_gt else 'pred'}_{fid}"
            is_the_selected = fid == sel_id and is_gt == sel_is_gt
            if has_selection and not is_the_selected:
                glyph = "☑" if highlighted else "☐"
                color = "#9ca3af" if is_greyed else "#374151"
                st.markdown(
                    f"<div style='color:{color};font-size:1.2rem;padding-top:0.4rem;text-align:center;'>{glyph}</div>",
                    unsafe_allow_html=True,
                )
            else:
                checked = st.checkbox("Select", value=highlighted, key=chk_key, label_visibility="collapsed")
                if is_the_selected and not checked:
                    _clear_selection()
                    st.rerun()
                elif not has_selection and checked:
                    same_side, other_side = _highlight_sets_for_selection(fid, match_idx, counterpart_match_idx)
                    st.session_state[_SELECT_KEY_ID] = fid
                    st.session_state[_SELECT_KEY_IS_GT] = is_gt
                    st.session_state[_SELECT_KEY_SAME_SIDE] = same_side
                    st.session_state[_SELECT_KEY_OTHER_SIDE] = other_side
                    st.rerun()
        with card_col:
            st.markdown(
                shared.render_finding_card(f, info, is_gt=is_gt, is_greyed=is_greyed),
                unsafe_allow_html=True,
            )


def _render_reports_tab(state: shared.DashboardState, report_id: str) -> None:
    """Indication block (when present) on top, then side-by-side raw GT vs Pred text reports."""
    gt_text = shared.load_report_text(str(state.reports_gt_dir) if state.reports_gt_dir else None, report_id)
    pred_text = shared.load_report_text(str(state.reports_pred_dir) if state.reports_pred_dir else None, report_id)
    indication_text = shared.load_report_text(str(state.indications_dir) if state.indications_dir else None, report_id)
    if not (gt_text or pred_text or indication_text):
        st.info(
            "No raw report texts available. Provide reports_gt/reports_pred sidebar overrides "
            "or run radmatch with --reports-gt / --reports-pred."
        )
        return
    # Reports routinely contain `<` / `>` (e.g. "<1.5 cm" thresholds). Escape
    # before embedding to keep `unsafe_allow_html=True` from interpreting them as tags.
    if indication_text:
        st.markdown("**Study indication**")
        st.markdown(
            f"<div class='report-card report-card-indication'>{html.escape(indication_text)}</div>",
            unsafe_allow_html=True,
        )
    gt_html = html.escape(gt_text) if gt_text else "(missing)"
    pred_html = html.escape(pred_text) if pred_text else "(missing)"
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ground truth**")
        st.markdown(f"<div class='report-card report-card-gt'>{gt_html}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("**Predicted**")
        st.markdown(f"<div class='report-card report-card-pred'>{pred_html}</div>", unsafe_allow_html=True)


def main() -> None:
    shared.set_base_page_config("Results Explorer")
    shared.inject_styles()
    sidebar = shared.configure_sidebar(default_results="")
    state = shared.build_state(sidebar.raw_results, sidebar.raw_reports_gt, sidebar.raw_reports_pred)
    if state is None:
        st.stop()

    st.title("🔎 Results Explorer")

    # Prefer the parquet index, falling back to a plain list only when none exists.
    # An empty filter result means zero matches — never the unfiltered listing.
    index_df = shared.load_report_index(str(state.results_dir))
    filtered, search_query, count_placeholder, total = _filter_panel(index_df)
    if filtered is None:
        report_ids = shared.get_report_ids(str(state.results_dir))
        if total == 0:
            total = len(report_ids)
    else:
        report_ids = filtered["report_id"].tolist()

    # Apply free-text search across GT + Pred findings, then update the count.
    report_ids = _filter_by_finding_text(state, report_ids, search_query)
    count_placeholder.markdown(
        f"<div style='text-align:right;color:#6b7280;font-size:0.9rem;'>"
        f"{len(report_ids):,} / {total:,} reports</div>",
        unsafe_allow_html=True,
    )

    if not report_ids:
        st.warning(
            "No reports match the active filters. Clear the search box or relax the "
            "actionable-errors slider to see results."
        )
        st.stop()

    report_id = _render_selection_box(report_ids)
    # Switching reports invalidates the per-row selection.
    if st.session_state.get("_last_report") != report_id:
        st.session_state["_last_report"] = report_id
        _clear_selection()

    per_report = shared.load_per_report_metrics(str(state.results_dir), report_id)
    if per_report:
        _per_report_metric_cards(per_report)
    else:
        st.info("No per_report_metrics for this series. Re-run scoring to populate per_report_metrics/<series>.json.")

    matching_data: dict[str, object] = {}
    if state.matching_dir:
        matching_data = shared.load_matching(str(state.matching_dir / f"{report_id}.json"))
    attr_errors: dict[str, object] | None = None
    if state.attribute_errors_dir:
        attr_errors = shared.load_attribute_errors(str(state.results_dir), report_id)

    gt_findings: list[dict[str, object]] = []
    pred_findings: list[dict[str, object]] = []
    if state.findings_gt_dir:
        gt_findings = shared.load_findings(str(state.findings_gt_dir / f"{report_id}.json"))
    if state.findings_pred_dir:
        pred_findings = shared.load_findings(str(state.findings_pred_dir / f"{report_id}.json"))

    gt_idx, pred_idx = shared.build_match_index(matching_data, attr_errors)

    tab_findings, tab_reports = st.tabs(["Findings", "Reports"])

    with tab_findings:
        with st.container(border=True):
            col_errors, col_subset = st.columns([2, 3])
            with col_errors:
                st.markdown(
                    "<div style='color:#6b7280;font-size:0.72rem;font-weight:600;"
                    "text-transform:uppercase;letter-spacing:0.04em;margin-bottom:0.25rem;'>"
                    "Errors</div>",
                    unsafe_allow_html=True,
                )
                errors_filter = st.radio(
                    "Errors filter",
                    options=_ERRORS_FILTER_OPTIONS,
                    horizontal=True,
                    label_visibility="collapsed",
                    key="errors_filter",
                    help=(
                        "Fade out findings to the chosen error tier. A finding passes only "
                        "if its match is INC / MIS / SPU (i.e. an error) AND its clinical "
                        "significance is in the tier. "
                        "`actionable` = critical + urgent + notable. "
                        "`triage` = critical + urgent."
                    ),
                )
            with col_subset:
                st.markdown(
                    "<div style='color:#6b7280;font-size:0.72rem;font-weight:600;"
                    "text-transform:uppercase;letter-spacing:0.04em;margin-bottom:0.25rem;'>"
                    "Subset</div>",
                    unsafe_allow_html=True,
                )
                subset_filter = st.radio(
                    "Subset filter",
                    options=_SUBSET_FILTER_OPTIONS,
                    horizontal=True,
                    label_visibility="collapsed",
                    key="subset_filter",
                    help=(
                        "Fade out findings that don't belong to the selected subset. "
                        "measurement and comparison keep findings carrying that attribute "
                        "and can overlap each other; abnormal-regular and normal-regular "
                        "are the findings of each clinical_status carrying neither, so "
                        "they never overlap the attribute subsets."
                    ),
                )

        gt_by_id = {f.get("finding_id"): f for f in gt_findings}
        pred_by_id = {f.get("finding_id"): f for f in pred_findings}

        # Inline panel above the columns: appears whenever a finding is selected.
        sel_id = st.session_state.get(_SELECT_KEY_ID)
        sel_is_gt = st.session_state.get(_SELECT_KEY_IS_GT)
        if sel_id is not None:
            info = (gt_idx if sel_is_gt else pred_idx).get(sel_id)
            if info is not None:
                selected = (gt_by_id if sel_is_gt else pred_by_id).get(sel_id)
                match_details.render_selected_finding_panel(
                    info,
                    selected,
                    is_gt=bool(sel_is_gt),
                    gt_idx=gt_idx,
                    pred_idx=pred_idx,
                    gt_findings_by_id=gt_by_id,
                    pred_findings_by_id=pred_by_id,
                )

        col_gt, col_pred = st.columns(2)
        with col_gt:
            _render_finding_column(
                gt_findings,
                gt_idx,
                "Ground truth",
                is_gt=True,
                counterpart_match_idx=pred_idx,
                errors_filter=errors_filter,
                subset_filter=subset_filter,
                counterpart_findings=pred_by_id,
            )
        with col_pred:
            _render_finding_column(
                pred_findings,
                pred_idx,
                "Predicted",
                is_gt=False,
                counterpart_match_idx=gt_idx,
                errors_filter=errors_filter,
                subset_filter=subset_filter,
                counterpart_findings=gt_by_id,
            )

        st.markdown("---")
        st.subheader("Match Outcomes", help=shared.MATCH_OUTCOMES_HELP)
        is_pct = shared.render_match_outcomes_toggle(key="match_outcomes_mode_explorer")
        shared.render_match_outcomes_bar((per_report or {}).get("muc_counts") or {}, is_pct=is_pct)

    with tab_reports:
        _render_reports_tab(state, report_id)


if __name__ == "__main__":
    main()
