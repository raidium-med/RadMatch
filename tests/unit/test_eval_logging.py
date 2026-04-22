"""Tests for evaluation logging and formatting functions."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from radmatch import constants
from radmatch.evaluation import eval_logging


class TestFormatOverviewLine(unittest.TestCase):
    """Test _format_overview_line function."""

    def test_format_overview_line_basic(self):
        """Test formatting a basic overview line."""
        result = eval_logging._format_overview_line("Reports evaluated:", 10)
        self.assertIn("Reports evaluated:", result)
        self.assertIn("10", result)
        self.assertTrue(result.startswith("│"))
        self.assertTrue(result.endswith("│"))

    def test_format_overview_line_with_indent(self):
        """Test formatting an overview line with indent."""
        result = eval_logging._format_overview_line("• true positive:", 5, "   ")
        self.assertIn("• true positive:", result)
        self.assertIn("5", result)
        self.assertIn("   ", result)

    def test_format_overview_line_zero_value(self):
        """Test formatting with zero value."""
        result = eval_logging._format_overview_line("Total findings:", 0)
        self.assertIn("Total findings:", result)
        self.assertIn("0", result)

    def test_format_overview_line_large_value(self):
        """Test formatting with large value."""
        result = eval_logging._format_overview_line("Total findings:", 99999)
        self.assertIn("99,999", result)


class TestPrintTableHeader(unittest.TestCase):
    """Test _print_table_header function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_table_header(self, mock_logger):
        """Test printing a table header."""
        eval_logging._print_table_header("Test Table")
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Test Table", call_args)
        self.assertTrue(call_args.startswith("┌"))
        self.assertTrue(call_args.endswith("┐"))

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_table_header_long_title(self, mock_logger):
        """Test printing a table header with long title."""
        eval_logging._print_table_header("Very Long Table Title That Might Wrap")
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Very Long Table Title That Might Wrap", call_args)


class TestPrintSeparator(unittest.TestCase):
    """Test _print_separator function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_separator(self, mock_logger):
        """Test printing a separator line."""
        eval_logging._print_separator()
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        self.assertTrue(call_args.startswith("│"))
        self.assertTrue(call_args.endswith("│"))
        self.assertIn("─", call_args)


class TestPrintTableFooter(unittest.TestCase):
    """Test _print_table_footer function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_table_footer(self, mock_logger):
        """Test printing a table footer."""
        eval_logging._print_table_footer()
        self.assertEqual(mock_logger.info.call_count, 2)
        footer_call = mock_logger.info.call_args_list[0][0][0]
        self.assertTrue(footer_call.startswith("└"))
        self.assertTrue(footer_call.endswith("┘"))


class TestCalculatePadding(unittest.TestCase):
    """Test _calculate_padding function."""

    def test_calculate_padding_standard_columns(self):
        """Test calculating padding for standard columns."""
        column_widths = [15, 10, 10, 10, 7, 6]
        padding = eval_logging._calculate_padding(column_widths)
        self.assertIsInstance(padding, int)
        self.assertGreaterEqual(padding, 0)

    def test_calculate_padding_single_column(self):
        """Test calculating padding for single column."""
        column_widths = [20]
        padding = eval_logging._calculate_padding(column_widths)
        self.assertIsInstance(padding, int)


class TestBuildRowFormat(unittest.TestCase):
    """Test _build_row_format function."""

    def test_build_row_format(self):
        """Test building row format string."""
        column_widths = [15, 10, 10]
        format_str = eval_logging._build_row_format(column_widths)
        self.assertIn("%-15s", format_str)
        self.assertIn("%10s", format_str)
        self.assertTrue(format_str.startswith("│"))


class TestPrintMetricsTableHeader(unittest.TestCase):
    """Test _print_metrics_table_header function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_table_header_default(self, mock_logger):
        """Test printing metrics table header with default first column."""
        eval_logging._print_metrics_table_header()
        mock_logger.info.assert_called_once()

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_table_header_custom_first_column(self, mock_logger):
        """Test printing metrics table header with custom first column."""
        eval_logging._print_metrics_table_header(first_column="Finding Type")
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        self.assertEqual(call_args[0][1], "Finding Type")

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_table_header_with_extra_columns(self, mock_logger):
        """Test printing metrics table header with extra columns."""
        eval_logging._print_metrics_table_header(extra_columns=["MRE"])
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        values_list = list(call_args[1:])
        mre_found = any("MRE" in str(val) for val in values_list)
        self.assertTrue(mre_found)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_table_header_multiple_extra_columns(self, mock_logger):
        """Test printing metrics table header with multiple extra columns."""
        eval_logging._print_metrics_table_header(extra_columns=["MRE", "Accuracy"])
        mock_logger.info.assert_called_once()


class TestPrintMetricsRow(unittest.TestCase):
    """Test _print_metrics_row function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_row_with_all_metrics(self, mock_logger):
        """Test printing metrics row with all metrics."""
        eval_logging._print_metrics_row(
            label="test-metric",
            gt_count=10,
            pred_count=12,
            precision=0.85,
            recall=0.90,
            f1=0.875,
        )
        mock_logger.info.assert_called_once()

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_row_with_none_metrics(self, mock_logger):
        """Test printing metrics row with None metrics."""
        eval_logging._print_metrics_row(
            label="test-metric",
            gt_count=10,
            pred_count=12,
        )
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        values_list = list(call_args[1:])
        self.assertIn("N/A", values_list)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_row_with_mre(self, mock_logger):
        """Test printing metrics row with MRE."""
        eval_logging._print_metrics_row(
            label="test-metric",
            gt_count=10,
            pred_count=12,
            precision=0.85,
            recall=0.90,
            f1=0.875,
            mre=0.05,
        )
        mock_logger.info.assert_called_once()

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_print_metrics_row_with_num_extra_columns(self, mock_logger):
        """Test printing metrics row with num_extra_columns."""
        eval_logging._print_metrics_row(
            label="test-metric",
            gt_count=10,
            pred_count=12,
            num_extra_columns=2,
        )
        mock_logger.info.assert_called_once()


