"""Metrics computation for findings evaluation."""

from __future__ import annotations

import logging
from collections import defaultdict

from radmatch import constants
from radmatch.evaluation import eval_utils

logger = logging.getLogger(__name__)


def _get_gt_finding_id(gt_finding: dict[str, object], index: int) -> str:
    """Get GT finding ID, generating synthetic ID if missing.

    Uses the same synthetic ID scheme as match_findings_llm: gt_{index+1}
    to ensure consistent ID matching between matching and metrics computation.

    Args:
        gt_finding: Ground truth finding dictionary
        index: Zero-based index of the finding in the list

    Returns:
        Finding ID (original or synthetic like "gt_1", "gt_2", etc.)
    """
    finding_id = gt_finding.get("finding_id")
    if finding_id:
        return str(finding_id)
    return f"gt_{index + 1}"


def get_finding_type(finding: dict) -> str | None:
    """Categorize finding by type based on its attributes."""
    has_comparison = finding.get("comparison") is not None
    has_measurements = bool(finding.get("measurements"))
    clinical_status_raw = finding.get("clinical_status", constants.DEFAULT_CLINICAL_STATUS)
    clinical_status = (
        clinical_status_raw
        if clinical_status_raw in constants.CLINICAL_STATUS_VALUES
        else constants.DEFAULT_CLINICAL_STATUS
    )

    if has_measurements:
        return constants.FINDING_TYPE_MEASUREMENT

    if has_comparison and not has_measurements:
        return constants.FINDING_TYPE_LONGITUDINAL

    if clinical_status == "normal":
        return constants.FINDING_TYPE_NORMAL_REGULAR

    if clinical_status == "abnormal":
        return constants.FINDING_TYPE_ABNORMAL_REGULAR

    # Should not reach here, but return None as fallback
    return None


def compute_f1_score(tp: int, fp: int, fn: int) -> float:
    """Compute F1 score from TP, FP, FN."""
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    denominator = 2 * tp + fp + fn
    if denominator == 0:
        return 0.0
    return (2 * tp) / denominator


def compute_precision(tp: int, fp: int) -> float:
    """Compute precision from TP, FP."""
    denominator = tp + fp
    if denominator == 0:
        return 0.0
    return tp / denominator


def compute_recall(tp: int, fn: int) -> float:
    """Compute recall from TP, FN."""
    denominator = tp + fn
    if denominator == 0:
        return 0.0
    return tp / denominator


def _average(values_list: list[float]) -> float:
    """Compute average value for a list."""
    if not values_list:
        return 0.0
    return sum(values_list) / len(values_list)


def compute_category_metrics(
    stats: dict[str, int],
    gt_count: int | None = None,
    pred_count: int | None = None,
    empty_is_perfect: bool = False,
) -> dict[str, float | int | None]:
    """Compute precision, recall, and F1 for a category/label from stats."""
    tp = stats.get("tp", 0)
    fp = stats.get("fp", 0)
    fn = stats.get("fn", 0)

    if gt_count is None:
        gt_count = tp + fn
    if pred_count is None:
        pred_count = tp + fp

    if gt_count == 0:
        if tp + fp + fn == 0:
            if empty_is_perfect:
                return {
                    "precision": 1.0,
                    "recall": 1.0,
                    "f1": 1.0,
                    "gt_count": gt_count,
                    "pred_count": pred_count,
                }
            return {
                "precision": None,
                "recall": None,
                "f1": None,
                "gt_count": gt_count,
                "pred_count": pred_count,
            }
        return {
            "precision": 0.0,
            "recall": None,
            "f1": 0.0,
            "gt_count": gt_count,
            "pred_count": pred_count,
        }

    return {
        "precision": compute_precision(tp, fp),
        "recall": compute_recall(tp, fn),
        "f1": compute_f1_score(tp, fp, fn),
        "gt_count": gt_count,
        "pred_count": pred_count,
    }


