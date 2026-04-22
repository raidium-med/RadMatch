"""Logging and printing functions for evaluation results."""

from __future__ import annotations

import logging

from radmatch import constants

logger = logging.getLogger(__name__)

_LABEL_WIDTH = 31
_NUM_WIDTH = 10
_FIRST_COLUMN_WIDTH = 15
_METRIC_COLUMN_WIDTH = 10
_RECALL_COLUMN_WIDTH = 7
_F1_COLUMN_WIDTH = 6
_MRE_COLUMN_WIDTH = 7
_TABLE_WIDTH = 90

_STANDARD_CONTENT_WIDTH = (
    3
    + _FIRST_COLUMN_WIDTH
    + 3
    + _NUM_WIDTH
    + 3
    + _NUM_WIDTH
    + 3
    + _METRIC_COLUMN_WIDTH
    + 3
    + _RECALL_COLUMN_WIDTH
    + 3
    + _F1_COLUMN_WIDTH
)
_MEASUREMENT_CONTENT_WIDTH = _STANDARD_CONTENT_WIDTH + 3 + _MRE_COLUMN_WIDTH
_STATS_CONTENT_WIDTH = 83

_STANDARD_COLUMN_WIDTHS = [
    _FIRST_COLUMN_WIDTH,
    _NUM_WIDTH,
    _NUM_WIDTH,
    _METRIC_COLUMN_WIDTH,
    _RECALL_COLUMN_WIDTH,
    _F1_COLUMN_WIDTH,
]
_STANDARD_PADDING = _TABLE_WIDTH - _STANDARD_CONTENT_WIDTH - 1

_MEASUREMENT_ROW_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_NUM_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_RECALL_COLUMN_WIDTH}s │ %{_F1_COLUMN_WIDTH}s │ "
    f"%{_MRE_COLUMN_WIDTH}s{' ' * (_TABLE_WIDTH - _MEASUREMENT_CONTENT_WIDTH - 1)}│"
)
_MEASUREMENT_HEADER_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_NUM_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_RECALL_COLUMN_WIDTH}s │ %{_F1_COLUMN_WIDTH}s │ "
    f"%{_MRE_COLUMN_WIDTH}s{' ' * (_TABLE_WIDTH - _MEASUREMENT_CONTENT_WIDTH - 1)}│"
)
_STANDARD_ROW_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_NUM_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_RECALL_COLUMN_WIDTH}s │ %{_F1_COLUMN_WIDTH}s"
    f"{' ' * _STANDARD_PADDING}│"
)
_STANDARD_HEADER_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_NUM_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_RECALL_COLUMN_WIDTH}s │ %{_F1_COLUMN_WIDTH}s"
    f"{' ' * _STANDARD_PADDING}│"
)
_STANDARD_NA_ROW_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_NUM_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_RECALL_COLUMN_WIDTH}s │ %{_F1_COLUMN_WIDTH}s"
    f"{' ' * _STANDARD_PADDING}│"
)
_STATS_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %{_NUM_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s"
    f"{' ' * (_TABLE_WIDTH - _STATS_CONTENT_WIDTH - 1)}│"
)
_STATS_HEADER_FORMAT = (
    f"│  %-{_FIRST_COLUMN_WIDTH}s │ %-{_NUM_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s │ "
    f"%{_METRIC_COLUMN_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s │ %{_METRIC_COLUMN_WIDTH}s"
    f"{' ' * (_TABLE_WIDTH - _STATS_CONTENT_WIDTH - 1)}│"
)
_MRE_NOT_PROVIDED = object()


def _format_int(value: int) -> str:
    """Format an integer with thousands separators."""
    return f"{value:,}"


def _format_float(value: float, precision: int = 4) -> str:
    """Format a float with thousands separators and specified precision."""
    return f"{value:,.{precision}f}"


def _print_separator() -> None:
    """Print a table separator line."""
    logger.info("│  " + "─" * (_TABLE_WIDTH - 5) + " │")


def _print_table_footer() -> None:
    """Print a table footer."""
    logger.info("└" + "─" * (_TABLE_WIDTH - 2) + "┘")
    logger.info("")