class TestLogMetricsSummary(unittest.TestCase):
    """Test log_metrics_summary function."""

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_minimal(self, mock_logger):
        """Test logging minimal metrics summary."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875, "gt_count": 50, "pred_count": 55},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 5)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_with_per_type(self, mock_logger):
        """Test logging metrics summary with per-type metrics."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875, "gt_count": 50, "pred_count": 55},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            constants.FINDING_TYPE_ABNORMAL_REGULAR: {
                "micro_averaged": {
                    "precision": 0.80,
                    "recall": 0.85,
                    "f1": 0.825,
                    "gt_count": 30,
                    "pred_count": 35,
                }
            },
            constants.FINDING_TYPE_NORMAL_REGULAR: {
                "micro_averaged": {
                    "precision": 0.90,
                    "recall": 0.95,
                    "f1": 0.925,
                    "gt_count": 20,
                    "pred_count": 20,
                }
            },
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 10)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_with_longitudinal(self, mock_logger):
        """Test logging metrics summary with longitudinal metrics."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875, "gt_count": 50, "pred_count": 55},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            "longitudinal": {
                "macro_averaged": {"precision": 0.80, "recall": 0.85, "f1": 0.825},
                "micro_averaged": {
                    "precision": 0.82,
                    "recall": 0.88,
                    "f1": 0.85,
                    "gt_count": 20,
                    "pred_count": 22,
                },
                "per_category": {
                    "improving": {
                        "precision": 0.85,
                        "recall": 0.90,
                        "f1": 0.875,
                        "tp": 9,
                        "fp": 1,
                        "fn": 1,
                        "pred_count": 10,
                    },
                    "worsening": {
                        "precision": 0.80,
                        "recall": 0.85,
                        "f1": 0.825,
                        "tp": 8,
                        "fp": 2,
                        "fn": 2,
                        "pred_count": 10,
                    },
                },
            },
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 15)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_with_measurement(self, mock_logger):
        """Test logging metrics summary with measurement metrics."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            "measurement": {
                "micro_averaged": {
                    "precision": 0.80,
                    "recall": 0.85,
                    "f1": 0.825,
                    "gt_count": 10,
                    "pred_count": 12,
                    "mre": 0.05,
                },
                "macro_averaged": {
                    "precision": 0.78,
                    "recall": 0.82,
                    "f1": 0.80,
                    "gt_count": 10,
                    "pred_count": 12,
                    "mre": 0.06,
                },
                "per_category": {
                    "size": {
                        "precision": 0.85,
                        "recall": 0.90,
                        "f1": 0.875,
                        "mre": 0.04,
                        "gt_count": 5,
                        "pred_count": 6,
                    },
                },
            },
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 15)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_with_report_stats(self, mock_logger):
        """Test logging metrics summary with report-level statistics."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            "report_score_statistics": {
                "f1": {"avg": 0.85, "std": 0.05, "median": 0.86, "min": 0.78, "max": 0.92},
                "precision": {"avg": 0.82, "std": 0.04, "median": 0.83, "min": 0.76, "max": 0.88},
                "recall": {"avg": 0.88, "std": 0.06, "median": 0.89, "min": 0.80, "max": 0.95},
            },
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 15)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_empty_counts(self, mock_logger):
        """Test logging metrics summary with empty counts."""
        summary = {
            "report_averaged": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            "micro_averaged": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            "findings_counts": {},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 5)

    @patch("radmatch.evaluation.eval_logging.logger")
    def test_log_metrics_summary_longitudinal_partial_labels(self, mock_logger):
        """Test logging longitudinal metrics with partial labels (some None metrics)."""
        summary = {
            "report_averaged": {"precision": 0.85, "recall": 0.90, "f1": 0.875},
            "micro_averaged": {"precision": 0.82, "recall": 0.88, "f1": 0.85},
            "longitudinal": {
                "macro_averaged": {"precision": 0.80, "recall": 0.85, "f1": 0.825},
                "micro_averaged": {
                    "precision": 0.82,
                    "recall": 0.88,
                    "f1": 0.85,
                    "gt_count": 20,
                    "pred_count": 22,
                },
                "per_category": {
                    "improving": {
                        "precision": None,
                        "recall": None,
                        "f1": None,
                        "tp": 0,
                        "fp": 0,
                        "fn": 0,
                        "pred_count": 0,
                    },
                    "stable": {
                        "precision": 0.85,
                        "recall": 0.90,
                        "f1": 0.875,
                        "tp": 9,
                        "fp": 1,
                        "fn": 1,
                        "pred_count": 10,
                    },
                },
            },
            "findings_counts": {"gt": 50, "pred": 55, "tp": 45, "fp": 10, "fn": 5},
        }
        eval_logging.log_metrics_summary(summary)
        self.assertGreater(mock_logger.info.call_count, 15)
