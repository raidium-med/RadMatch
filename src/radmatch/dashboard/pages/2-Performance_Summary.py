#!/usr/bin/env python3
"""Performance Summary — dataset-level RadMatch metrics."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from radmatch import constants
from radmatch.dashboard.common import constants as dashboard_constants
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


FN_HELP = "Reference findings of the tier missed or contradicted (MIS + INC on the tier's GT findings)."
FP_HELP = (
    "Claims of the tier the reference lacks: SPU in the tier, plus INC where only the "
    "prediction is in the tier (e.g. an abnormality where the reference says normal)."
)


def _headline_metric_cards(block: dict[str, object], tier: str) -> None:
    """Cards for the selected tier: errors per report split into FN + FP, then
    recall / precision with `(hits / total)` subtitles and errors per finding."""
    row1 = st.columns(3)
    for col, (metric, key) in zip(row1, [("ER", "errors"), ("FN", "fn"), ("FP", "fp")]):
        col.markdown(
            shared.render_metric_card(
                shared.tier_metric_label(tier, metric, suffix=" per Report", with_abbrev=False),
                shared.format_numeric_metric(block.get(f"{key}_per_report"), decimals=2),
                card_class="f1-metric-card" if metric == "ER" else "grey-metric-card",
            ),
            unsafe_allow_html=True,
        )

    row2 = st.columns(3)
    for col, (abbr, metric) in zip(row2, [("Rec", "recall"), ("Prec", "precision")]):
        col.markdown(
            shared.render_metric_card(
                shared.tier_metric_label(tier, abbr, with_abbrev=False),
                shared.format_tier_rate(block, metric),
                card_class="grey-metric-card",
                subtitle=shared.format_tier_rate_subtitle(block, metric),
            ),
            unsafe_allow_html=True,
        )
    row2[2].markdown(
        shared.render_metric_card(
            f"{dashboard_constants.TIER_NAMES[tier]} Errors per Finding",
            shared.format_numeric_metric(block.get("errors_per_finding"), decimals=3),
            card_class="grey-metric-card",
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
    "Diagnostic only — does not feed the tier errors (aER, tER, cER)."
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


def _subsets_table(subsets: dict[str, dict], tier: str) -> None:
    # Unlisted subsets trail at the end, so the table never drops rows. Each row is
    # an independent slice — columns do not sum across rows.
    ordered_names = [s for s in _SUBSET_DISPLAY_ORDER if s in subsets] + [
        s for s in subsets if s not in _SUBSET_DISPLAY_ORDER
    ]
    fn, fp, prec, rec = (shared.tier_metric_label(tier, m, with_tier=False) for m in ("FN", "FP", "Prec", "Rec"))

    def _pct_or_nan(block: dict, metric: str) -> float:
        # Vacuous pool → NaN, so the cell renders empty rather than "100 %".
        total_key = "gt_total" if metric == "recall" else "pred_total"
        if int(block.get(total_key) or 0) == 0:
            return float("nan")
        return float(block.get(metric) or 0.0) * 100.0

    rows: list[dict[str, object]] = []
    for name in ordered_names:
        payload = subsets[name]
        block = shared.tier_block(payload, tier)
        muc = payload.get("muc_counts", {})
        rows.append(
            {
                "Subset": name,
                "Errors per Finding": float(block.get("errors_per_finding") or 0.0),
                fn: int(block.get("fn_total") or 0),
                fp: int(block.get("fp_total") or 0),
                "Findings at Stake": int(block.get("findings_total") or 0),
                prec: _pct_or_nan(block, "precision"),
                rec: _pct_or_nan(block, "recall"),
                **{cat: muc.get(cat, 0) for cat in constants.MUC_CATEGORIES},
            }
        )

    # Numeric columns auto-right-align (header + cell); the "Subset" name stays
    # left. Narrow widths so 1-4 digit cells don't get dwarfed.
    column_config = {
        "Subset": st.column_config.TextColumn(width="small"),
        "Errors per Finding": st.column_config.NumberColumn(width="small", format="%.3f"),
        fn: st.column_config.NumberColumn(width="small", help=FN_HELP),
        fp: st.column_config.NumberColumn(width="small", help=FP_HELP),
        "Findings at Stake": st.column_config.NumberColumn(width="small"),
        prec: st.column_config.NumberColumn(width="small", format="%.1f%%"),
        rec: st.column_config.NumberColumn(width="small", format="%.1f%%"),
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
    attribute_breakdown = summary.get("attribute_breakdown") or {}
    subsets = summary.get("subsets") or {}

    _hdr(metadata)
    st.subheader("Main Metrics")
    tier = shared.select_tier(key="tier_radio_summary")
    st.caption(f"{dashboard_constants.TIER_NAMES[tier]} tier: {' + '.join(constants.ERROR_TIERS[tier])} findings.")
    _headline_metric_cards(shared.tier_block(summary, tier), tier)
    st.markdown("---")

    st.subheader("Match Outcomes", help=shared.MATCH_OUTCOMES_HELP)
    is_pct = shared.render_match_outcomes_toggle(key="match_outcomes_mode_summary")
    shared.render_match_outcomes_bar(muc_counts, is_pct=is_pct)

    st.subheader("Attribute Errors", help=ATTRIBUTE_ERRORS_HELP)
    _attribute_breakdown(attribute_breakdown)

    # Prepend a whole-dataset "overall" row so the per-subset rates have a
    # baseline to compare against; the summary carries the same `tiers` block.
    st.subheader("Subset Results", help=SUBSET_RESULTS_HELP)
    _subsets_table({_OVERALL_ROW: summary, **subsets}, tier)


if __name__ == "__main__":
    main()
