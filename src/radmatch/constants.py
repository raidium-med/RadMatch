"""Shared constants for RadMatch evaluation."""

from __future__ import annotations

import os

# ============================================================================
# Finding Schema Constants
# ============================================================================

CLINICAL_STATUS_VALUES: set[str] = {"normal", "abnormal"}
COMPARISON_VALUES: set[str] = {"stable", "improving", "worsening", "new", "resolved"}
LATERALITY_VALUES: set[str] = {"left", "right", "bilateral"}
MEASUREMENT_CATEGORY_VALUES: set[str] = {"size", "count", "attenuation", "ratio", "other"}

# Tiers follow the ACR Actionable Findings Framework / RSNA colour codes.
CLINICAL_SIGNIFICANCE_VALUES: set[str] = {"critical", "urgent", "notable", "routine"}
DEFAULT_CLINICAL_SIGNIFICANCE: str = "routine"

# Significance pools of the error tiers. A GT finding is a hit iff its match survives
# PAR-reclassification as COR or PAR; INC and MIS are misses (FN).
CRITICAL_SIGNIFICANCE_TIERS: tuple[str, ...] = ("critical",)
TRIAGE_SIGNIFICANCE_TIERS: tuple[str, ...] = ("critical", "urgent")
ACTIONABLE_SIGNIFICANCE_TIERS: tuple[str, ...] = ("critical", "urgent", "notable")
# The `tiers.<name>` output blocks, reported as aER = aFN + aFP with aRec / aPrec
# (actionable), and likewise tER, ... (triage) and cER, ... (critical).
ERROR_TIERS: dict[str, tuple[str, ...]] = {
    "actionable": ACTIONABLE_SIGNIFICANCE_TIERS,
    "triage": TRIAGE_SIGNIFICANCE_TIERS,
    "critical": CRITICAL_SIGNIFICANCE_TIERS,
}
ERROR_TIER_PREFIX: dict[str, str] = {"actionable": "a", "triage": "t", "critical": "c"}

# Comparisons that signal disease activity (the others are benign). A difference across the two
# buckets, or a dropped active gt comparison, is `major`; any other difference is `minor`.
ACTIVE_COMPARISONS: frozenset[str] = frozenset({"worsening", "new"})


# ============================================================================
# LLM Configuration
# ============================================================================

# Catalog of supported models organized by provider, with list prices in USD per 1M
# tokens (standard tier, short context) used to report `token_cost`. A `None` price
# routes the model without pricing it.
MODEL_CATALOG: dict[str, dict[str, dict[str, float] | None]] = {
    "mistral": {
        "magistral-medium-2509": {"input": 2.00, "output": 5.00, "cached_input": 0.20},
    },
    # "openai" routes through OpenAIClient, which talks to Azure OpenAI when
    # AZURE_OPENAI_ENDPOINT is set and api.openai.com otherwise. GPT models plus the
    # non-OpenAI families served over the same OpenAI-compatible Azure route (Kimi,
    # DeepSeek) live here.
    # NOTE: most entries are vendor model ids, valid on api.openai.com. A few are Azure
    # *deployment* names (`gpt-5-4` is a gpt-5.4 deployment) and resolve only on the
    # Azure route — deployment names are chosen per resource, so edit this set to match
    # your own.
    "openai": {
        "gpt-4.1": {"input": 2.00, "output": 8.00, "cached_input": 0.50},
        "gpt-5": {"input": 1.25, "output": 10.00, "cached_input": 0.125},
        "gpt-5.1": {"input": 1.25, "output": 10.00, "cached_input": 0.125},
        "gpt-5.2": {"input": 1.25, "output": 10.00, "cached_input": 0.125},
        "gpt-5.5": {"input": 5.00, "output": 30.00, "cached_input": 0.50},
        "gpt-5-4": {"input": 2.50, "output": 15.00, "cached_input": 0.25},  # gpt-5.4 deployment
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50, "cached_input": 0.075},
        "gpt-5.4-nano": {"input": 0.20, "output": 1.25, "cached_input": 0.02},
        "gpt-5-mini": {"input": 0.25, "output": 2.00, "cached_input": 0.025},
        "gpt-5-nano": {"input": 0.05, "output": 0.40, "cached_input": 0.005},
        "gpt-5.6-sol": {"input": 4.00, "output": 20.00, "cached_input": 0.40},
        "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cached_input": 0.20},
        "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cached_input": 0.02},
        "gpt-6-sol": {"input": 2.00, "output": 10.00, "cached_input": 0.20},
        "gpt-6-luna": {"input": 0.10, "output": 0.50, "cached_input": 0.01},
        "gpt-6-astra": {"input": 10.00, "output": 50.00, "cached_input": 1.00},
        "kimi-k2.6": {"input": 0.95, "output": 4.00, "cached_input": 0.095},
        "deepseek-v4-pro": {"input": 1.74, "output": 3.48, "cached_input": 0.174},
    },
    # Claude answers the Anthropic Messages API, not the OpenAI surface, so it routes
    # through a dedicated AnthropicClient (json_schema structured output maps to the
    # native `output_config.format`). Azure Foundry when ANTHROPIC_FOUNDRY_BASE_URL is
    # set, api.anthropic.com otherwise.
    "anthropic": {
        "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cached_input": 0.20},
        "claude-fable-5": {"input": 10.00, "output": 50.00, "cached_input": 1.00},
        "claude-fable-5-1": {"input": 10.00, "output": 50.00, "cached_input": 1.00},
    },
}

