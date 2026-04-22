"""Shared constants for RadMatch evaluation."""

from __future__ import annotations

# ============================================================================
# Finding Schema Constants
# ============================================================================

# Simplified finding fields (without abnormality_category and organ)
FINDING_FIELDS: tuple[str, ...] = (
    "finding_id",
    "text",
    "clinical_status",
    "comparison",
    "measurements",
)

# Constants for clinical status, comparison, and measurement category values
CLINICAL_STATUS_VALUES: set[str] = {"normal", "abnormal"}
COMPARISON_VALUES: set[str] = {"stable", "improving", "worsening", "new", "resolved"}
MEASUREMENT_CATEGORY_VALUES: set[str] = {"size", "count", "attenuation", "ratio", "other"}
COMPARISON_VALUES_ORDER: tuple[str, ...] = ("stable", "improving", "worsening", "new", "resolved")
MEASUREMENT_CATEGORY_ORDER: tuple[str, ...] = ("size", "count", "attenuation", "ratio", "other")

# Finding type categories for evaluation metrics
FINDING_TYPE_ABNORMAL_REGULAR: str = "abnormal-regular"
FINDING_TYPE_NORMAL_REGULAR: str = "normal-regular"
FINDING_TYPE_LONGITUDINAL: str = "longitudinal"
FINDING_TYPE_MEASUREMENT: str = "measurement"
FINDING_TYPES: tuple[str, ...] = (
    FINDING_TYPE_ABNORMAL_REGULAR,
    FINDING_TYPE_NORMAL_REGULAR,
    FINDING_TYPE_LONGITUDINAL,
    FINDING_TYPE_MEASUREMENT,
)


# ============================================================================
# LLM Configuration
# ============================================================================

# Catalog of supported models organized by provider
MODEL_CATALOG: dict[str, set[str]] = {
    "mistral": {
        "magistral-medium-2509",
    },
    "azure": {
        "gpt-5",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5-4",
        "gpt-5-4-mini",
        "gpt-5-4-nano",
        "gpt-5-mini",
        "gpt-5-nano",
    },
}

# Mapping from model name to provider (derived from MODEL_CATALOG)
MODEL_TO_PROVIDER: dict[str, str] = {model: provider for provider, models in MODEL_CATALOG.items() for model in models}

# Maximum number of tokens for LLM completion responses.
MAX_TOKENS: int = 32768

# Maximum number of retry attempts for failed LLM API calls.
MAX_RETRIES: int = 3


# ============================================================================
# LLM Batch Processing Constants
# ============================================================================

# Batch file names for finding extraction
BATCH_REQUESTS_FILE: str = "batch_requests.jsonl"  # JSONL file with batch API requests
BATCH_JOB_ID_FILE: str = "batch_job_id.txt"  # Text file containing the batch job ID
BATCH_SERIES_UUID_MAP_FILE: str = "batch_series_uuid_map.json"  # Maps custom_id to report file paths

# Maximum number of requests per batch file (to avoid API limits)
MAX_REQUESTS_PER_BATCH_FILE: int = 3000

# Batch job status constants
COMPLETED_STATUSES: tuple[str, ...] = ("SUCCESS", "completed")
FAILED_STATUSES: tuple[str, ...] = ("FAILED", "failed", "TIMEOUT_EXCEEDED", "expired", "CANCELLED", "cancelled")
IN_PROGRESS_STATUSES: tuple[str, ...] = (
    "VALIDATING",
    "IN_PROGRESS",
    "FINALIZING",
    "validating",
    "in_progress",
    "finalizing",
)


# ============================================================================
# Findings Extraction Default Values
# ============================================================================

DEFAULT_CLINICAL_STATUS: str = "abnormal"
DEFAULT_MEASUREMENT_CATEGORY: str = "other"


# ============================================================================
# Directory and File Names
# ============================================================================

# Output directory names
RESULTS_DIR: str = "radmatch_results"
FINDINGS_GT_DIR: str = "findings_gt"
FINDINGS_PRED_DIR: str = "findings_pred"
MATCHING_DIR: str = "matching"
REPORTS_GT_DIR: str = "reports_gt"
REPORTS_PRED_DIR: str = "reports_pred"

# Batch processing directory and file names
BATCH_AUX_DIR: str = "aux"
BATCH_CLIENT_DIR: str = "batch_client"
BATCH_METADATA_FILE: str = "batch_metadata.json"
FAILED_REPORTS_FILE: str = "failed_reports.json"
FAILED_FINDINGS_FILE: str = "failed_findings.json"
SUMMARY_FILE: str = "metrics_summary.json"

# Few-shot example file patterns
EXAMPLE_FILE_PREFIX: str = "example_"


# ============================================================================
# Measurement Parsing Constants
# ============================================================================

# Common unit patterns for different measurement categories
MEASUREMENT_UNIT_PATTERNS: dict[str, list[str]] = {
    "size": ["mm", "cm", "m", "inch", "in", "inches"],
    "attenuation": ["hu", "hounsfield", "units"],
    "ratio": ["pct", "percent", "ratio", ":"],
    "count": [],
    "other": [],
}

# Unit conversion factors to base unit (for normalization)
# Base units: mm for size, HU for attenuation
MEASUREMENT_UNIT_CONVERSION: dict[str, float] = {
    # Size (to mm)
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "inch": 25.4,
    "in": 25.4,
    "inches": 25.4,
    # Attenuation (HU is already base)
    "hu": 1.0,
    "hounsfield": 1.0,
    "units": 1.0,
    # Ratio/Percentage
    "pct": 1.0,
    "percent": 1.0,
}
