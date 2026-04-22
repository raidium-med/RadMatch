"""Utility functions for evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path  # noqa: TC003
from typing import TypedDict

from radmatch import constants


class MeasurementDict(TypedDict, total=False):
    """TypedDict for measurement structure."""

    category: str
    value: float | int
    unit: str | None


class MeasurementComparisonDict(TypedDict, total=False):
    """TypedDict for measurement comparison result."""

    category: str
    gt_value: float
    pred_value: float
    mre: float | None
    gt_unit: str | None
    pred_unit: str | None


def normalize_comparison(comparison: str | None) -> str | None:
    """Normalize comparison value to lowercase and validate against constants."""
    if not comparison:
        return None
    normalized = str(comparison).strip().lower()
    return normalized if normalized in constants.COMPARISON_VALUES else None


def normalize_measurement_to_base_unit(value: float, unit: str | None, category: str) -> float | None:
    """Convert a measurement value to its base unit for comparison."""
    if unit is None:
        return value

    unit_lower = unit.lower().strip()
    conversion_factor = constants.MEASUREMENT_UNIT_CONVERSION.get(unit_lower)

    if conversion_factor is None:
        return value

    return value * conversion_factor


def compare_measurements(
    gt_measurements: list[MeasurementDict],
    pred_measurements: list[MeasurementDict],
) -> list[MeasurementComparisonDict]:
    """Compare measurements between GT and predicted findings.

    Returns list of comparison results, each with:
    - "category": measurement category
    - "gt_value": normalized GT value (in base unit)
    - "pred_value": normalized predicted value (in base unit)
    - "mre": Mean Relative Error (|pred - gt| / gt) if gt_value > 0, else None
    - "gt_unit": original GT unit
    - "pred_unit": original predicted unit

    Handles:
    - Unit conversion to base units for comparison
    - Multi-dimensional measurements (averages MRE per dimension)
    - Missing measurements (skipped)
    """
    if not gt_measurements or not pred_measurements:
        return []

    # Group measurements by category
    gt_by_category: dict[str, list[MeasurementDict]] = {}
    for m in gt_measurements:
        category = m.get("category", constants.DEFAULT_MEASUREMENT_CATEGORY)
        if category not in gt_by_category:
            gt_by_category[category] = []
        gt_by_category[category].append(m)

    pred_by_category: dict[str, list[MeasurementDict]] = {}
    for m in pred_measurements:
        category = m.get("category", constants.DEFAULT_MEASUREMENT_CATEGORY)
        if category not in pred_by_category:
            pred_by_category[category] = []
        pred_by_category[category].append(m)

    comparisons: list[MeasurementComparisonDict] = []

    # Compare measurements by category
    for category in set(gt_by_category.keys()) & set(pred_by_category.keys()):
        gt_list = gt_by_category[category]
        pred_list = pred_by_category[category]

        # For multi-dimensional measurements, match by position or average
        # Simple approach: take the minimum of lengths and compare pairwise
        min_len = min(len(gt_list), len(pred_list))

        # Normalize all values to base units
        gt_normalized: list[float] = []
        pred_normalized: list[float] = []

        for i in range(min_len):
            gt_m = gt_list[i]
            pred_m = pred_list[i]

            gt_value = gt_m.get("value")
            pred_value = pred_m.get("value")

            if not isinstance(gt_value, (int, float)) or not isinstance(pred_value, (int, float)):
                continue

            gt_unit = gt_m.get("unit")
            pred_unit = pred_m.get("unit")

            gt_norm = normalize_measurement_to_base_unit(float(gt_value), gt_unit, category)
            pred_norm = normalize_measurement_to_base_unit(float(pred_value), pred_unit, category)

            if gt_norm is not None and pred_norm is not None:
                gt_normalized.append(gt_norm)
                pred_normalized.append(pred_norm)

        if not gt_normalized or not pred_normalized:
            continue

        # Compute MRE per dimension, then average
        mre_list: list[float] = []
        for gt_val, pred_val in zip(gt_normalized, pred_normalized):
            if gt_val > 0:
                mre = abs(pred_val - gt_val) / gt_val
                mre_list.append(mre)

        # Always append comparison, with mre=None when gt_value is 0
        avg_mre = sum(mre_list) / len(mre_list) if mre_list else None
        # Use first measurement for unit info
        comparisons.append(
            {
                "category": category,
                "gt_value": gt_normalized[0],
                "pred_value": pred_normalized[0],
                "mre": avg_mre,
                "gt_unit": gt_list[0].get("unit"),
                "pred_unit": pred_list[0].get("unit"),
            }
        )

    return comparisons


def create_metadata(
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    model_name: str,
    execution_time_seconds: float | None = None,
    num_reports: int | None = None,
) -> dict[str, object]:
    """Create metadata dictionary for reproducibility.

    Args:
        findings_gt_dir: Path to ground truth findings directory
        findings_pred_dir: Path to predicted findings directory
        model_name: LLM model name used for evaluation
        execution_time_seconds: Execution time in seconds (optional)
        num_reports: Number of reports evaluated (optional)

    Returns:
        Metadata dictionary with timestamp, inputs, and optional fields
    """
    metadata: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "findings_gt": str(findings_gt_dir.resolve()),
            "findings_pred": str(findings_pred_dir.resolve()),
        },
        "config": {
            "llm_judge": model_name,
        },
    }

    if execution_time_seconds is not None:
        metadata["execution_time_seconds"] = execution_time_seconds

    if num_reports is not None:
        metadata["num_reports"] = num_reports

    return metadata