def _print_table_header(title: str) -> None:
    """Print a table header."""
    dashes = _TABLE_WIDTH - 3 - len(title) - 1 - 1
    logger.info("┌─ " + title + " " + "─" * dashes + "┐")


def _calculate_padding(column_widths: list[int]) -> int:
    """Calculate padding width for a table row with given column widths."""
    content_width = 3
    for width in column_widths:
        content_width += width + 3
    content_width -= 3
    return _TABLE_WIDTH - content_width - 1


def _build_row_format(column_widths: list[int]) -> str:
    """Build a format string for a table row with given column widths."""
    padding = _calculate_padding(column_widths)
    format_parts = [f"│  %-{column_widths[0]}s"]
    for width in column_widths[1:]:
        format_parts.append(f" │ %{width}s")
    format_parts.append(f"{' ' * padding}│")
    return "".join(format_parts)


def _print_metrics_table_header(first_column: str = "Metric", extra_columns: list[str] | None = None) -> None:
    """Print the header row for metrics tables."""
    standard_columns = [
        ("GT Count", _NUM_WIDTH),
        ("Pred Count", _NUM_WIDTH),
        ("Precision", _METRIC_COLUMN_WIDTH),
        ("Recall", _RECALL_COLUMN_WIDTH),
        ("F1", _F1_COLUMN_WIDTH),
    ]

    if extra_columns:
        extra_widths = [_MRE_COLUMN_WIDTH if col == "MRE" else _METRIC_COLUMN_WIDTH for col in extra_columns]
        column_widths = _STANDARD_COLUMN_WIDTHS + extra_widths
        values = (
            [first_column]
            + [label.rjust(width) for label, width in standard_columns]
            + [col.rjust(width) for col, width in zip(extra_columns, extra_widths)]
        )
        logger.info(_build_row_format(column_widths), *values)
    else:
        logger.info(
            _STANDARD_HEADER_FORMAT,
            first_column,
            "GT Count".rjust(_NUM_WIDTH),
            "Pred Count".rjust(_NUM_WIDTH),
            "Precision".rjust(_METRIC_COLUMN_WIDTH),
            "Recall".rjust(_RECALL_COLUMN_WIDTH),
            "F1".rjust(_F1_COLUMN_WIDTH),
        )


def _print_metrics_row(
    label: str,
    gt_count: int,
    pred_count: int,
    precision: float | None = None,
    recall: float | None = None,
    f1: float | None = None,
    mre: float | None | object = _MRE_NOT_PROVIDED,
    num_extra_columns: int = 0,
) -> None:
    """Print a metrics table row."""
    formatted_gt_count = _format_int(gt_count)
    formatted_pred_count = _format_int(pred_count)

    use_measurement_format = mre is not _MRE_NOT_PROVIDED or num_extra_columns > 0

    if use_measurement_format:
        mre_value = "" if (mre is None or mre is _MRE_NOT_PROVIDED) else _format_float(mre)
        if precision is not None and recall is not None and f1 is not None:
            logger.info(
                _MEASUREMENT_ROW_FORMAT,
                label,
                formatted_gt_count,
                formatted_pred_count,
                _format_float(precision),
                _format_float(recall),
                _format_float(f1),
                mre_value,
            )
        else:
            logger.info(
                _MEASUREMENT_ROW_FORMAT,
                label,
                formatted_gt_count,
                formatted_pred_count,
                "N/A",
                "N/A",
                "N/A",
                mre_value,
            )
    elif precision is not None and recall is not None and f1 is not None:
        logger.info(
            _STANDARD_ROW_FORMAT,
            label,
            formatted_gt_count,
            formatted_pred_count,
            _format_float(precision),
            _format_float(recall),
            _format_float(f1),
        )
    else:
        logger.info(_STANDARD_NA_ROW_FORMAT, label, formatted_gt_count, formatted_pred_count, "N/A", "N/A", "N/A")


def _format_overview_line(label: str, value: int, indent: str = "") -> str:
    """Format a single overview line."""
    label_width = _LABEL_WIDTH - len(indent) if indent else _LABEL_WIDTH
    padding = _TABLE_WIDTH - 6 - len(indent) - label_width - _NUM_WIDTH
    formatted_value = _format_int(value)
    return f"│    {indent}{label:<{label_width}}{formatted_value:>{_NUM_WIDTH}s}" + " " * padding + "│"