def compute_report_metrics(
    gt_findings_list: list[dict[str, object]],
    pred_findings_list: list[dict[str, object]],
    matching_results: dict[str, dict[str, object]],
) -> dict[str, dict[str, float | int | None]]:
    """Compute per-type and overall metrics for a single report."""
    pred_id_to_type = {
        finding.get("finding_id", ""): finding_type
        for finding in pred_findings_list
        if (finding_type := get_finding_type(finding)) is not None
    }

    gt_id_to_type: dict[str, str] = {}
    for index, finding in enumerate(gt_findings_list):
        finding_type = get_finding_type(finding)
        if finding_type is None:
            continue
        gt_id_to_type[_get_gt_finding_id(finding, index)] = finding_type

    finding_type_to_stats: dict[str, dict[str, int]] = {
        finding_type: {"tp": 0, "fp": 0, "fn": 0} for finding_type in constants.FINDING_TYPES
    }
    finding_type_to_counts: dict[str, dict[str, int]] = {
        finding_type: {"gt": 0, "pred": 0} for finding_type in constants.FINDING_TYPES
    }
    matched_gt_ids: set[str] = set()

    for finding in pred_findings_list:
        finding_type = get_finding_type(finding)
        if finding_type is None:
            continue
        finding_type_to_counts[finding_type]["pred"] += 1

    for finding in gt_findings_list:
        finding_type = get_finding_type(finding)
        if finding_type is None:
            continue
        finding_type_to_counts[finding_type]["gt"] += 1

    for pred_id, match_info in matching_results.items():
        if not isinstance(match_info, dict):
            continue
        corresponding_gt_id = match_info.get("corresponding_gt_finding_id")
        if match_info.get("matched") and corresponding_gt_id:
            matched_gt_ids.add(str(corresponding_gt_id))

        finding_type = pred_id_to_type.get(pred_id)
        if finding_type is None:
            continue
        if match_info.get("matched"):
            finding_type_to_stats[finding_type]["tp"] += 1
        else:
            finding_type_to_stats[finding_type]["fp"] += 1

    for pred_id, finding_type in pred_id_to_type.items():
        if pred_id not in matching_results:
            finding_type_to_stats[finding_type]["fp"] += 1

    for gt_id, finding_type in gt_id_to_type.items():
        if gt_id not in matched_gt_ids:
            finding_type_to_stats[finding_type]["fn"] += 1

    finding_type_to_metrics: dict[str, dict[str, float | int | None]] = {}
    for finding_type in constants.FINDING_TYPES:
        finding_type_stats = finding_type_to_stats[finding_type]
        type_metrics = compute_category_metrics(finding_type_stats, empty_is_perfect=True)
        finding_type_to_metrics[finding_type] = {
            "gt_count": type_metrics["gt_count"],
            "pred_count": type_metrics["pred_count"],
            "precision": type_metrics["precision"],
            "recall": type_metrics["recall"],
            "f1": type_metrics["f1"],
            "tp": finding_type_stats["tp"],
            "fp": finding_type_stats["fp"],
            "fn": finding_type_stats["fn"],
        }

    overall_tp = sum(stats["tp"] for stats in finding_type_to_stats.values())
    overall_fp = sum(stats["fp"] for stats in finding_type_to_stats.values())
    overall_fn = sum(stats["fn"] for stats in finding_type_to_stats.values())
    overall_metrics = compute_category_metrics(
        {"tp": overall_tp, "fp": overall_fp, "fn": overall_fn}, empty_is_perfect=True
    )
    finding_type_to_metrics["__overall__"] = {
        "gt_count": overall_metrics["gt_count"],
        "pred_count": overall_metrics["pred_count"],
        "precision": overall_metrics["precision"],
        "recall": overall_metrics["recall"],
        "f1": overall_metrics["f1"],
        "tp": overall_tp,
        "fp": overall_fp,
        "fn": overall_fn,
    }

    return finding_type_to_metrics


