"""Shared utilities for the RadMatch evaluation Streamlit dashboard."""

from __future__ import annotations

import contextlib
import html as _html
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from radmatch import constants
from radmatch.dashboard.common import constants as dashboard_constants
from radmatch.io import load_json, read_text_file

# ============================================================================
# State + sidebar
# ============================================================================


@dataclass
class SidebarState:
    """Raw inputs from the sidebar."""

    raw_results: str
    raw_reports_gt: str = ""
    raw_reports_pred: str = ""


@dataclass
class DashboardState:
    """Validated paths used across the dashboard. None when the underlying
    subdirectory is missing — pages decide whether to gate or proceed."""

    results_dir: Path
    radmatch_dir: Path
    findings_gt_dir: Path | None
    findings_pred_dir: Path | None
    matching_dir: Path | None
    attribute_errors_dir: Path | None
    per_report_metrics_dir: Path | None
    reports_gt_dir: Path | None
    reports_pred_dir: Path | None
    indications_dir: Path | None


def _radmatch_dir(parent: Path) -> Path:
    return parent / dashboard_constants.RADMATCH_RESULTS_DIR


def set_base_page_config(page_title: str) -> None:
    st.set_page_config(page_title=page_title, layout="wide")


def persist_sidebar_config(sidebar: SidebarState) -> None:
    """Mirror sidebar inputs into session_state AND the URL query params.

    Session state survives reruns inside one browser tab; query params survive
    a hard refresh (Ctrl+R). The two together make the chosen results dir
    sticky across all interactions.
    """
    st.session_state[dashboard_constants.CONFIG_RESULTS_PATH] = sidebar.raw_results
    st.session_state[dashboard_constants.CONFIG_REPORTS_GT_PATH] = sidebar.raw_reports_gt
    st.session_state[dashboard_constants.CONFIG_REPORTS_PRED_PATH] = sidebar.raw_reports_pred

    _sync_query_param(dashboard_constants.QUERY_PARAM_RESULTS, sidebar.raw_results)
    _sync_query_param(dashboard_constants.QUERY_PARAM_REPORTS_GT, sidebar.raw_reports_gt)
    _sync_query_param(dashboard_constants.QUERY_PARAM_REPORTS_PRED, sidebar.raw_reports_pred)


def _sync_query_param(name: str, value: str) -> None:
    """Add/remove a query param so the URL reflects the current sidebar state."""
    value = (value or "").strip()
    if value:
        if st.query_params.get(name) != value:
            st.query_params[name] = value
    elif name in st.query_params:
        del st.query_params[name]


def configure_sidebar(default_results: str) -> SidebarState:
    """Render the sidebar config inputs and persist them to session state."""
    params = st.query_params
    results_default = (
        params.get(dashboard_constants.QUERY_PARAM_RESULTS)
        or st.session_state.get(dashboard_constants.CONFIG_RESULTS_PATH)
        or default_results
    )
    reports_gt_default = (
        params.get(dashboard_constants.QUERY_PARAM_REPORTS_GT)
        or st.session_state.get(dashboard_constants.CONFIG_REPORTS_GT_PATH)
        or ""
    )
    reports_pred_default = (
        params.get(dashboard_constants.QUERY_PARAM_REPORTS_PRED)
        or st.session_state.get(dashboard_constants.CONFIG_REPORTS_PRED_PATH)
        or ""
    )

    with st.sidebar:
        st.markdown("### Configuration")
        results_value = st.text_input(
            "Results directory",
            value=results_default,
            help=f"Parent directory containing {dashboard_constants.RADMATCH_RESULTS_DIR}/.",
            key="results_dir_input",
        )
        reports_gt_value = st.text_input(
            "(Optional) Reports GT directory",
            value=reports_gt_default,
            help="Directory of ground-truth .txt reports for the Results Explorer side panel.",
            key="reports_gt_input",
        )
        reports_pred_value = st.text_input(
            "(Optional) Reports Pred directory",
            value=reports_pred_default,
            help="Directory of predicted .txt reports for the Results Explorer side panel.",
            key="reports_pred_input",
        )
        _, col_right = st.columns([2, 2])
        with col_right:
            st.button("Apply", type="secondary", width="stretch", key="apply_config_button")

    sidebar = SidebarState(
        raw_results=results_value, raw_reports_gt=reports_gt_value, raw_reports_pred=reports_pred_value
    )
    persist_sidebar_config(sidebar)
    return sidebar