def log_metrics_summary(metrics_summary: dict, metadata: dict | None = None) -> None:
    """Log metrics summary to console."""
    logger.info("")
    title = "EVALUATION SUMMARY"
    content_width = _TABLE_WIDTH - 2
    padding = (content_width - len(title)) // 2
    logger.info("╔" + "═" * content_width + "╗")
    logger.info("║" + " " * padding + title + " " * (content_width - len(title) - padding) + "║")
    logger.info("╚" + "═" * content_width + "╝")
    logger.info("")

    metrics_block = metrics_summary
    findings_counts = metrics_block.get("findings_counts", {})
    tp = findings_counts.get("tp", 0)
    fp = findings_counts.get("fp", 0)
    fn = findings_counts.get("fn", 0)
    micro_averaged = metrics_block.get("micro_averaged", {})
    total_gt = findings_counts.get("gt", micro_averaged.get("gt_count", tp + fn))
    total_pred = findings_counts.get("pred", micro_averaged.get("pred_count", tp + fp))

    num_reports = metadata.get("num_reports", 0) if metadata else 0

    _print_table_header("Overview")
    logger.info(_format_overview_line("Reports evaluated:", num_reports))
    logger.info(_format_overview_line("Total ground truth findings:", total_gt))
    logger.info(_format_overview_line("• True positive (TP):", tp, indent="  "))
    logger.info(_format_overview_line("• False negative (FN):", fn, indent="  "))
    logger.info(_format_overview_line("Total predicted findings:", total_pred))
    logger.info(_format_overview_line("• True positive (TP):", tp, indent="  "))
    logger.info(_format_overview_line("• False positive (FP):", fp, indent="  "))
    _print_table_footer()

    _print_table_header("Overall Performance")
    _print_separator()
    _print_metrics_table_header()
    _print_separator()

    report_averaged = metrics_block["report_averaged"]
    micro_averaged = metrics_block["micro_averaged"]
    _print_metrics_row(
        "report-averaged",
        total_gt,
        total_pred,
        report_averaged["precision"],
        report_averaged["recall"],
        report_averaged["f1"],
    )
    _print_metrics_row(
        "micro-averaged",
        total_gt,
        total_pred,
        micro_averaged["precision"],
        micro_averaged["recall"],
        micro_averaged["f1"],
    )
    _print_table_footer()

    regular_types = [constants.FINDING_TYPE_ABNORMAL_REGULAR, constants.FINDING_TYPE_NORMAL_REGULAR]
    if any(metrics_block.get(finding_type) for finding_type in regular_types):
        _print_table_header("Regular Performance")
        _print_separator()
        _print_metrics_table_header("Finding Type")
        _print_separator()
        for finding_type in regular_types:
            type_metrics = metrics_block.get(finding_type, {}).get("micro_averaged")
            if type_metrics:
                _print_metrics_row(
                    finding_type.replace("-regular", ""),
                    type_metrics.get("gt_count", 0),
                    type_metrics.get("pred_count", 0),
                    type_metrics.get("precision", 0.0),
                    type_metrics.get("recall", 0.0),
                    type_metrics.get("f1", 0.0),
                )
        _print_table_footer()

    longitudinal_metrics = metrics_block.get("longitudinal")
    if longitudinal_metrics:
        _print_table_header("Longitudinal Performance")
        _print_separator()
        _print_metrics_table_header("Metric")
        _print_separator()

        macro_averaged = longitudinal_metrics.get("macro_averaged", {})
        micro_averaged = longitudinal_metrics.get("micro_averaged", {})
        if micro_averaged:
            _print_metrics_row(
                "micro-averaged",
                micro_averaged.get("gt_count", 0),
                micro_averaged.get("pred_count", 0),
                micro_averaged.get("precision", 0.0),
                micro_averaged.get("recall", 0.0),
                micro_averaged.get("f1", 0.0),
            )

        _print_metrics_row(
            "macro-averaged",
            micro_averaged.get("gt_count", 0),
            micro_averaged.get("pred_count", 0),
            macro_averaged.get("precision", 0.0),
            macro_averaged.get("recall", 0.0),
            macro_averaged.get("f1", 0.0),
        )

        label_to_metrics = longitudinal_metrics.get("per_category", {})
        _print_separator()
        for label in constants.COMPARISON_VALUES_ORDER:
            label_metrics = label_to_metrics.get(label, {})
            gt_count = label_metrics.get("gt_count", 0)
            pred_count = label_metrics.get("pred_count", 0)
            precision = label_metrics.get("precision")
            recall = label_metrics.get("recall")
            f1 = label_metrics.get("f1")

            if all(m is not None for m in [precision, recall, f1]):
                _print_metrics_row(f"  • {label}", gt_count, pred_count, precision, recall, f1)
            else:
                _print_metrics_row(f"  • {label}", gt_count, pred_count)

        _print_table_footer()

    measurement_metrics = metrics_block.get("measurement", {})
    measurement_type_metrics = measurement_metrics.get("micro_averaged")
    if measurement_type_metrics or measurement_metrics:
        _print_table_header("Measurement Performance")
        _print_separator()
        _print_metrics_table_header("Type", extra_columns=["MRE"])
        _print_separator()

        category_to_metrics = measurement_metrics.get("per_category", {})
        micro_averaged_metrics = measurement_metrics.get("micro_averaged", {})
        macro_averaged_metrics = measurement_metrics.get("macro_averaged", {})

        if macro_averaged_metrics or micro_averaged_metrics:
            _print_metrics_row(
                "micro-averaged",
                micro_averaged_metrics.get("gt_count", 0),
                micro_averaged_metrics.get("pred_count", 0),
                micro_averaged_metrics.get("precision", 0.0),
                micro_averaged_metrics.get("recall", 0.0),
                micro_averaged_metrics.get("f1", 0.0),
                mre=micro_averaged_metrics.get("mre"),
            )

            _print_metrics_row(
                "macro-averaged",
                macro_averaged_metrics.get("gt_count", 0),
                macro_averaged_metrics.get("pred_count", 0),
                macro_averaged_metrics.get("precision", 0.0),
                macro_averaged_metrics.get("recall", 0.0),
                macro_averaged_metrics.get("f1", 0.0),
                mre=macro_averaged_metrics.get("mre"),
            )

        _print_separator()
        for category in sorted(constants.MEASUREMENT_CATEGORY_VALUES):
            category_metrics = category_to_metrics.get(category, {})
            category_mre = category_metrics.get("mre")
            gt_count = category_metrics.get("gt_count", 0)
            pred_count = category_metrics.get("pred_count", 0)
            precision = category_metrics.get("precision")
            recall = category_metrics.get("recall")
            f1 = category_metrics.get("f1")

            if all(m is not None for m in [precision, recall, f1]):
                _print_metrics_row(f"  • {category}", gt_count, pred_count, precision, recall, f1, mre=category_mre)
            else:
                _print_metrics_row(f"  • {category}", gt_count, pred_count, mre=category_mre)

        _print_table_footer()

    report_stats = metrics_block.get("report_score_statistics", {})
    if report_stats:
        _print_table_header("Report-Level Statistics")
        _print_separator()
        logger.info(
            _STATS_HEADER_FORMAT,
            "Metric",
            "Avg".rjust(_METRIC_COLUMN_WIDTH),
            "Std".rjust(_METRIC_COLUMN_WIDTH),
            "Med".rjust(_METRIC_COLUMN_WIDTH),
            "Min".rjust(_METRIC_COLUMN_WIDTH),
            "Max".rjust(_METRIC_COLUMN_WIDTH),
        )
        _print_separator()
        for metric_name in ["f1", "precision", "recall"]:
            stats = report_stats.get(metric_name, {})
            logger.info(
                _STATS_FORMAT,
                metric_name.title(),
                _format_float(stats.get("avg", 0.0)),
                _format_float(stats.get("std", 0.0)),
                _format_float(stats.get("median", 0.0)),
                _format_float(stats.get("min", 0.0)),
                _format_float(stats.get("max", 0.0)),
            )
        _print_table_footer()

    logger.info("═" * (_TABLE_WIDTH + 2))
    logger.info("")