def compute_report_measurement_metrics(
    gt_findings_list: list[dict[str, object]],
    pred_findings_list: list[dict[str, object]],
    matching_results: dict[str, dict[str, object]],
    measurement_type_metrics: dict[str, float | int | None],
) -> dict[str, dict[str, float | int | None]]:
    """Compute per-report measurement metrics including MRE."""
    pred_id_to_finding: dict[str, dict[str, object]] = {f.get("finding_id", ""): f for f in pred_findings_list}
    gt_id_to_finding: dict[str, dict[str, object]] = {
        _get_gt_finding_id(f, i): f for i, f in enumerate(gt_findings_list)
    }

    measurement_category_stats: dict[str, dict[str, int]] = {
        category: {"tp": 0, "fp": 0, "fn": 0} for category in constants.MEASUREMENT_CATEGORY_ORDER
    }
    measurement_category_counts: dict[str, dict[str, int]] = {
        category: {"pred": 0, "gt": 0} for category in constants.MEASUREMENT_CATEGORY_ORDER
    }
    category_to_mres: dict[str, list[float]] = {category: [] for category in constants.MEASUREMENT_CATEGORY_ORDER}
    all_mres_list: list[float] = []

    matched_gt_ids = {
        match_result.get("corresponding_gt_finding_id")
        for match_result in matching_results.values()
        if match_result.get("matched")
    }
    matched_gt_ids.discard(None)

    for pred_finding in pred_findings_list:
        if get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
            continue
        measurements = pred_finding.get("measurements", [])
        if not measurements:
            continue
        categories = MetricsAggregator._extract_measurement_categories(measurements, deduplicate=True)
        for category in categories:
            measurement_category_counts[category]["pred"] += 1

    for gt_finding in gt_findings_list:
        if get_finding_type(gt_finding) != constants.FINDING_TYPE_MEASUREMENT:
            continue
        measurements = gt_finding.get("measurements", [])
        if not measurements:
            continue
        categories = MetricsAggregator._extract_measurement_categories(measurements, deduplicate=True)
        for category in categories:
            measurement_category_counts[category]["gt"] += 1

    for finding_id, match_result in matching_results.items():
        pred_finding = pred_id_to_finding.get(finding_id)
        if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
            continue
        pred_measurements = pred_finding.get("measurements", [])
        pred_categories = MetricsAggregator._extract_measurement_categories(pred_measurements)
        if not pred_categories:
            continue

        if match_result.get("matched"):
            corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
            gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
            if gt_finding:
                gt_measurements = gt_finding.get("measurements", [])
                gt_categories = MetricsAggregator._extract_measurement_categories(gt_measurements)
                for category in pred_categories:
                    if category in gt_categories:
                        measurement_category_stats[category]["tp"] += 1
                    else:
                        measurement_category_stats[category]["fp"] += 1
                for category in gt_categories:
                    if category not in pred_categories:
                        measurement_category_stats[category]["fn"] += 1
            else:
                for category in pred_categories:
                    measurement_category_stats[category]["fp"] += 1
        else:
            for category in pred_categories:
                measurement_category_stats[category]["fp"] += 1

    for index, gt_finding in enumerate(gt_findings_list):
        if get_finding_type(gt_finding) != constants.FINDING_TYPE_MEASUREMENT:
            continue
        gt_id = _get_gt_finding_id(gt_finding, index)
        if gt_id in matched_gt_ids:
            continue
        gt_measurements = gt_finding.get("measurements", [])
        if not gt_measurements:
            continue
        gt_categories = MetricsAggregator._extract_measurement_categories(gt_measurements)
        for category in gt_categories:
            measurement_category_stats[category]["fn"] += 1

    for finding_id, match_result in matching_results.items():
        pred_finding = pred_id_to_finding.get(finding_id)
        if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
            continue
        if not match_result.get("matched"):
            continue
        corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
        gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
        if not gt_finding:
            continue
        gt_measurements = gt_finding.get("measurements", [])
        pred_measurements = pred_finding.get("measurements", [])
        if not gt_measurements or not pred_measurements:
            continue
        comparisons = eval_utils.compare_measurements(gt_measurements, pred_measurements)
        for comp in comparisons:
            mre = comp.get("mre")
            category = comp.get("category")
            if mre is not None and isinstance(mre, (int, float)) and category:
                mre_float = float(mre)
                category_str = str(category)
                if category_str in category_to_mres:
                    category_to_mres[category_str].append(mre_float)
                all_mres_list.append(mre_float)

    category_to_metrics: dict[str, dict[str, float | int | None]] = {}
    category_mres_for_macro_list: list[float] = []
    for category in constants.MEASUREMENT_CATEGORY_ORDER:
        stats = measurement_category_stats[category]
        gt_count = measurement_category_counts[category]["gt"]
        pred_count = measurement_category_counts[category]["pred"]
        matching_metrics = compute_category_metrics(stats, gt_count=gt_count, pred_count=pred_count)
        mre_list = category_to_mres.get(category, [])
        avg_mre = _average(mre_list) if mre_list else None
        if mre_list:
            category_mres_for_macro_list.append(avg_mre)
        category_to_metrics[category] = {
            **matching_metrics,
            "mre": avg_mre,
        }

    micro_mre = _average(all_mres_list)
    macro_mre = _average(category_mres_for_macro_list)

    macro_precisions_list = [
        metrics["precision"] for metrics in category_to_metrics.values() if metrics.get("precision") is not None
    ]
    macro_recalls_list = [
        metrics["recall"] for metrics in category_to_metrics.values() if metrics.get("recall") is not None
    ]
    macro_f1s_list = [metrics["f1"] for metrics in category_to_metrics.values() if metrics.get("f1") is not None]

    micro_averaged = {
        "precision": measurement_type_metrics.get("precision"),
        "recall": measurement_type_metrics.get("recall"),
        "f1": measurement_type_metrics.get("f1"),
        "gt_count": measurement_type_metrics.get("gt_count"),
        "pred_count": measurement_type_metrics.get("pred_count"),
        "mre": micro_mre,
    }
    macro_averaged = {
        "precision": _average(macro_precisions_list),
        "recall": _average(macro_recalls_list),
        "f1": _average(macro_f1s_list),
        "gt_count": measurement_type_metrics.get("gt_count"),
        "pred_count": measurement_type_metrics.get("pred_count"),
        "mre": macro_mre,
    }

    return {
        "micro_averaged": micro_averaged,
        "macro_averaged": macro_averaged,
        "per_category": category_to_metrics,
    }