def _existing_subdir(parent: Path, name: str) -> Path | None:
    sub = parent / name
    return sub if sub.exists() and sub.is_dir() else None


def build_state(raw_results: str, raw_reports_gt: str = "", raw_reports_pred: str = "") -> DashboardState | None:
    """Validate sidebar inputs and resolve subdirectories under `radmatch_results/`."""
    raw_results = raw_results.strip()
    if not raw_results:
        st.warning("Please provide a valid results directory.")
        return None

    parent = Path(raw_results).expanduser()
    if not parent.exists() or not parent.is_dir():
        st.warning(f"Results directory not found: {parent}")
        return None

    if parent.name == dashboard_constants.RADMATCH_RESULTS_DIR:
        st.warning(
            f"Provide the PARENT directory, not the {dashboard_constants.RADMATCH_RESULTS_DIR}/ folder directly."
        )
        return None

    radmatch_dir = _radmatch_dir(parent)
    if not radmatch_dir.exists() or not radmatch_dir.is_dir():
        st.warning(f"{dashboard_constants.RADMATCH_RESULTS_DIR}/ not found under {parent}.")
        return None

    reports_gt_dir = _existing_subdir(radmatch_dir, constants.REPORTS_GT_DIR)
    reports_pred_dir = _existing_subdir(radmatch_dir, constants.REPORTS_PRED_DIR)

    for raw, current_attr in ((raw_reports_gt, "gt"), (raw_reports_pred, "pred")):
        raw = raw.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.exists() and path.is_dir():
            if current_attr == "gt":
                reports_gt_dir = path
            else:
                reports_pred_dir = path

    return DashboardState(
        results_dir=parent,
        radmatch_dir=radmatch_dir,
        findings_gt_dir=_existing_subdir(radmatch_dir, constants.FINDINGS_GT_DIR),
        findings_pred_dir=_existing_subdir(radmatch_dir, constants.FINDINGS_PRED_DIR),
        matching_dir=_existing_subdir(radmatch_dir, constants.MATCHING_DIR),
        attribute_errors_dir=_existing_subdir(radmatch_dir, constants.ATTRIBUTE_ERRORS_DIR),
        per_report_metrics_dir=_existing_subdir(radmatch_dir, "per_report_metrics"),
        reports_gt_dir=reports_gt_dir,
        reports_pred_dir=reports_pred_dir,
        indications_dir=_existing_subdir(radmatch_dir, constants.INDICATIONS_DIR),
    )


