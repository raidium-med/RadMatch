#!/usr/bin/env python3
"""Performance Summary — dataset-level RadMatch metrics."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from radmatch import constants
from radmatch.dashboard.common import shared


def _hdr(metadata: dict[str, object]) -> None:
    """Top header row: report count + total findings on each side (all from metadata)."""
    n_reports = int(metadata.get("n_reports") or 0)
    gt_total = int(metadata.get("total_gt_findings") or 0)
    pred_total = int(metadata.get("total_pred_findings") or 0)

    cols = st.columns(3)
    cols[0].markdown(shared.render_metric_card("Total Reports", f"{n_reports:,}"), unsafe_allow_html=True)
    cols[1].markdown(shared.render_metric_card("Total GT findings", f"{gt_total:,}"), unsafe_allow_html=True)
    cols[2].markdown(shared.render_metric_card("Total Pred findings", f"{pred_total:,}"), unsafe_allow_html=True)


def _headline_metric_cards(summary: dict[str, object], safety: dict[str, object]) -> None:
    """Safety cards: average actionable errors, then actionable and triage
    precision/recall with `(hits / total)` subtitles. The opportunity-normalized
    `actionable_errors_per_finding` lives in the subset table instead.
    """
    row1 = st.columns(3)
    row1[0].markdown(
        shared.render_metric_card(
            "Avg. Actionable Errors",
            shared.format_numeric_metric(summary.get("actionable_errors_per_report"), decimals=2),
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


_OVERALL_ROW = "overall"
_SUBSET_DISPLAY_ORDER = [_OVERALL_ROW, "abnormal-regular", "normal-regular", "measurement", "comparison"]

SUBSET_RESULTS_HELP = (
    "Per-subset breakdown of the same finding population.\n\n"
    "- **overall**: every finding — the whole-dataset baseline each subset rate compares against.\n"
    "- **abnormal-regular**: positive findings (`clinical_status == 'abnormal'`) that carry "
    "  *neither* a measurement *nor* a comparison — the plain descriptive findings.\n"
    "- **normal-regular**: explicit negations (`clinical_status == 'normal'`, e.g. 'no pleural "
    "  effusion') that likewise carry no measurement/comparison.\n"
    "- **measurement**: findings that carry at least one numerical measurement "
    "  (size / count / attenuation / ratio).\n"
    "- **comparison**: findings annotated with a temporal label "
    "  (stable / improving / worsening / new / resolved).\n\n"
    "`measurement` and `comparison` are not mutually exclusive — a finding can carry both — "
    "so the subset finding counts don't sum to the overall finding total."
)


_SEVERITY_LABEL = {"clean": "clean", "minor": "minor error", "major": "major error"}
_SEVERITY_COLORS = {"clean": "#22c55e", "minor error": "#f59e0b", "major error": "#dc2626"}

ATTRIBUTE_ERRORS_HELP = (
    "Per-attribute distribution of clean / minor / major across all matched "
    "pairs (COR + INC + the internal PAR records before reclassification). "
    "Diagnostic only — does not feed `actionable_errors`."
)


def _attribute_breakdown(breakdown: dict[str, dict[str, float]]) -> None:
    """Stacked horizontal bar of clean / minor / major per attribute dimension.

    A toggle switches the x-axis between absolute counts and per-dimension
    percentages (clean_pct / minor_pct / major_pct).
    """
    if not breakdown:
        st.info("No `attribute_breakdown` in this metrics_summary.json. Re-run scoring.")
        return

    ordered_dims = [d for d in shared.DIMENSION_DISPLAY_ORDER if d in breakdown]

    mode = st.radio(
        "Display",
        options=("counts", "percentages"),
        horizontal=True,
        label_visibility="collapsed",
        key="attribute_breakdown_mode",
    )
    is_pct = mode == "percentages"

    rows = [
        {
            "Dimension": dim,
            "Severity": _SEVERITY_LABEL[severity],
            "Value": (
                100.0 * (breakdown[dim].get(f"{severity}_pct") or 0.0) if is_pct else breakdown[dim].get(severity, 0)
            ),
        }
        for dim in ordered_dims
        for severity in ("clean", "minor", "major")
    ]
    fig = px.bar(
        pd.DataFrame(rows),
        x="Value",
        y="Dimension",
        color="Severity",
        orientation="h",
        color_discrete_map=_SEVERITY_COLORS,
        category_orders={
            "Severity": ["clean", "minor error", "major error"],
            "Dimension": ordered_dims,
        },
        text="Value",
    )
    fig.update_traces(
        texttemplate="%{text:.1f}%" if is_pct else "%{text:d}",
        textposition="inside",
        insidetextanchor="middle",
        textfont={"color": "white", "size": 11},
    )
    # Every dimension shares the same `evaluated` denominator, so lock the x-axis to
    # it rather than let plotly round the tick up (857 → "900").
    evaluated_total = max(
        (int(breakdown[dim].get("evaluated") or 0) for dim in ordered_dims),
        default=0,
    )
    upper = 100.0 if is_pct else evaluated_total
    tick_text = "100%" if is_pct else f"{evaluated_total:,}"
    fig.update_layout(
        height=320,
        margin={"t": 40, "b": 10, "l": 10, "r": 10},
        xaxis={
            "title": "%" if is_pct else "Count",
            "range": [0, upper] if upper > 0 else None,
            "tickmode": "array",
            "tickvals": [upper] if upper > 0 else [],
            "ticktext": [tick_text] if upper > 0 else [],
        },
        yaxis_title="",
        legend_title_text="",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )
    st.plotly_chart(fig, width="stretch")


def _subsets_table(subsets: dict[str, dict]) -> None:
    # Unlisted subsets trail at the end, so the table never drops rows. Each row is
    # an independent slice — columns do not sum across rows.
    ordered_names = [s for s in _SUBSET_DISPLAY_ORDER if s in subsets] + [
        s for s in subsets if s not in _SUBSET_DISPLAY_ORDER
    ]

    def _safety_pct_or_nan(safety: dict, tier: str, metric: str) -> float:
        # Vacuous pool → NaN, so the cell renders empty rather than "100 %".
        total_key = f"{tier}_pred_total" if metric == "precision" else f"{tier}_gt_total"
        if int(safety.get(total_key) or 0) == 0:
            return float("nan")
        return float(safety.get(f"{tier}_{metric}", 0.0)) * 100.0

    rows: list[dict[str, object]] = []
    for name in ordered_names:
        payload = subsets[name]
        muc = payload.get("muc_counts", {})
        safety = payload.get("clinical_safety_summary") or {}
        actionable_findings = int(payload.get("actionable_findings_total", 0) or 0)
        rows.append(
            {
                "Subset": name,
                "Avg. actionable errors / finding": float(payload.get("actionable_errors_per_finding", 0.0) or 0.0),
                "Actionable findings": actionable_findings,
                "Actionable precision": _safety_pct_or_nan(safety, "actionable", "precision"),
                "Actionable recall": _safety_pct_or_nan(safety, "actionable", "recall"),
                "Triage precision": _safety_pct_or_nan(safety, "triage", "precision"),
                "Triage recall": _safety_pct_or_nan(safety, "triage", "recall"),
                **{cat: muc.get(cat, 0) for cat in constants.MUC_CATEGORIES},
            }
        )

    # Numeric columns auto-right-align (header + cell); the "Subset" name stays
    # left. Narrow widths so 1-4 digit cells don't get dwarfed.
    column_config = {
        "Subset": st.column_config.TextColumn(width="small"),
        "Avg. actionable errors / finding": st.column_config.NumberColumn(width="small", format="%.3f"),
        "Actionable findings": st.column_config.NumberColumn(width="small"),
        "Actionable precision": st.column_config.NumberColumn(width="small", format="%.1f%%"),
        "Actionable recall": st.column_config.NumberColumn(width="small", format="%.1f%%"),
        "Triage precision": st.column_config.NumberColumn(width="small", format="%.1f%%"),
        "Triage recall": st.column_config.NumberColumn(width="small", format="%.1f%%"),
        **{cat: st.column_config.NumberColumn(width="small") for cat in constants.MUC_CATEGORIES},
    }
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=column_config)


def main() -> None:
    shared.set_base_page_config("Performance Summary")
    shared.inject_styles()
    sidebar = shared.configure_sidebar(default_results="")
    state = shared.build_state(sidebar.raw_results, sidebar.raw_reports_gt, sidebar.raw_reports_pred)
    if state is None:
        st.stop()

    st.title("📊 Performance Summary")
    summary = shared.load_summary(str(state.results_dir))
    if not summary:
        st.warning(f"No `{constants.SUMMARY_FILE}` found in {state.radmatch_dir}. Run scoring first.")
        st.stop()

    metadata = summary.get("metadata") or {}
    muc_counts = summary.get("muc_counts") or {}
    safety = summary.get("clinical_safety_summary") or {}
    attribute_breakdown = summary.get("attribute_breakdown") or {}
    subsets = summary.get("subsets") or {}

    _hdr(metadata)
    _headline_metric_cards(summary, safety)
    st.markdown("---")

    st.subheader("Match Outcomes", help=shared.MATCH_OUTCOMES_HELP)
    is_pct = shared.render_match_outcomes_toggle(key="match_outcomes_mode_summary")
    shared.render_match_outcomes_bar(muc_counts, is_pct=is_pct)

    st.subheader("Attribute Errors", help=ATTRIBUTE_ERRORS_HELP)
    _attribute_breakdown(attribute_breakdown)

    # Prepend a whole-dataset "overall" row so the per-subset rates have a
    # baseline to compare against, shaped like a subset payload.
    overall = {
        "muc_counts": muc_counts,
        "actionable_errors_total": summary.get("actionable_errors_total", 0),
        "actionable_findings_total": summary.get("actionable_findings_total", 0),
        "actionable_errors_per_finding": summary.get("actionable_errors_per_finding", 0.0),
        "clinical_safety_summary": safety,
    }
    st.subheader("Subset Results", help=SUBSET_RESULTS_HELP)
    _subsets_table({_OVERALL_ROW: overall, **subsets})


if __name__ == "__main__":
    main()
