"""Shared constants for the RadMatch evaluation dashboard."""

from __future__ import annotations

# ============================================================================
# Color Constants
# ============================================================================

# Clinical status colors (pastel tones compatible with white text)
CLINICAL_STATUS_COLORS: dict[str, str] = {
    "abnormal": "#8b5cf6",  # Purple (violet-500)
    "normal": "#0ea5e9",  # Sky blue (sky-500)
}

# Comparison colors (lighter tones)
COMPARISON_COLORS: dict[str, str] = {
    "stable": "#9ca3af",  # Light gray
    "improving": "#86efac",  # Light green
    "worsening": "#fca5a5",  # Light red
    "new": "#7dd3fc",  # Light sky
    "resolved": "#6ee7b7",  # Light emerald
    "no": "#e5e7eb",  # Very light gray
}

# ============================================================================
# Directory Names
# ============================================================================

RADMATCH_RESULTS_DIR: str = "radmatch_results"

# ============================================================================
# Sidebar Config Persistence
# ============================================================================

CONFIG_RESULTS_PATH = "eval_config_results_path"
CONFIG_REPORTS_GT_PATH = "eval_config_reports_gt_path"
CONFIG_REPORTS_PRED_PATH = "eval_config_reports_pred_path"

# ============================================================================
# Query Parameters (for shareable URLs)
# ============================================================================

QUERY_PARAM_RESULTS = "results_dir"
QUERY_PARAM_REPORTS_GT = "reports_gt_dir"
QUERY_PARAM_REPORTS_PRED = "reports_pred_dir"

# ============================================================================
# Error tiers (sidebar selector; keys of `tiers.<name>` in the outputs)
# ============================================================================

CONFIG_TIER = "eval_config_tier"
DEFAULT_TIER = "actionable"
TIER_PREFIX: dict[str, str] = {"actionable": "a", "triage": "t", "critical": "c"}
TIER_NAMES: dict[str, str] = {"actionable": "Actionable", "triage": "Triage", "critical": "Critical"}
# Metric abbreviations (after the tier prefix: aER, aFN, ...) and their full names.
METRIC_NAMES: dict[str, str] = {
    "ER": "Errors",
    "FN": "False Negatives",
    "FP": "False Positives",
    "Rec": "Recall",
    "Prec": "Precision",
}
