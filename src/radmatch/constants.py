"""Shared constants for RadMatch evaluation."""

from __future__ import annotations

# ============================================================================
# Finding Schema Constants
# ============================================================================

CLINICAL_STATUS_VALUES: set[str] = {"normal", "abnormal"}
COMPARISON_VALUES: set[str] = {"stable", "improving", "worsening", "new", "resolved"}
MEASUREMENT_CATEGORY_VALUES: set[str] = {"size", "count", "attenuation", "ratio", "other"}

# Tiers follow the ACR Actionable Findings Framework / RSNA colour codes.
CLINICAL_SIGNIFICANCE_VALUES: set[str] = {"critical", "urgent", "notable", "routine"}
DEFAULT_CLINICAL_SIGNIFICANCE: str = "routine"

# Safety-recall denominator pools. A finding is a hit iff its match survives
# PAR-reclassification as COR or PAR; INC and MIS are misses.
TRIAGE_SIGNIFICANCE_TIERS: tuple[str, ...] = ("critical", "urgent")
ACTIONABLE_SIGNIFICANCE_TIERS: tuple[str, ...] = ("critical", "urgent", "notable")

# A cross-bucket comparison difference is `major` (misleads on whether action is
# needed); same-bucket, or one side absent, is `minor`.
BENIGN_COMPARISONS: frozenset[str] = frozenset({"stable", "improving", "resolved"})
ACTIVE_COMPARISONS: frozenset[str] = frozenset({"worsening", "new"})


# ============================================================================
# LLM Configuration
# ============================================================================

# Catalog of supported models organized by provider. Routing only — RadMatch does
# not price requests.
MODEL_CATALOG: dict[str, set[str]] = {
    "mistral": {"magistral-medium-2509"},
    # "openai" routes through OpenAIClient, which talks to Azure OpenAI when
    # AZURE_OPENAI_ENDPOINT is set and api.openai.com otherwise. GPT models plus the
    # non-OpenAI families served over the same OpenAI-compatible Azure route (Kimi,
    # DeepSeek) live here.
    # NOTE: most entries are vendor model ids, valid on api.openai.com. A few are Azure
    # *deployment* names (`gpt-5-4` is a gpt-5.4 deployment) and resolve only on the
    # Azure route — deployment names are chosen per resource, so edit this set to match
    # your own.
    "openai": {
        "gpt-4.1",
        "gpt-5",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5.5",
        "gpt-5-4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5-mini",
        "gpt-5-nano",
        "kimi-k2.6",
        "deepseek-v4-pro",
    },
    # Claude answers the Anthropic Messages API, not the OpenAI surface, so it routes
    # through a dedicated AnthropicClient (json_schema structured output is emulated
    # with a forced tool). Azure Foundry when ANTHROPIC_FOUNDRY_BASE_URL is set,
    # api.anthropic.com otherwise.
    "anthropic": {
        "claude-opus-4-8",
        "claude-fable-5",
    },
}

# Mapping from model name to provider (derived from MODEL_CATALOG)
MODEL_TO_PROVIDER: dict[str, str] = {model: provider for provider, models in MODEL_CATALOG.items() for model in models}

# Maximum number of tokens for LLM completion responses.
MAX_TOKENS: int = 32768

# Maximum number of retry attempts for failed LLM API calls.
MAX_RETRIES: int = 5

# Bounds a single attempt (tenacity owns retries). Without it the SDKs default to
# ~600s, so one hung socket holds a worker thread for ten minutes.
LLM_REQUEST_TIMEOUT_S: float = 180.0


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

# Stage 2 scope label, gating safety-recall credit. 1:1 matches are `direct` only
# (a 1:1 too vague for that must be left unmatched). Multi-bind matches are
# `aggregate` when they name the pathology ("Bilateral pleural effusions") or
# `generic` when they merely absorb it ("Study unremarkable"). Required on every
# row — credit iff scope is direct/aggregate, or the GT finding is routine.
MATCH_SCOPE_VALUES: tuple[str, ...] = ("direct", "aggregate", "generic")
MATCH_SCOPE_CREDITED: frozenset[str] = frozenset({"direct", "aggregate"})

ATTRIBUTE_ERROR_SEVERITIES: tuple[str, ...] = ("major", "minor")

# Stage 3a handles the structured dimensions, Stage 3b the free-text ones.
# `measurement` is split: numeric comparison is deterministic, but the LLM may also
# flag a difference that crosses a clinical boundary.
ATTRIBUTE_DIMENSIONS_LLM: tuple[str, ...] = ("location", "severity", "morphology", "certainty")
# Keep in sync with `assets/prompts/prompt_attribute_errors.md`; anything else the
# judge emits is dropped by `inference._normalize_llm_error`.
ATTRIBUTE_DIMENSIONS_LLM_ACCEPTED: tuple[str, ...] = (*ATTRIBUTE_DIMENSIONS_LLM, "measurement")
ATTRIBUTE_DIMENSIONS_ALL: tuple[str, ...] = ("clinical_status", "comparison", "measurement", *ATTRIBUTE_DIMENSIONS_LLM)

# Parallel views of the finding population. `measurement` / `comparison` collect
# findings carrying that attribute and may overlap each other; the `*-regular`
# subsets carry neither, so status and attribute subsets stay disjoint.
SUBSETS: tuple[str, ...] = ("measurement", "comparison", "abnormal-regular", "normal-regular")


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