def compute_report_longitudinal_metrics(
    gt_findings_list: list[dict[str, object]],
    pred_findings_list: list[dict[str, object]],
    matching_results: dict[str, dict[str, object]],
) -> dict[str, dict[str, float | int | None]]:
    """Compute per-report longitudinal metrics."""

    def normalize_comparison(comparison: object) -> str | None:
        if not comparison:
            return None
        normalized = str(comparison).strip().lower()
        return normalized if normalized in constants.COMPARISON_VALUES else None

    matching_results_map = matching_results if isinstance(matching_results, dict) else {}
    pred_id_to_finding: dict[str, dict[str, object]] = {f.get("finding_id", ""): f for f in pred_findings_list}
    gt_id_to_finding: dict[str, dict[str, object]] = {
        _get_gt_finding_id(f, i): f for i, f in enumerate(gt_findings_list)
    }

    matched_gt_ids = {
        match_result.get("corresponding_gt_finding_id")
        for match_result in matching_results_map.values()
        if match_result.get("matched")
    }
    matched_gt_ids.discard(None)

    matched_longitudinal_list: list[tuple[dict[str, object], dict[str, object]]] = []
    for finding_id, match_result in matching_results_map.items():
        pred_finding = pred_id_to_finding.get(finding_id)
        if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_LONGITUDINAL:
            continue
        if match_result.get("matched"):
            corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
            gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
            if gt_finding:
                matched_longitudinal_list.append((pred_finding, gt_finding))

    category_to_stats: dict[str, dict[str, int]] = {
        label: {"tp": 0, "fp": 0, "fn": 0} for label in constants.COMPARISON_VALUES_ORDER
    }
    category_precisions_list: list[float] = []
    category_recalls_list: list[float] = []
    category_f1s_list: list[float] = []

    for pred_finding, gt_finding in matched_longitudinal_list:
        pred_comparison = normalize_comparison(pred_finding.get("comparison"))
        gt_comparison = normalize_comparison(gt_finding.get("comparison"))

        if not gt_comparison:
            if pred_comparison:
                category_to_stats[pred_comparison]["fp"] += 1
            continue

        if pred_comparison == gt_comparison:
            category_to_stats[gt_comparison]["tp"] += 1
        else:
            category_to_stats[gt_comparison]["fn"] += 1
            if pred_comparison:
                category_to_stats[pred_comparison]["fp"] += 1

    for pred_finding in pred_findings_list:
        if get_finding_type(pred_finding) != constants.FINDING_TYPE_LONGITUDINAL:
            continue
        finding_id = pred_finding.get("finding_id", "")
        if not matching_results_map.get(finding_id, {}).get("matched"):
            pred_comparison = normalize_comparison(pred_finding.get("comparison"))
            if pred_comparison:
                category_to_stats[pred_comparison]["fp"] += 1

    for gt_finding in gt_findings_list:
        if get_finding_type(gt_finding) != constants.FINDING_TYPE_LONGITUDINAL:
            continue
        gt_id = gt_finding.get("finding_id", "")
        if gt_id not in matched_gt_ids:
            gt_comparison = normalize_comparison(gt_finding.get("comparison"))
            if gt_comparison:
                category_to_stats[gt_comparison]["fn"] += 1

    category_to_metrics: dict[str, dict[str, float | int | None]] = {}
    for label in constants.COMPARISON_VALUES_ORDER:
        label_stats = category_to_stats[label]
        label_metrics = compute_category_metrics(label_stats)
        category_to_metrics[label] = {
            "precision": label_metrics["precision"],
            "recall": label_metrics["recall"],
            "f1": label_metrics["f1"],
            "gt_count": label_metrics["gt_count"],
            "pred_count": label_metrics["pred_count"],
        }

        if (
            label_metrics["precision"] is not None
            and label_metrics["recall"] is not None
            and label_metrics["f1"] is not None
        ):
            category_precisions_list.append(label_metrics["precision"])
            category_recalls_list.append(label_metrics["recall"])
            category_f1s_list.append(label_metrics["f1"])

    macro_averaged = {
        "precision": _average(category_precisions_list),
        "recall": _average(category_recalls_list),
        "f1": _average(category_f1s_list),
    }

    micro_aggregated_tp = sum(stats["tp"] for stats in category_to_stats.values())
    micro_aggregated_fp = sum(stats["fp"] for stats in category_to_stats.values())
    micro_aggregated_fn = sum(stats["fn"] for stats in category_to_stats.values())
    micro_metrics = compute_category_metrics(
        {"tp": micro_aggregated_tp, "fp": micro_aggregated_fp, "fn": micro_aggregated_fn},
        empty_is_perfect=True,
    )
    micro_averaged = {
        "precision": micro_metrics["precision"],
        "recall": micro_metrics["recall"],
        "f1": micro_metrics["f1"],
        "gt_count": micro_metrics["gt_count"],
        "pred_count": micro_metrics["pred_count"],
    }

    macro_averaged["gt_count"] = micro_averaged.get("gt_count", 0)
    macro_averaged["pred_count"] = micro_averaged.get("pred_count", 0)

    return {
        "micro_averaged": micro_averaged,
        "macro_averaged": macro_averaged,
        "per_category": category_to_metrics,
    }


