"""Utility functions for finding extraction."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING, Literal, Sequence, TypedDict

if TYPE_CHECKING:
    from pathlib import Path

from radmatch import constants, io

logger = logging.getLogger(__name__)


class Finding(TypedDict):
    """A single radiology finding, after extraction + normalisation."""

    finding_id: str
    text: str
    clinical_status: Literal["normal", "abnormal"]
    clinical_significance: Literal["critical", "urgent", "notable", "routine"]
    comparison: Literal["stable", "improving", "worsening", "new", "resolved"] | None
    measurements: list[dict]


# ============================================================================
# Measurement Parsing Utilities
# ============================================================================


def _normalize_unit(unit_str: str, category: str) -> str | None:
    """Normalize unit string to standard form."""
    if unit_str is None:
        return None
    if not isinstance(unit_str, str):
        unit_str = str(unit_str).strip()
    if not unit_str:
        return None

    unit_lower = unit_str.lower().strip()
    if not unit_lower:
        return None

    # Handle percentage symbol - convert to "pct"
    if unit_lower == "%":
        return "pct"

    # Check against known units for this category
    category_units = constants.MEASUREMENT_UNIT_PATTERNS.get(category, [])
    for known_unit in category_units:
        if unit_lower == known_unit or unit_lower.startswith(known_unit):
            return known_unit

    # Check against all known units
    for known_unit in constants.MEASUREMENT_UNIT_CONVERSION:
        if unit_lower == known_unit or unit_lower.startswith(known_unit):
            return known_unit

    return unit_lower


# ============================================================================
# Finding Normalisation
# ============================================================================


def validate_and_normalize_finding(finding: dict) -> dict:
    """Copy of `finding` with its enum fields validated.

    `clinical_status` and `clinical_significance` fall back to their defaults;
    invalid non-null `comparison` becomes None. The three stay independent — a
    `normal + critical` rule-out is left alone. Everything else passes through, and
    the input is never mutated.

    Applied both to fresh LLM output and to findings loaded from disk, which defends
    against schema drift and hand-edited annotations.
    """
    out = dict(finding)
    label = out.get("finding_id") or (out.get("text") or "")[:40]

    status = out.get("clinical_status")
    if status is None:
        logger.warning(
            "finding %r missing clinical_status; filling with default %r", label, constants.DEFAULT_CLINICAL_STATUS
        )
        out["clinical_status"] = constants.DEFAULT_CLINICAL_STATUS
    elif status not in constants.CLINICAL_STATUS_VALUES:
        logger.warning(
            "finding %r has invalid clinical_status %r; falling back to default %r",
            label,
            status,
            constants.DEFAULT_CLINICAL_STATUS,
        )
        out["clinical_status"] = constants.DEFAULT_CLINICAL_STATUS

    sig = out.get("clinical_significance")
    if sig is None:
        logger.warning(
            "finding %r missing clinical_significance; filling with default %r",
            label,
            constants.DEFAULT_CLINICAL_SIGNIFICANCE,
        )
        out["clinical_significance"] = constants.DEFAULT_CLINICAL_SIGNIFICANCE
    elif sig not in constants.CLINICAL_SIGNIFICANCE_VALUES:
        logger.warning(
            "finding %r has invalid clinical_significance %r; falling back to default %r",
            label,
            sig,
            constants.DEFAULT_CLINICAL_SIGNIFICANCE,
        )
        out["clinical_significance"] = constants.DEFAULT_CLINICAL_SIGNIFICANCE

    comparison = out.get("comparison")
    if comparison is not None and comparison not in constants.COMPARISON_VALUES:
        logger.warning("finding %r has invalid comparison %r; falling back to None", label, comparison)
        out["comparison"] = None

    return out


_CANONICAL_FINDING_FIELDS = (
    "finding_id",
    "text",
    "clinical_status",
    "clinical_significance",
    "comparison",
    "measurements",
)


def project_to_canonical_finding(finding: dict[str, object]) -> dict[str, object]:
    """Validate + normalize then project to the canonical 6-field schema.
    Used when serializing findings into LLM prompts (few-shot examples) so
    the wire format stays minimal."""
    normalized = validate_and_normalize_finding(finding)
    defaults = {"finding_id": "", "text": "", "measurements": []}
    return {k: normalized.get(k, defaults.get(k)) for k in _CANONICAL_FINDING_FIELDS}


# ============================================================================
# Finding Extraction Functions
# ============================================================================


def create_output_directories(output_dir: Path) -> tuple[Path, Path]:
    """Create findings_gt and findings_pred directories."""
    from radmatch import constants

    output_dir.mkdir(parents=True, exist_ok=True)
    findings_gt_dir = output_dir / constants.FINDINGS_GT_DIR
    findings_pred_dir = output_dir / constants.FINDINGS_PRED_DIR
    findings_gt_dir.mkdir(parents=True, exist_ok=True)
    findings_pred_dir.mkdir(parents=True, exist_ok=True)
    return findings_gt_dir, findings_pred_dir


def extract_findings_list(
    findings_raw: list[dict[str, object]],
    series_uuid: str,
) -> list[dict[str, object]]:
    """Extract and normalize findings from LLM response list."""
    if not isinstance(findings_raw, list):
        raise ValueError(f"Expected list, got {type(findings_raw).__name__}")

    findings_list = []
    for i, finding in enumerate(findings_raw, 1):
        if not isinstance(finding, dict):
            continue

        # Normalize measurements
        measurements = []
        measurements_raw = finding.get("measurements", [])
        if isinstance(measurements_raw, list):
            for m in measurements_raw:
                if not isinstance(m, dict) or "value" not in m or "category" not in m:
                    continue

                # Normalize category
                category = str(m["category"])
                normalized_category = (
                    category
                    if category in constants.MEASUREMENT_CATEGORY_VALUES
                    else constants.DEFAULT_MEASUREMENT_CATEGORY
                )

                # Coerce numeric strings, drop anything else — rare schema drift.
                value_raw = m.get("value")
                try:
                    if isinstance(value_raw, (int, float)):
                        numeric_value = value_raw
                    else:
                        value_str = str(value_raw).strip()
                        numeric_value = float(value_str) if "." in value_str else int(value_str)
                except (ValueError, TypeError):
                    logger.warning("Skipping measurement with invalid value %r", value_raw)
                    continue

                unit_raw = m.get("unit")
                normalized_unit = _normalize_unit(unit_raw, normalized_category) if unit_raw else None

                measurements.append({"value": numeric_value, "unit": normalized_unit, "category": normalized_category})

        normalized = validate_and_normalize_finding(
            {
                "finding_id": f"{series_uuid}_{i:03d}",
                "text": finding.get("text", ""),
                "clinical_status": finding.get("clinical_status"),
                "clinical_significance": finding.get("clinical_significance"),
                "comparison": finding.get("comparison"),
                "measurements": measurements,
            }
        )
        findings_list.append(normalized)

    return findings_list


def copy_findings_from_directory(
    source_dir: Path,
    target_dir: Path,
    series_uuid_list: Sequence[str] | None = None,
) -> int:
    """Copy filtered findings files from source to target. Returns count copied."""
    if not source_dir.exists():
        logger.warning("Source findings directory does not exist: %s", source_dir)
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    series_uuid_set = set(series_uuid_list) if series_uuid_list else None
    copied_count = 0
    skipped_count = 0

    for findings_file in source_dir.glob("*.json"):
        series_uuid = findings_file.stem
        if series_uuid_set is not None and series_uuid not in series_uuid_set:
            continue
        target_file = target_dir / f"{series_uuid}.json"
        if target_file.exists():
            skipped_count += 1
            continue

        try:
            findings_list = io.load_json(findings_file, raise_on_error=True)
            if not isinstance(findings_list, list):
                logger.warning("Skipping %s: not a list", findings_file.name)
                continue
            filtered = [project_to_canonical_finding(f) for f in findings_list if isinstance(f, dict)]
            io.save_json(filtered, target_file)
            copied_count += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to copy findings from %s: %s", findings_file.name, exc)

    if copied_count > 0:
        logger.info("Copied %d findings files from %s", copied_count, source_dir)
    if skipped_count > 0:
        logger.info("Skipped %d findings files that already have outputs", skipped_count)
    return copied_count


def copy_reports_directory(
    source_dir: Path,
    target_dir: Path,
    series_uuid_list: Sequence[str] | None = None,
) -> int:
    """Copy report .txt files from source to target. Returns count copied."""
    if not source_dir.exists():
        logger.warning("Source reports directory does not exist: %s", source_dir)
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    series_uuid_set = set(series_uuid_list) if series_uuid_list else None
    copied_count = 0

    for report_file in source_dir.glob("*.txt"):
        if series_uuid_set is not None and report_file.stem not in series_uuid_set:
            continue
        try:
            shutil.copy2(report_file, target_dir / report_file.name)
            copied_count += 1
        except (OSError, PermissionError, shutil.SameFileError) as exc:
            logger.warning("Failed to copy report from %s: %s", report_file.name, exc)

    if copied_count > 0:
        logger.info("Copied %d report files from %s to %s", copied_count, source_dir, target_dir)
    return copied_count