# ============================================================================
# CSS
# ============================================================================


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .filter-card {
            background: #f8fafc; border: 1px solid rgba(148,163,184,0.4); border-radius: 0.9rem;
            padding: 0.75rem 0.9rem 0.9rem 0.9rem; box-shadow: 0 8px 24px rgba(15,23,42,0.06);
            margin-bottom: 1.1rem;
        }
        .ds-stats-card {
            background: #ecf2ff; border: 1px solid #c7d2fe; border-radius: 0.8rem;
            padding: 0.7rem 0.95rem; box-shadow: 0 12px 24px rgba(15,23,42,0.08);
            margin-bottom: 0.85rem;
        }
        .ds-stats-card span { display: block; }
        .ds-stats-label {
            font-size: 0.78rem; color: #6171a3; text-transform: uppercase; letter-spacing: 0.04em;
        }
        .ds-stats-value { font-size: 1.25rem; font-weight: 600; color: #0f172a; }
        /* Inline subtitle (e.g. `(126 / 128)`) sitting next to a metric value.
           Class specificity beats `.ds-stats-card span { display: block; }`. */
        .ds-stats-card .ds-stats-subtitle {
            display: inline;
            font-size: 0.78rem; color: #6171a3; font-weight: normal;
            font-variant-numeric: tabular-nums; margin-left: 0.35rem;
        }
        .volume-metric-card { background: linear-gradient(135deg,#eef4ff,#dfe8ff); border-color:#c7d2fe; }
        .safety-metric-card { background: linear-gradient(135deg,#fff1f2,#ffe4e6); border-color:#fecdd3; }
        .f1-metric-card     { background: linear-gradient(135deg,#fffbeb,#fde68a); border-color:#fcd34d; }
        .report-card {
            border-radius: 0.75rem; padding: 1rem 1.1rem;
            font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; color: #1f2933;
            white-space: pre-wrap;
        }
        .report-card-gt   { background: #eff6ff; border: 1px solid #93c5fd; }
        .report-card-pred { background: #fff6e6; border: 1px solid #f5c48d; }
        .report-card-indication {
            background: #f5f3ff; border: 1px solid #c4b5fd;
            margin-bottom: 0.75rem;
        }
        .selected-panel {
            background: #fefce8; border: 1px solid #facc15; border-radius: 0.6rem;
            padding: 0.85rem 1.05rem; margin-bottom: 0.6rem;
            /* Pin descendant text to a dark tone so it stays readable on the
               yellow background in dark mode (without this, Streamlit's auto
               text color makes unstyled cells like the Dimension column near-
               invisible). Per-element color overrides still apply. */
            color: #1f2937;
        }
        .selected-panel-divider {
            border: none; border-top: 1px solid #fde68a; margin: 0.6rem 0 0.5rem 0;
        }
        .finding-card {
            background: #fff; border: 1px solid #e5e7eb; border-radius: 0.6rem;
            padding: 0.7rem 0.95rem; margin-bottom: 0.5rem;
            color: #1f2933;  /* Same reason as .selected-panel: pin text dark in dark mode. */
        }
        /* Finding-card colors mirror the Match Outcomes bar so each category is
           visually distinct (previously MIS shared red with INC, SPU shared amber with PAR). */
        .finding-card-cor { border-color: #15803d; background: #dcfce7; }
        .finding-card-par { border-color: #0d9488; background: #ccfbf1; }
        .finding-card-inc { border-color: #dc2626; background: #fee2e2; }
        .finding-card-mis { border-color: #7f1d1d; background: #fecaca; }
        .finding-card-spu { border-color: #f59e0b; background: #fef3c7; }
        .finding-card-greyed { border-color: #e5e7eb; background: #f9fafb; opacity: 0.45; }
        .finding-card-greyed .finding-text, .finding-card-greyed .finding-meta {
            color: #9ca3af;
        }
        .finding-text { font-size: 0.92rem; color: #1f1f1f; margin-bottom: 0.4rem; }
        .finding-meta { font-size: 0.78rem; color: #6b7280; }
        .outcome-pill {
            display: inline-block; padding: 0.1rem 0.45rem; border-radius: 4px;
            font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em;
            margin-right: 0.35rem;
        }
        .outcome-cor { background: #15803d; color: white; }
        .outcome-par { background: #0f766e; color: white; }
        .outcome-inc { background: #991b1b; color: white; }
        .outcome-mis { background: #7f1d1d; color: white; }
        .outcome-spu { background: #b45309; color: white; }
        .attr-error {
            background: #fef9c3; border-left: 3px solid #ca8a04;
            padding: 0.3rem 0.55rem; margin: 0.3rem 0; font-size: 0.85rem; color: #422006;
        }
        .attr-error-major { background: #fee2e2; border-left-color: #b91c1c; }
        .attr-error-stage3a { background: #f1f5f9; border-left-color: #475569; }
        .home-hero {
            background: linear-gradient(135deg,#eef4ff,#fafaff); border: 1px solid #c7d2fe;
            border-radius: 0.8rem; padding: 0.9rem 1.05rem;
        }
        .home-hero .title { font-size: 1.05rem; font-weight: 700; color: #0f172a; }
        .home-hero .subtitle { font-size: 0.85rem; color: #475569; }
        .gt-pred-header {
            text-align: center; margin: 0 0 0.5rem 0;
            padding-bottom: 0.5rem; border-bottom: 2px solid #e5e7eb;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# Data loaders (radmatch_results/...)
# ============================================================================


@st.cache_data(show_spinner=False)
def load_summary(results_dir_str: str) -> dict[str, object] | None:
    """Load `metrics_summary.json`. Returns the full dict, or None."""
    radmatch_dir = _radmatch_dir(Path(results_dir_str))
    path = radmatch_dir / constants.SUMMARY_FILE
    if not path.exists():
        return None
    data = load_json(path, default=None, raise_on_error=False)
    return data if isinstance(data, dict) else None


@st.cache_data(show_spinner=False)
def load_per_report_metrics(results_dir_str: str, report_id: str) -> dict[str, object] | None:
    """Load `per_report_metrics/<series>.json`. Returns the full dict, or None."""
    path = _radmatch_dir(Path(results_dir_str)) / "per_report_metrics" / f"{report_id}.json"
    if not path.exists():
        return None
    data = load_json(path, default=None, raise_on_error=False)
    return data if isinstance(data, dict) else None


@st.cache_data(show_spinner=False)
def load_attribute_errors(results_dir_str: str, report_id: str) -> dict[str, object] | None:
    """Load `attribute_errors/<series>.json` (raw Stage 3 output: muc_records etc.)."""
    path = _radmatch_dir(Path(results_dir_str)) / constants.ATTRIBUTE_ERRORS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    data = load_json(path, default=None, raise_on_error=False)
    return data if isinstance(data, dict) else None


@st.cache_data(show_spinner=False)
def get_report_ids(results_dir_str: str) -> list[str]:
    """Union of series IDs found under findings_gt/, findings_pred/, matching/."""
    radmatch_dir = _radmatch_dir(Path(results_dir_str))
    ids: set[str] = set()
    for sub in (constants.FINDINGS_GT_DIR, constants.FINDINGS_PRED_DIR, constants.MATCHING_DIR):
        d = radmatch_dir / sub
        if d.exists():
            ids.update(p.stem for p in d.glob("*.json") if p.is_file())
    return sorted(ids)


@st.cache_data(show_spinner=False)
def load_findings(path_str: str) -> list[dict[str, object]]:
    path = Path(path_str)
    if not path.exists():
        return []
    data = load_json(path, default=None, raise_on_error=False)
    return data if isinstance(data, list) else []


@st.cache_data(show_spinner=False)
def load_matching(path_str: str) -> dict[str, object]:
    path = Path(path_str)
    if not path.exists():
        return {}
    data = load_json(path, default=None, raise_on_error=False)
    return data if isinstance(data, dict) else {}


@st.cache_data(show_spinner=False)
def load_report_text(reports_dir: str | None, report_id: str) -> str | None:
    """Load the raw `<series>.txt` report from a reports_{gt,pred}/ dir, if any."""
    if not reports_dir:
        return None
    path = Path(reports_dir) / f"{report_id}.txt"
    return read_text_file(path)


def load_report_index(results_dir_str: str) -> pd.DataFrame | None:
    """Load precomputed per-report index from `aux/report_index.parquet`.

    Not cached directly: the actual read is delegated to `_read_index_parquet`
    keyed by (path, mtime), so rebuilding `build_dashboard_data.py` invalidates
    the cache automatically (a fresh mtime → new cache key).
    """
    path = _radmatch_dir(Path(results_dir_str)) / constants.AUX_DIR / "report_index.parquet"
    if not path.exists():
        return None
    return _read_index_parquet(str(path), path.stat().st_mtime)


@st.cache_data(show_spinner=False)
def _read_index_parquet(path_str: str, _mtime: float) -> pd.DataFrame | None:
    """`_mtime` is unused inside the function but is part of the cache key —
    when the parquet is rebuilt, mtime changes, so the cache lookup misses and
    pandas re-reads from disk."""
    with contextlib.suppress(Exception):
        return pd.read_parquet(path_str, engine="pyarrow")
    return None


# ============================================================================
# Per-pair derived data
# ============================================================================


@dataclass
class CounterpartMatchInfo:
    """One match row from a finding's perspective — the other side of the pair."""

    counterpart_id: str
    category: str  # per-pair effective category: COR / PAR / INC
    match_reasoning: str | None
    structured_errors: list[dict[str, object]]
    text_errors: list[dict[str, object]]
    match_scope: str | None = None


# Under N:N, a finding identified by ANY pred is a hit even if another verbose pred
# mis-described it. Mirrors `_per_gt_safety_outcomes`.
_CATEGORY_RANK = {"COR": 3, "PAR": 2, "INC": 1, "MIS": 0, "SPU": 0}


def _best_category(categories: list[str]) -> str:
    if not categories:
        return "COR"
    return max(categories, key=lambda c: _CATEGORY_RANK.get(c, -1))


@dataclass
class PerPairMatchInfo:
    """Resolved match state for one finding.

    `counterparts` holds one entry per match row the finding participates in, empty
    for MIS / SPU. `category` is the best across those rows.
    """

    category: str  # one of COR / PAR / INC / MIS / SPU
    counterparts: list[CounterpartMatchInfo]


def build_match_index(
    matching_data: dict[str, object], attribute_errors: dict[str, object] | None
) -> tuple[dict[str, PerPairMatchInfo], dict[str, PerPairMatchInfo]]:
    """Merge Stage 2 matching with Stage 3 attribute errors into
    (gt_id → info, pred_id → info), with per-pair categories reclassified to the
    effective taxonomy.
    """
    from radmatch.scoring import metrics as _scoring_metrics

    matches = matching_data.get("matches", []) if matching_data else []
    unmatched_pred = matching_data.get("unmatched_pred", []) if matching_data else []
    unmatched_gt = matching_data.get("unmatched_gt", []) if matching_data else []
    muc_records = attribute_errors.get("muc_records", []) if attribute_errors else []
    structured_per_pair = attribute_errors.get("structured_errors_per_pair", []) if attribute_errors else []
    text_per_pair = attribute_errors.get("text_errors_per_pair", []) if attribute_errors else []

    rec_by_pair: dict[tuple[str, str], dict[str, object]] = {}
    for i, rec in enumerate(muc_records):
        rec_by_pair[(rec.get("pred_id"), rec.get("gt_id"))] = {
            "category": rec.get("muc_category", "COR"),
            "structured": structured_per_pair[i] if i < len(structured_per_pair) else rec.get("structured_errors", []),
            "text": text_per_pair[i] if i < len(text_per_pair) else rec.get("text_errors", []),
        }

    gt_cps: dict[str, list[CounterpartMatchInfo]] = {}
    pred_cps: dict[str, list[CounterpartMatchInfo]] = {}
    for m in matches:
        pred_id = m.get("pred_id")
        gt_id = m.get("gt_id")
        rec = rec_by_pair.get((pred_id, gt_id), {})
        structured = list(rec.get("structured", []))
        text = list(rec.get("text", []))
        pair_category = _scoring_metrics.reclassify_to_effective_category(
            {"muc_category": rec.get("category", "COR"), "structured_errors": structured, "text_errors": text}
        )
        gt_cps.setdefault(gt_id, []).append(
            CounterpartMatchInfo(
                counterpart_id=pred_id,
                category=pair_category,
                match_reasoning=m.get("reasoning"),
                structured_errors=structured,
                text_errors=text,
                match_scope=m.get("match_scope"),
            )
        )
        pred_cps.setdefault(pred_id, []).append(
            CounterpartMatchInfo(
                counterpart_id=gt_id,
                category=pair_category,
                match_reasoning=m.get("reasoning"),
                structured_errors=structured,
                text_errors=text,
                match_scope=m.get("match_scope"),
            )
        )

    gt_idx: dict[str, PerPairMatchInfo] = {
        gid: PerPairMatchInfo(_best_category([c.category for c in cps]), cps) for gid, cps in gt_cps.items()
    }
    pred_idx: dict[str, PerPairMatchInfo] = {
        pid: PerPairMatchInfo(_best_category([c.category for c in cps]), cps) for pid, cps in pred_cps.items()
    }
    for gt_id in unmatched_gt:
        gt_idx[gt_id] = PerPairMatchInfo("MIS", [])
    for pred_id in unmatched_pred:
        pred_idx[pred_id] = PerPairMatchInfo("SPU", [])
    return gt_idx, pred_idx


# ============================================================================
# UI helpers — formatting + small renderers
# ============================================================================


def _is_valid_metric_value(value: float | None) -> bool:
    if value is None:
        return False
    return not (isinstance(value, float) and math.isnan(value))


def format_percent_metric(value: float | None) -> str:
    """Format 0.0–1.0 as percentage; 'N/A' if missing."""
    if not _is_valid_metric_value(value):
        return "N/A"
    return f"{value:.1%}"


def format_numeric_metric(value: float | None, decimals: int = 4) -> str:
    if not _is_valid_metric_value(value):
        return "N/A"
    return f"{value:.{decimals}f}"


def format_int(value: int) -> str:
    return f"{value:,}"


def render_metric_card(
    label: str,
    value: str | int,
    card_class: str = "volume-metric-card",
    help_text: str | None = None,
    subtitle: str | None = None,
) -> str:
    """Render a metric card. `help_text` adds a small `ⓘ` icon with a hover
    tooltip; `subtitle` renders inline next to the value in smaller, lighter
    type (e.g. a `(126 / 128)` fraction beside a recall percentage)."""
    if help_text:
        info = (
            f" <span style='font-size:0.75rem;color:#6b7280;cursor:help;' "
            f'title="{_html.escape(help_text, quote=True)}">ⓘ</span>'
        )
    else:
        info = ""
    subtitle_html = f" <span class='ds-stats-subtitle'>{_html.escape(subtitle)}</span>" if subtitle else ""
    return (
        f"<div class='ds-stats-card {card_class}'>"
        f"<span class='ds-stats-label'>{label}{info}</span>"
        f"<span class='ds-stats-value'>{value}{subtitle_html}</span></div>"
    )


def format_recall_metric(safety: dict[str, object], tier: str) -> str:
    """Safety recall as a percentage, or "—" on an empty GT pool — distinct from the
    "N/A" that means missing data.
    """
    if int(safety.get(f"{tier}_gt_total") or 0) == 0:
        return "—"
    return format_percent_metric(safety.get(f"{tier}_recall"))


def format_recall_subtitle(safety: dict[str, object], tier: str) -> str | None:
    """`(hit_count / gt_total)` subtitle, so a percentage's sample size is visible
    without back-computing it.
    """
    hits = safety.get(f"{tier}_hit_count")
    total = int(safety.get(f"{tier}_gt_total") or 0)
    if hits is None or total <= 0:
        return None
    return f"({int(hits)} / {total})"


def format_precision_metric(safety: dict[str, object], tier: str) -> str:
    """Precision counterpart of `format_recall_metric` — '—' when the pred pool is empty."""
    if int(safety.get(f"{tier}_pred_total") or 0) == 0:
        return "—"
    return format_percent_metric(safety.get(f"{tier}_precision"))


def format_precision_subtitle(safety: dict[str, object], tier: str) -> str | None:
    """`(pred_hit_count / pred_total)` subtitle string for a safety-precision card."""
    hits = safety.get(f"{tier}_pred_hit_count")
    total = int(safety.get(f"{tier}_pred_total") or 0)
    if hits is None or total <= 0:
        return None
    return f"({int(hits)} / {total})"


MATCH_OUTCOMES_HELP = (
    "COR — correct: matched with no attribute errors at all.\n\n"
    "PAR — partial: matched with only minor attribute errors "
    "(imprecise location / severity / morphology / certainty, etc.). The "
    "finding was identified, just with rough descriptors. Counts as a "
    "*hit* in safety recalls (the finding wasn't missed).\n\n"
    "INC — incorrect: matched but materially wrong. Either status was inverted "
    "(e.g. pred 'no PTX' vs GT 'PTX present') OR ≥1 major attribute error "
    "(wrong location / wrong severity / wrong comparison / ...). Counts as a "
    "miss in safety recalls.\n\n"
    "MIS — missed: a GT finding with no pred counterpart.\n\n"
    "SPU — spurious: a predicted finding with no GT counterpart (hallucination)."
)


def format_finding_id(finding_id: str, is_gt: bool) -> str:
    """Format finding ID as `GT01` / `Pred12`. Both sides number independently, so the
    raw `<series>_NNN` id is ambiguous without the side prefix.
    """
    raw = finding_id.rsplit("_", 1)[-1] if "_" in finding_id else finding_id
    num = f"{int(raw):02d}" if raw.isdigit() else raw
    return f"GT{num}" if is_gt else f"Pred{num}"


OUTCOME_COLORS: dict[str, str] = {
    "COR": "#22c55e",  # green — perfect match
    "PAR": "#14b8a6",  # teal — matched with minor descriptor errors only
    "INC": "#dc2626",  # red — matched but materially wrong (status inversion or major attr error)
    "MIS": "#7f1d1d",  # dark red — GT finding without pred counterpart
    "SPU": "#f59e0b",  # amber — predicted finding without GT counterpart
}


def render_match_outcomes_toggle(key: str) -> bool:
    """Render the counts/percentages toggle above a Match Outcomes bar.

    Returns True when the percentages mode is selected. The Streamlit key must
    be unique per page (Performance Summary uses dataset aggregate, Results
    Explorer uses per-pair counts).
    """
    mode = st.radio(
        "Display",
        options=("counts", "percentages"),
        horizontal=True,
        label_visibility="collapsed",
        key=key,
    )
    return mode == "percentages"


def render_match_outcomes_bar(muc_counts: dict[str, int], *, is_pct: bool = False) -> None:
    """Horizontal stacked bar of the COR / PAR / INC / MIS / SPU distribution.
    `is_pct=True` switches labels and axis to percentages.
    """
    import pandas as pd
    import plotly.express as px

    raw_counts = [muc_counts.get(cat, 0) for cat in constants.MUC_CATEGORIES]
    total = sum(raw_counts)
    denom = total or 1
    values = [100.0 * c / denom for c in raw_counts] if is_pct else raw_counts
    rows = [{"Category": cat, "Value": v} for cat, v in zip(constants.MUC_CATEGORIES, values)]
    upper = 100.0 if is_pct else total
    tick_text = "100%" if is_pct else f"{total:,}"
    fig = px.bar(
        pd.DataFrame(rows),
        x="Value",
        y=[""] * len(rows),
        color="Category",
        orientation="h",
        color_discrete_map=OUTCOME_COLORS,
        category_orders={"Category": list(constants.MUC_CATEGORIES)},
        text="Value",
    )
    fig.update_traces(
        texttemplate="%{text:.1f}%" if is_pct else "%{text:d}",
        textposition="inside",
        insidetextanchor="middle",
        textfont={"color": "white", "size": 12},
    )
    fig.update_layout(
        height=170,
        margin={"t": 10, "b": 10, "l": 10, "r": 10},
        xaxis={
            "title": "",
            "range": [0, upper] if upper > 0 else None,
            "tickmode": "array",
            "tickvals": [upper] if upper > 0 else [],
            "ticktext": [tick_text] if upper > 0 else [],
        },
        yaxis_title="",
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.35,
            "xanchor": "center",
            "x": 0.5,
            "title_text": "",
            "font": {"size": 12},
        },
    )
    st.plotly_chart(fig, width="stretch")


# Order used everywhere a per-dimension breakdown is rendered (table + chart).
DIMENSION_DISPLAY_ORDER: list[str] = [
    "clinical_status",
    "location",
    "severity",
    "morphology",
    "certainty",
    "measurement",
    "comparison",
]


def render_hero_row(emoji: str, title: str, subtitle: str, page_path: str, key: str) -> None:
    left, right = st.columns([20, 2], gap="small")
    with left:
        st.markdown(
            f"<div class='home-hero'>"
            f"<div style='display:flex;align-items:center;gap:0.6rem;'>"
            f"<div style='font-size:1.3rem;'>{emoji}</div>"
            f"<div><div class='title'>{title}</div><div class='subtitle'>{subtitle}</div></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button("Open", width="stretch", type="primary", key=key):
            try:
                st.switch_page(page_path)
            except (ValueError, KeyError):
                st.caption(f'Use the left sidebar Pages menu to open "{title}".')


_SIGNIFICANCE_COLORS = {
    "critical": "#991b1b",
    "urgent": "#b45309",
    "notable": "#15803d",
    "routine": "#475569",
}


_MATCH_SCOPE_COLORS: dict[str, str] = {
    "direct": "#6b7280",  # slate — neutral, 1:1 default
    "aggregate": "#4f6987",  # muted blue — legitimate umbrella claim
    "generic": "#a16207",  # muted amber — boilerplate cover, gates safety credit
}


_SCOPE_CONCERN_RANK = {"direct": 0, "aggregate": 1, "generic": 2}


def _summarise_scopes(scopes: list[str | None]) -> str | None:
    """Most concerning scope across a counterpart list (generic > aggregate > direct).
    Returns None when no scopes are present (MIS / SPU)."""
    valid = [s for s in scopes if s]
    if not valid:
        return None
    return max(valid, key=lambda s: _SCOPE_CONCERN_RANK.get(s, -1))


def _scope_badge(scope: str | None, *, font_size: str, padding: str, extra_style: str = "") -> str:
    """Outlined pill with the scope-specific color. Empty string on MIS / SPU."""
    if not scope:
        return ""
    color = _MATCH_SCOPE_COLORS.get(scope, "#6b7280")
    return (
        f"<span style='font-size:{font_size};color:{color};border:1px solid {color};"
        f"padding:{padding};border-radius:0.2rem;font-weight:600;text-transform:uppercase;"
        f"background:transparent;letter-spacing:0.02em;{extra_style}'>{scope}</span>"
    )


def build_match_scope_badge(scope: str | None) -> str:
    """Standard chip used next to the Matching Reasoning header on the detail panel."""
    return _scope_badge(scope, font_size="0.62rem", padding="0.08rem 0.35rem")


def build_match_scope_badge_compact(scope: str | None) -> str:
    """Tighter variant for the meta row of a finding card."""
    return _scope_badge(scope, font_size="0.55rem", padding="0.02rem 0.25rem", extra_style="line-height:1;")


def build_significance_badge(finding: dict[str, object]) -> str:
    """Standalone badge for the finding's clinical_significance.

    Rendered prominently at the top of the finding card (next to the outcome pill)
    because significance is what weights every metric. Returns empty string if
    the finding has no significance.
    """
    sig = finding.get("clinical_significance")
    if not sig:
        return ""
    color = _SIGNIFICANCE_COLORS.get(str(sig), "#475569")
    return (
        f"<span style='font-size:0.62rem;background:{color};color:white;"
        f"padding:0.12rem 0.4rem;border-radius:0.2rem;font-weight:600;text-transform:lowercase;'>{sig}</span>"
    )


def build_finding_badges(finding: dict[str, object]) -> str:
    """Bottom-row badges: significance / status / comparison / measurement."""
    badges: list[str] = []
    sig_badge = build_significance_badge(finding)
    if sig_badge:
        badges.append(sig_badge)
    status = str(finding.get("clinical_status") or "")
    if status:
        color = dashboard_constants.CLINICAL_STATUS_COLORS.get(status, "#d1d5db")
        badges.append(
            f"<span style='font-size:0.62rem;background:{color};color:white;"
            f"padding:0.12rem 0.4rem;border-radius:0.2rem;'>{status}</span>"
        )
    comp = finding.get("comparison")
    if comp:
        color = dashboard_constants.COMPARISON_COLORS.get(str(comp), "#d1d5db")
        badges.append(
            f"<span style='font-size:0.62rem;background:{color};color:white;"
            f"padding:0.12rem 0.4rem;border-radius:0.2rem;'>{comp}</span>"
        )
    measurements = finding.get("measurements") or []
    if isinstance(measurements, list) and measurements:
        badges.append(
            "<span style='font-size:0.62rem;background:#f97316;color:white;"
            "padding:0.12rem 0.4rem;border-radius:0.2rem;'>measurement</span>"
        )
    return " ".join(badges)


def render_outcome_pill(category: str) -> str:
    """Render the per-finding outcome pill (COR / PAR / INC / MIS / SPU)."""
    return f"<span class='outcome-pill outcome-{category.lower()}'>{category}</span>"


def render_finding_card(
    finding: dict[str, object],
    info: PerPairMatchInfo,
    is_gt: bool,
    is_greyed: bool = False,
) -> str:
    """One finding rendered as a colored card with outcome pill + badges + text.

    When `is_greyed` is True the card is rendered in a neutral, low-contrast
    style — used to fade out non-selected findings while one match is in focus.
    """
    if is_greyed:
        card_class = "finding-card finding-card-greyed"
    else:
        card_class = f"finding-card finding-card-{info.category.lower()}"
    pill = render_outcome_pill(info.category)
    badges = build_finding_badges(finding)
    # Escape everything reaching the HTML: report text carries `<`/`>` (thresholds)
    # that would corrupt the card markup under `unsafe_allow_html=True`.
    text = _html.escape(str(finding.get("text", "")))
    fid = str(finding.get("finding_id", ""))
    short_id = _html.escape(format_finding_id(fid, is_gt=is_gt))
    id_html = f"<span class='finding-meta' title='{_html.escape(fid)}'>{short_id}</span>"
    if info.counterparts:
        labels = [_html.escape(format_finding_id(c.counterpart_id, is_gt=not is_gt)) for c in info.counterparts]
        rendered = labels[0] if len(labels) == 1 else "{" + ", ".join(labels) + "}"
        id_html += f"<span class='finding-meta'> → {rendered}</span>"
        # One chip per finding. When multi-bind rows disagree, show the most
        # concerning scope so vagueness isn't hidden by a friendlier sibling row.
        id_html += build_match_scope_badge_compact(_summarise_scopes([c.match_scope for c in info.counterparts]))
    return (
        f"<div class='{card_class}'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;gap:0.5rem;'>"
        f"<div style='display:flex;align-items:center;gap:0.35rem;'>{pill}</div>"
        f"<div style='display:flex;align-items:center;gap:0.25rem;'>{id_html}</div>"
        f"</div>"
        f"<div class='finding-text' style='margin-top:0.35rem;'>{text}</div>"
        f"<div>{badges}</div>"
        f"</div>"
    )
