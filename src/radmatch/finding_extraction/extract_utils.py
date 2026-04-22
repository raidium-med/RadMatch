"""Utility functions for finding extraction."""

from __future__ import annotations

import logging
import re
import shutil
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from pathlib import Path

from radmatch import constants, io
from radmatch.llm_utils import prompts

logger = logging.getLogger(__name__)


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


def _parse_value_and_unit(value_str: str, category: str) -> tuple[float, str | None] | None:
    """Parse 'number' or 'number unit' from a string (e.g. '2.3 cm'). Returns (value, unit) or None."""
    if not value_str or not isinstance(value_str, str):
        return None
    value_str = value_str.strip()
    match = re.match(r"^\s*([+-]?\d*\.?\d+)\s*([a-zA-Z%]+)?\s*$", value_str)
    if not match:
        return None
    try:
        num = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).strip() if match.group(2) else None
    return (num, unit or None)


def normalize_measurement_to_base_unit(value: float, unit: str | None, category: str) -> float | None:
    """Convert a measurement value to its base unit for comparison."""
    if unit is None:
        return value

    unit_lower = unit.lower().strip()
    conversion_factor = constants.MEASUREMENT_UNIT_CONVERSION.get(unit_lower)

    if conversion_factor is None:
        return value

    return value * conversion_factor


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

                # Keep value as numeric (int or float)
                value_raw = m.get("value")
                unit_from_str: str | None = None
                try:
                    if isinstance(value_raw, (int, float)):
                        numeric_value = value_raw
                    else:
                        value_str = str(value_raw).strip()
                        try:
                            numeric_value = int(value_str)
                        except ValueError:
                            numeric_value = float(value_str)
                except (ValueError, TypeError):
                    value_str = str(value_raw).strip() if value_raw is not None else ""
                    parsed = _parse_value_and_unit(value_str, normalized_category)
                    if parsed is None:
                        logger.warning(f"Skipping measurement with invalid value '{value_raw}'")
                        continue
                    numeric_value, unit_from_str = parsed

                unit_raw = m.get("unit")
                unit_to_normalize = unit_from_str or unit_raw
                normalized_unit = _normalize_unit(unit_to_normalize, normalized_category) if unit_to_normalize else None

                measurements.append({"value": numeric_value, "unit": normalized_unit, "category": normalized_category})

        clinical_status_raw = finding.get("clinical_status", constants.DEFAULT_CLINICAL_STATUS)
        clinical_status = (
            clinical_status_raw
            if clinical_status_raw in constants.CLINICAL_STATUS_VALUES
            else constants.DEFAULT_CLINICAL_STATUS
        )

        # Normalize comparison
        comparison = finding.get("comparison")
        if comparison and comparison not in constants.COMPARISON_VALUES:
            comparison = None

        findings_list.append(
            {
                "finding_id": f"{series_uuid}_{i:03d}",
                "text": finding.get("text", ""),
                "clinical_status": clinical_status,
                "comparison": comparison,
                "measurements": measurements,
            }
        )

    return findings_list


def write_findings_output(series_uuid: str, findings_list: list[dict[str, object]], findings_dir: Path) -> None:
    """Write findings list to JSON file."""
    findings_output = findings_dir / f"{series_uuid}.json"
    io.save_json(findings_list, findings_output)