class MetricsAggregator:
    """Aggregate metrics across multiple reports."""

    def __init__(self) -> None:
        """Initialize empty aggregator."""
        self.report_stats_list: list[dict[str, int]] = []
        self.global_tp = 0
        self.global_fp = 0
        self.global_fn = 0
        self.finding_type_to_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        self.total_pred_findings = 0
        self.total_gt_findings = 0
        self.finding_type_to_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"pred": 0, "gt": 0})
        # Longitudinal metrics tracking
        self.longitudinal_label_match_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"tp": 0, "fp": 0, "fn": 0}
        )
        # Measurement category tracking
        self.measurement_mre_by_category: dict[str, list[float]] = defaultdict(list)
        self.measurement_category_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        self.measurement_category_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"pred": 0, "gt": 0})

    @staticmethod
    def _extract_measurement_categories(measurements: list[dict[str, object]], deduplicate: bool = False) -> set[str]:
        """Extract measurement categories from a list of measurements."""
        categories: set[str] = set()
        categories_seen: set[str] = set() if deduplicate else set()

        for m in measurements:
            if isinstance(m, dict):
                category = m.get("category", constants.DEFAULT_MEASUREMENT_CATEGORY)
                if category in constants.MEASUREMENT_CATEGORY_VALUES:
                    category_str = str(category)
                    if deduplicate:
                        if category_str not in categories_seen:
                            categories.add(category_str)
                            categories_seen.add(category_str)
                    else:
                        categories.add(category_str)

        return categories

    def add_report(
        self,
        report_stats: dict[str, int],
        pred_findings_list: list[dict[str, object]],
        gt_findings_list: list[dict[str, object]],
        matching_results: dict[str, dict[str, object]],
        precomputed_per_type_stats: dict[str, dict[str, int]],
    ) -> None:
        """Add statistics from a single report."""
        self.report_stats_list.append(report_stats.copy())
        self.global_tp += report_stats["tp"]
        self.global_fp += report_stats["fp"]
        self.global_fn += report_stats["fn"]
        self.total_pred_findings += report_stats.get("pred_count", len(pred_findings_list))
        self.total_gt_findings += report_stats.get("gt_count", len(gt_findings_list))

        for finding_type in constants.FINDING_TYPES:
            type_stats = precomputed_per_type_stats.get(finding_type, {})
            self.finding_type_to_counts[finding_type]["pred"] += type_stats.get("pred", 0)
            self.finding_type_to_counts[finding_type]["gt"] += type_stats.get("gt", 0)
            self.finding_type_to_stats[finding_type]["tp"] += type_stats.get("tp", 0)
            self.finding_type_to_stats[finding_type]["fp"] += type_stats.get("fp", 0)
            self.finding_type_to_stats[finding_type]["fn"] += type_stats.get("fn", 0)

        pred_id_to_finding: dict[str, dict[str, object]] = {f.get("finding_id", ""): f for f in pred_findings_list}
        gt_id_to_finding: dict[str, dict[str, object]] = {
            _get_gt_finding_id(f, i): f for i, f in enumerate(gt_findings_list)
        }
        matched_gt_ids = {
            match_result.get("corresponding_gt_finding_id")
            for match_result in matching_results.values()
            if match_result.get("matched")
        }
        matched_gt_ids.discard(None)

        for finding_id, match_result in matching_results.items():
            pred_finding = pred_id_to_finding.get(finding_id)
            if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_LONGITUDINAL:
                continue

            if not match_result.get("matched"):
                continue

            corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
            gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
            if not gt_finding:
                continue

            pred_comparison = eval_utils.normalize_comparison(pred_finding.get("comparison"))
            gt_comparison = eval_utils.normalize_comparison(gt_finding.get("comparison"))

            if pred_comparison and gt_comparison:
                if pred_comparison == gt_comparison:
                    self.longitudinal_label_match_stats[gt_comparison]["tp"] += 1
                else:
                    self.longitudinal_label_match_stats[pred_comparison]["fp"] += 1
                    self.longitudinal_label_match_stats[gt_comparison]["fn"] += 1
            elif pred_comparison:
                self.longitudinal_label_match_stats[pred_comparison]["fp"] += 1
            elif gt_comparison:
                self.longitudinal_label_match_stats[gt_comparison]["fn"] += 1

        for pred_finding in pred_findings_list:
            if get_finding_type(pred_finding) != constants.FINDING_TYPE_LONGITUDINAL:
                continue
            finding_id = pred_finding.get("finding_id", "")
            if not matching_results.get(finding_id, {}).get("matched"):
                pred_comparison = eval_utils.normalize_comparison(pred_finding.get("comparison"))
                if pred_comparison:
                    self.longitudinal_label_match_stats[pred_comparison]["fp"] += 1

        for i, gt_finding in enumerate(gt_findings_list):
            if get_finding_type(gt_finding) != constants.FINDING_TYPE_LONGITUDINAL:
                continue
            gt_id = _get_gt_finding_id(gt_finding, i)
            if gt_id not in matched_gt_ids:
                gt_comparison = eval_utils.normalize_comparison(gt_finding.get("comparison"))
                if gt_comparison:
                    self.longitudinal_label_match_stats[gt_comparison]["fn"] += 1

        # Track measurement category finding counts
        for pred_finding in pred_findings_list:
            if get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
                continue
            measurements = pred_finding.get("measurements", [])
            if not measurements:
                continue
            categories = self._extract_measurement_categories(measurements, deduplicate=True)
            for category in categories:
                self.measurement_category_counts[category]["pred"] += 1

        for gt_finding in gt_findings_list:
            if get_finding_type(gt_finding) != constants.FINDING_TYPE_MEASUREMENT:
                continue
            measurements = gt_finding.get("measurements", [])
            if not measurements:
                continue
            categories = self._extract_measurement_categories(measurements, deduplicate=True)
            for category in categories:
                self.measurement_category_counts[category]["gt"] += 1

        # Track measurement category TP/FP/FN

        for finding_id, match_result in matching_results.items():
            pred_finding = pred_id_to_finding.get(finding_id)
            if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
                continue

            pred_measurements = pred_finding.get("measurements", [])
            pred_categories = self._extract_measurement_categories(pred_measurements)
            if not pred_categories:
                continue

            if match_result.get("matched"):
                corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
                gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
                if gt_finding:
                    gt_measurements = gt_finding.get("measurements", [])
                    gt_categories = self._extract_measurement_categories(gt_measurements)

                    for category in pred_categories:
                        if category in gt_categories:
                            self.measurement_category_stats[category]["tp"] += 1
                        else:
                            self.measurement_category_stats[category]["fp"] += 1
                    for category in gt_categories:
                        if category not in pred_categories:
                            self.measurement_category_stats[category]["fn"] += 1
                else:
                    for category in pred_categories:
                        self.measurement_category_stats[category]["fp"] += 1
            else:
                for category in pred_categories:
                    self.measurement_category_stats[category]["fp"] += 1

        for i, gt_finding in enumerate(gt_findings_list):
            if get_finding_type(gt_finding) != constants.FINDING_TYPE_MEASUREMENT:
                continue
            gt_id = _get_gt_finding_id(gt_finding, i)
            if gt_id not in matched_gt_ids:
                gt_measurements = gt_finding.get("measurements", [])
                if not gt_measurements:
                    continue
                gt_categories = self._extract_measurement_categories(gt_measurements)
                for category in gt_categories:
                    self.measurement_category_stats[category]["fn"] += 1

        # Track measurement MRE for matched findings
        for finding_id, match_result in matching_results.items():
            pred_finding = pred_id_to_finding.get(finding_id)
            if not pred_finding or get_finding_type(pred_finding) != constants.FINDING_TYPE_MEASUREMENT:
                continue

            if not match_result.get("matched"):
                continue

            corresponding_gt_id = match_result.get("corresponding_gt_finding_id")
            gt_finding = gt_id_to_finding.get(corresponding_gt_id) if corresponding_gt_id else None
            if not gt_finding:
                continue

            gt_measurements = gt_finding.get("measurements", [])
            pred_measurements = pred_finding.get("measurements", [])

            if not gt_measurements or not pred_measurements:
                continue

            comparisons = eval_utils.compare_measurements(gt_measurements, pred_measurements)
            for comp in comparisons:
                mre = comp.get("mre")
                category = comp.get("category")
                if mre is not None and isinstance(mre, (int, float)) and category:
                    self.measurement_mre_by_category[str(category)].append(float(mre))

    def _compute_per_report_scores(self) -> tuple[list[float], list[float], list[float]]:
        """Compute F1, precision, and recall scores for each report."""
        f1_scores_list = []
        precision_scores_list = []
        recall_scores_list = []

        for stats in self.report_stats_list:
            tp = stats["tp"]
            fp = stats["fp"]
            fn = stats["fn"]

            if tp + fp + fn == 0:
                # Empty GT and empty predictions: perfect report. Keeps precision,
                # recall, and f1 consistent with compute_f1_score(0,0,0) == 1.0.
                f1_scores_list.append(1.0)
                precision_scores_list.append(1.0)
                recall_scores_list.append(1.0)
                continue

            f1_scores_list.append(compute_f1_score(tp, fp, fn))
            precision_scores_list.append(compute_precision(tp, fp))
            recall_scores_list.append(compute_recall(tp, fn))

        return f1_scores_list, precision_scores_list, recall_scores_list

    def compute_per_report_metrics(self) -> dict[str, float | int]:
        """Compute report-averaged F1, precision, and recall."""
        micro_metrics = compute_category_metrics(
            {"tp": self.global_tp, "fp": self.global_fp, "fn": self.global_fn}, empty_is_perfect=True
        )
        gt_count = micro_metrics["gt_count"]
        pred_count = micro_metrics["pred_count"]

        if not self.report_stats_list:
            return {
                "f1": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "gt_count": gt_count,
                "pred_count": pred_count,
            }

        f1_scores, precision_scores, recall_scores = self._compute_per_report_scores()

        return {
            "f1": _average(f1_scores),
            "precision": _average(precision_scores),
            "recall": _average(recall_scores),
            "gt_count": gt_count,
            "pred_count": pred_count,
        }

    def compute_report_level_statistics(self) -> dict[str, dict[str, float]]:
        """Compute report-level statistics (avg, min, max, std) for F1, precision, recall."""
        if not self.report_stats_list:
            return {
                "f1": {"avg": 0.0, "std": 0.0, "median": 0.0, "min": 0.0, "max": 0.0},
                "precision": {"avg": 0.0, "std": 0.0, "median": 0.0, "min": 0.0, "max": 0.0},
                "recall": {"avg": 0.0, "std": 0.0, "median": 0.0, "min": 0.0, "max": 0.0},
            }

        f1_scores, precision_scores, recall_scores = self._compute_per_report_scores()

        def compute_stats(values: list[float]) -> dict[str, float]:
            if not values:
                return {"avg": 0.0, "std": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
            mean_val = _average(values)
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_val = variance**0.5
            sorted_values = sorted(values)
            n = len(sorted_values)
            if n % 2 == 0:
                median_val = (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2.0
            else:
                median_val = sorted_values[n // 2]
            return {
                "avg": mean_val,
                "std": std_val,
                "median": median_val,
                "min": min(values),
                "max": max(values),
            }

        return {
            "f1": compute_stats(f1_scores),
            "precision": compute_stats(precision_scores),
            "recall": compute_stats(recall_scores),
        }

    def compute_micro_metrics(self) -> dict[str, float | int | None]:
        """Compute global micro-averaged F1, precision, and recall."""
        micro_metrics = compute_category_metrics(
            {"tp": self.global_tp, "fp": self.global_fp, "fn": self.global_fn}, empty_is_perfect=True
        )
        return {
            **micro_metrics,
            "count": micro_metrics["gt_count"],
        }

    def compute_per_type_metrics(self) -> dict[str, dict[str, float | int | None]]:
        """Compute per-type metrics for each finding type."""
        type_to_metrics: dict[str, dict[str, float | int | None]] = {}

        for finding_type in constants.FINDING_TYPES:
            finding_type_stats = self.finding_type_to_stats.get(finding_type, {"tp": 0, "fp": 0, "fn": 0})
            gt_count = self.finding_type_to_counts.get(finding_type, {}).get("gt", 0)
            pred_count = self.finding_type_to_counts.get(finding_type, {}).get("pred", 0)

            metrics = compute_category_metrics(
                finding_type_stats, gt_count=gt_count, pred_count=pred_count, empty_is_perfect=True
            )
            type_to_metrics[finding_type] = {
                "f1": metrics["f1"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "gt_count": metrics["gt_count"],
                "pred_count": metrics["pred_count"],
            }

        return type_to_metrics

    def compute_longitudinal_metrics(self) -> dict[str, dict[str, float | int]]:
        """Compute longitudinal-specific metrics including comparison label accuracy."""
        label_to_metrics: dict[str, dict[str, float | int | None]] = {}
        label_precisions_for_macro_list: list[float] = []
        label_recalls_for_macro_list: list[float] = []
        label_f1s_for_macro_list: list[float] = []

        for label in constants.COMPARISON_VALUES_ORDER:
            label_stats = self.longitudinal_label_match_stats.get(label, {"tp": 0, "fp": 0, "fn": 0})
            metrics = compute_category_metrics(label_stats)

            label_to_metrics[label] = metrics

            if metrics["precision"] is not None:
                label_precisions_for_macro_list.append(metrics["precision"])
                label_recalls_for_macro_list.append(metrics["recall"])
                label_f1s_for_macro_list.append(metrics["f1"])

        # Compute micro-averaged metrics (aggregated TP/FP/FN across all labels)
        micro_aggregated_tp = sum(stats["tp"] for stats in self.longitudinal_label_match_stats.values())
        micro_aggregated_fp = sum(stats["fp"] for stats in self.longitudinal_label_match_stats.values())
        micro_aggregated_fn = sum(stats["fn"] for stats in self.longitudinal_label_match_stats.values())

        micro_metrics = compute_category_metrics(
            {"tp": micro_aggregated_tp, "fp": micro_aggregated_fp, "fn": micro_aggregated_fn},
            empty_is_perfect=True,
        )
        micro_averaged = {
            "precision": micro_metrics["precision"],
            "recall": micro_metrics["recall"],
            "f1": micro_metrics["f1"],
            "gt_count": micro_metrics["gt_count"],
            "pred_count": micro_metrics["pred_count"],
        }

        # Compute macro-averaged metrics (average of per-category metrics)
        macro_averaged = {
            "precision": _average(label_precisions_for_macro_list),
            "recall": _average(label_recalls_for_macro_list),
            "f1": _average(label_f1s_for_macro_list),
        }

        return {
            "micro_averaged": micro_averaged,
            "macro_averaged": macro_averaged,
            "per_category": label_to_metrics,
        }

    def compute_measurement_metrics(self) -> dict[str, dict[str, float | int]]:
        """Compute matching metrics (precision/recall/F1) and MRE metrics for measurements per category."""
        category_to_mres: dict[str, list[float]] = {}
        all_mres_list: list[float] = []

        for category, mre_list in self.measurement_mre_by_category.items():
            if mre_list:
                category_to_mres[category] = mre_list
                all_mres_list.extend(mre_list)

        # Compute per-category metrics
        category_to_metrics: dict[str, dict[str, float | int | None]] = {}
        category_mres_for_macro_list: list[float] = []

        for category in constants.MEASUREMENT_CATEGORY_ORDER:
            category_stats = self.measurement_category_stats.get(category, {"tp": 0, "fp": 0, "fn": 0})
            gt_count = self.measurement_category_counts.get(category, {}).get("gt", 0)
            pred_count = self.measurement_category_counts.get(category, {}).get("pred", 0)

            matching_metrics = compute_category_metrics(category_stats, gt_count=gt_count, pred_count=pred_count)

            mre_list = category_to_mres.get(category, [])
            avg_mre = _average(mre_list) if mre_list else None

            if mre_list:
                category_mres_for_macro_list.append(avg_mre)

            category_to_metrics[category] = {
                **matching_metrics,
                "mre": avg_mre,
            }

        micro_aggregated_tp = sum(stats["tp"] for stats in self.measurement_category_stats.values())
        micro_aggregated_fp = sum(stats["fp"] for stats in self.measurement_category_stats.values())
        micro_aggregated_fn = sum(stats["fn"] for stats in self.measurement_category_stats.values())
        micro_aggregated_gt = sum(counts["gt"] for counts in self.measurement_category_counts.values())
        micro_aggregated_pred = sum(counts["pred"] for counts in self.measurement_category_counts.values())

        micro_metrics = compute_category_metrics(
            {"tp": micro_aggregated_tp, "fp": micro_aggregated_fp, "fn": micro_aggregated_fn},
            gt_count=micro_aggregated_gt,
            pred_count=micro_aggregated_pred,
            empty_is_perfect=True,
        )

        micro_averaged = {
            "precision": micro_metrics["precision"],
            "recall": micro_metrics["recall"],
            "f1": micro_metrics["f1"],
            "gt_count": micro_metrics["gt_count"],
            "pred_count": micro_metrics["pred_count"],
            "mre": _average(all_mres_list),
        }

        macro_precisions_list = [
            metrics["precision"] for metrics in category_to_metrics.values() if metrics.get("precision") is not None
        ]
        macro_recalls_list = [
            metrics["recall"] for metrics in category_to_metrics.values() if metrics.get("recall") is not None
        ]
        macro_f1s_list = [metrics["f1"] for metrics in category_to_metrics.values() if metrics.get("f1") is not None]

        macro_mre = _average(category_mres_for_macro_list)

        macro_averaged = {
            "precision": _average(macro_precisions_list),
            "recall": _average(macro_recalls_list),
            "f1": _average(macro_f1s_list),
            "gt_count": micro_aggregated_gt,
            "pred_count": micro_aggregated_pred,
            "mre": macro_mre,
        }

        return {
            "micro_averaged": micro_averaged,
            "macro_averaged": macro_averaged,
            "per_category": category_to_metrics,
        }

    def get_summary(self) -> dict[str, dict[str, object]]:
        """Get complete metrics summary."""
        per_type_metrics = self.compute_per_type_metrics()
        longitudinal_metrics = self.compute_longitudinal_metrics()
        measurement_metrics = self.compute_measurement_metrics()

        measurement_metrics["macro_averaged"]["gt_count"] = measurement_metrics["micro_averaged"]["gt_count"]
        measurement_metrics["macro_averaged"]["pred_count"] = measurement_metrics["micro_averaged"]["pred_count"]

        finding_type_to_metrics = {
            finding_type: per_type_metrics[finding_type] for finding_type in constants.FINDING_TYPES
        }
        total_gt = sum(metrics_data.get("gt_count", 0) for metrics_data in finding_type_to_metrics.values())
        total_pred = sum(metrics_data.get("pred_count", 0) for metrics_data in finding_type_to_metrics.values())
        count_key_to_value = {"total_ground_truth": total_gt, "total_predicted": total_pred}

        return {
            "report_averaged": self.compute_per_report_metrics(),
            "micro_averaged": self.compute_micro_metrics(),
            constants.FINDING_TYPE_ABNORMAL_REGULAR: {
                "micro_averaged": per_type_metrics[constants.FINDING_TYPE_ABNORMAL_REGULAR],
            },
            constants.FINDING_TYPE_NORMAL_REGULAR: {
                "micro_averaged": per_type_metrics[constants.FINDING_TYPE_NORMAL_REGULAR],
            },
            "longitudinal": longitudinal_metrics,
            "measurement": measurement_metrics,
            "report_score_statistics": self.compute_report_level_statistics(),
            "findings_counts": {
                "gt": count_key_to_value["total_ground_truth"],
                "pred": count_key_to_value["total_predicted"],
                "tp": self.global_tp,
                "fp": self.global_fp,
                "fn": self.global_fn,
            },
        }