# Mapping from model name to provider and pricing (derived from MODEL_CATALOG)
MODEL_TO_PROVIDER: dict[str, str] = {model: provider for provider, models in MODEL_CATALOG.items() for model in models}
MODEL_PRICING: dict[str, dict[str, float]] = {
    model: price for models in MODEL_CATALOG.values() for model, price in models.items() if price is not None
}

# Maximum number of tokens for LLM completion responses.
MAX_TOKENS: int = int(os.environ.get("RADMATCH_MAX_TOKENS") or 32768)

# Maximum number of retry attempts for failed LLM API calls.
MAX_RETRIES: int = 5

# Default per-request timeout (seconds) for one LLM attempt; Stage 2 and Stage 3b derive
# theirs from it. Tenacity, not the SDK, owns retries.
LLM_REQUEST_TIMEOUT_S: float = float(os.environ.get("RADMATCH_REQUEST_TIMEOUT_S") or 180.0)


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
ATTRIBUTE_ERRORS_DIR: str = "attribute_errors"
PER_REPORT_METRICS_DIR: str = "per_report_metrics"
REPORTS_GT_DIR: str = "reports_gt"
REPORTS_PRED_DIR: str = "reports_pred"
INDICATIONS_DIR: str = "indications"
FEWSHOT_DIR: str = "fewshot"

AUX_DIR: str = "aux"
FAILED_REPORTS_FILE: str = "failed_reports.json"  # Stage 1 (extraction)
FAILED_REPORTS_MATCHING_FILE: str = "failed_reports_matching.json"  # Stage 2
FAILED_REPORTS_SCORING_FILE: str = "failed_reports_scoring.json"  # Stage 3
SUMMARY_FILE: str = "metrics_summary.json"

# Few-shot example file patterns
EXAMPLE_FILE_PREFIX: str = "example_"


# ============================================================================
# RadMatch Evaluation Constants
# ============================================================================

# Stage 3 tags matched pairs COR / PAR / INC, then reclassifies any PAR holding a
# major error to INC. Surviving PAR = matched but imprecise, still a safety hit.
MUC_CATEGORIES: tuple[str, ...] = ("COR", "PAR", "INC", "MIS", "SPU")

ATTRIBUTE_ERROR_SEVERITIES: tuple[str, ...] = ("major", "minor")

# Stage 3a handles the structured dimensions, Stage 3b the free-text ones.
# `measurement` and `comparison` are split: the comparators flag a size difference or
# an invented change, and the LLM grades the ones that matter.
ATTRIBUTE_DIMENSIONS_LLM: tuple[str, ...] = ("site", "extent", "severity", "character", "diagnosis", "certainty")
# Keep in sync with `assets/prompts/prompt_attribute_errors.md`; anything else the
# judge emits is dropped by `inference._normalize_llm_error`.
ATTRIBUTE_DIMENSIONS_LLM_ACCEPTED: tuple[str, ...] = (*ATTRIBUTE_DIMENSIONS_LLM, "measurement", "comparison")
ATTRIBUTE_DIMENSIONS_ALL: tuple[str, ...] = (
    "clinical_status",
    "laterality",
    "comparison",
    "measurement",
    *ATTRIBUTE_DIMENSIONS_LLM,
)

# Parallel views of the finding population. `measurement` / `comparison` collect
# findings carrying that attribute and may overlap each other; the `*-regular`
# subsets carry neither, so status and attribute subsets stay disjoint.
SUBSETS: tuple[str, ...] = ("measurement", "comparison", "abnormal-regular", "normal-regular")


# ============================================================================
# Measurement Parsing Constants
# ============================================================================

# Spelled-out or symbol units mapped to their canonical form. Matching is exact: a prefix match
# read "mL" and "minutes" as "m" and "cm3" as "cm".
MEASUREMENT_UNIT_ALIASES: dict[str, str] = {
    "%": "pct",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "cc": "ml",
    "cm3": "ml",
    "cm^3": "ml",
    "cm³": "ml",
}

# Unit conversion factors to base unit (for normalization)
# Base units: mm for length, mL for volume, HU for attenuation
MEASUREMENT_UNIT_CONVERSION: dict[str, float] = {
    # Length (to mm)
    "mm": 1.0,
    "cm": 10.0,
    "inch": 25.4,
    "in": 25.4,
    "inches": 25.4,
    # Volume (to mL)
    "ml": 1.0,
    "l": 1000.0,
    # Attenuation (HU is already base)
    "hu": 1.0,
    "hounsfield": 1.0,
    "units": 1.0,
    # Ratio/Percentage
    "pct": 1.0,
    "percent": 1.0,
}

# Sizes are compared only within one kind: a length is never compared with a volume
MEASUREMENT_SIZE_UNIT_KIND: dict[str, str] = {
    "mm": "length",
    "cm": "length",
    "inch": "length",
    "in": "length",
    "inches": "length",
    "ml": "volume",
    "l": "volume",
}