def copy_findings_from_directory(
    source_dir: Path,
    target_dir: Path,
    logger_instance: logging.Logger | None = None,
    series_uuid_list: Sequence[str] | None = None,
) -> int:
    """Copy and filter findings files from source to target directory."""
    logger_inst = io.get_logger(logger_instance)

    if not source_dir.exists():
        logger_inst.warning("Source findings directory does not exist: %s", source_dir)
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    copied_count = 0
    skipped_count = 0

    # Create set for O(1) lookup if filtering by series_uuid
    series_uuid_set = set(series_uuid_list) if series_uuid_list else None

    for findings_file in source_dir.glob("*.json"):
        series_uuid = findings_file.stem

        # Filter by series_uuid if list provided
        if series_uuid_set is not None and series_uuid not in series_uuid_set:
            continue

        target_file = target_dir / f"{series_uuid}.json"

        if target_file.exists():
            skipped_count += 1
            continue

        try:
            findings_list = io.load_json(findings_file, raise_on_error=True)
            if not isinstance(findings_list, list):
                logger_inst.warning("Skipping %s: not a list", findings_file.name)
                continue

            # Filter findings to only include needed fields
            filtered_findings = [
                prompts.filter_finding_fields(finding) for finding in findings_list if isinstance(finding, dict)
            ]

            # Write filtered findings
            write_findings_output(series_uuid, filtered_findings, target_dir)
            copied_count += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger_inst.warning("Failed to copy findings from %s: %s", findings_file.name, exc)
            continue

    if copied_count > 0:
        logger_inst.info("Copied %d findings files from %s", copied_count, source_dir)
    if skipped_count > 0:
        logger_inst.info("Skipped %d findings files that already have outputs", skipped_count)

    return copied_count


def log_completion_stats(
    total_reports: int,
    processed_reports: int,
    skipped_reports: int,
    failed_reports: int,
    total_findings: int,
    findings_dir: Path,
    logger_instance: logging.Logger | None = None,
) -> None:
    """Log completion statistics."""
    logger_inst = io.get_logger(logger_instance)

    avg = total_findings / processed_reports if processed_reports else 0

    logger_inst.info("=" * 90)
    logger_inst.info("COMPLETE")
    logger_inst.info(f"  Total reports: {total_reports:6d}")
    logger_inst.info(f"    • processed: {processed_reports:6d}")
    logger_inst.info(f"    • skipped:   {skipped_reports:6d}")
    logger_inst.info(f"    • failed:    {failed_reports:6d}")
    logger_inst.info(f"  Total findings: {total_findings:6d}")
    logger_inst.info(f"  Average findings/report: {avg:.1f}")
    logger_inst.info(f"  Findings dir: {findings_dir}")
    logger_inst.info("=" * 90)


def setup_processing_context(
    reports_dir: Path,
    fewshot: str | None = None,
    limit: int | None = None,
) -> tuple[list[Path], Sequence[dict[str, object]]]:
    """Set up processing context: find report files and load few-shot examples."""
    logger = logging.getLogger(__name__)

    if not reports_dir.exists():
        raise FileNotFoundError(f"Reports directory not found: {reports_dir}")

    examples_list: Sequence[dict[str, object]] = []
    if fewshot:
        examples_list = prompts.load_fewshot(fewshot)
        if examples_list:
            logger.info(f"Loaded {len(examples_list)} few-shot examples for '{fewshot}'")
        else:
            logger.info("No few-shot examples loaded")

    # Find report files
    report_files = io.find_report_files(reports_dir)
    if not report_files:
        raise ValueError(f"No .txt reports found in {reports_dir}")

    # Apply limit if specified
    if limit is not None:
        report_files = report_files[:limit]
        logger.info(f"Limited processing to first {len(report_files)} reports")

    return report_files, examples_list


def copy_reports_directory(
    source_dir: Path,
    target_dir: Path,
    logger_instance: logging.Logger | None = None,
    series_uuid_list: Sequence[str] | None = None,
) -> int:
    """Copy report .txt files from source to target directory."""
    logger_inst = io.get_logger(logger_instance)

    if not source_dir.exists():
        logger_inst.warning("Source reports directory does not exist: %s", source_dir)
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    copied_count = 0

    # Create set for O(1) lookup if filtering by series_uuid
    series_uuid_set = set(series_uuid_list) if series_uuid_list else None

    for report_file in source_dir.glob("*.txt"):
        series_uuid = report_file.stem

        # Filter by series_uuid if list provided
        if series_uuid_set is not None and series_uuid not in series_uuid_set:
            continue

        target_file = target_dir / report_file.name

        try:
            shutil.copy2(report_file, target_file)
            copied_count += 1
        except (OSError, PermissionError, shutil.SameFileError) as exc:
            logger_inst.warning("Failed to copy report from %s: %s", report_file.name, exc)
            continue

    if copied_count > 0:
        logger_inst.info("Copied %d report files from %s to %s", copied_count, source_dir, target_dir)

    return copied_count
