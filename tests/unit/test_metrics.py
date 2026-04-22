"""Tests for metrics computation."""

from __future__ import annotations

import unittest

from radmatch import constants
from radmatch.evaluation import metrics


class TestGetFindingType(unittest.TestCase):
    """Test get_finding_type function."""

    def test_normal_finding(self):
        """Test normal findings are categorized correctly."""
        self.assertEqual(metrics.get_finding_type({"clinical_status": "normal"}), constants.FINDING_TYPE_NORMAL_REGULAR)
        self.assertEqual(
            metrics.get_finding_type({"clinical_status": "normal", "comparison": "improving"}),
            constants.FINDING_TYPE_LONGITUDINAL,
        )
        self.assertEqual(
            metrics.get_finding_type({"clinical_status": "normal", "measurements": [{"value": "5"}]}),
            constants.FINDING_TYPE_MEASUREMENT,
        )

    def test_measurement_finding(self):
        """Test findings with measurements and comparison."""
        finding = {
            "clinical_status": "abnormal",
            "comparison": "stable",
            "measurements": [{"value": "5.2", "category": "size"}],
        }
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_MEASUREMENT)

    def test_longitudinal_finding(self):
        """Test findings with comparison but no measurements."""
        finding = {"clinical_status": "abnormal", "comparison": "worsening", "measurements": []}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_LONGITUDINAL)

        finding = {"clinical_status": "abnormal", "comparison": "improving"}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_LONGITUDINAL)

    def test_abnormal_regular_finding(self):
        """Test abnormal regular findings (without comparison or measurements)."""
        finding = {"clinical_status": "abnormal", "measurements": []}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_ABNORMAL_REGULAR)

        finding = {"clinical_status": "abnormal"}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_ABNORMAL_REGULAR)

    def test_invalid_status_finding(self):
        """Test findings with invalid status are normalized to default (abnormal-regular)."""
        finding = {"clinical_status": "invalid_status", "measurements": []}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_ABNORMAL_REGULAR)

        finding = {"clinical_status": "invalid_status"}
        self.assertEqual(metrics.get_finding_type(finding), constants.FINDING_TYPE_ABNORMAL_REGULAR)


class TestComputeF1Score(unittest.TestCase):
    """Test compute_f1_score function."""

    def test_perfect_score(self):
        """Test perfect F1 score."""
        self.assertEqual(metrics.compute_f1_score(10, 0, 0), 1.0)

    def test_no_findings(self):
        """Test when there are no findings."""
        self.assertEqual(metrics.compute_f1_score(0, 0, 0), 1.0)

    def test_zero_f1(self):
        """Test zero F1 score."""
        self.assertEqual(metrics.compute_f1_score(0, 5, 5), 0.0)

    def test_standard_f1(self):
        """Test standard F1 calculation."""
        # TP=8, FP=2, FN=2 -> F1 = 2*8 / (2*8 + 2 + 2) = 16/20 = 0.8
        self.assertAlmostEqual(metrics.compute_f1_score(8, 2, 2), 0.8, places=5)

    def test_denominator_zero(self):
        """Test when denominator is zero."""
        self.assertEqual(metrics.compute_f1_score(0, 0, 0), 1.0)


class TestComputePrecision(unittest.TestCase):
    """Test compute_precision function."""

    def test_perfect_precision(self):
        """Test perfect precision."""
        self.assertEqual(metrics.compute_precision(10, 0), 1.0)

    def test_zero_precision(self):
        """Test zero precision."""
        self.assertEqual(metrics.compute_precision(0, 5), 0.0)

    def test_standard_precision(self):
        """Test standard precision calculation."""
        # TP=8, FP=2 -> Precision = 8/(8+2) = 0.8
        self.assertAlmostEqual(metrics.compute_precision(8, 2), 0.8, places=5)

    def test_denominator_zero(self):
        """Test when denominator is zero."""
        self.assertEqual(metrics.compute_precision(0, 0), 0.0)


class TestComputeRecall(unittest.TestCase):
    """Test compute_recall function."""

    def test_perfect_recall(self):
        """Test perfect recall."""
        self.assertEqual(metrics.compute_recall(10, 0), 1.0)

    def test_zero_recall(self):
        """Test zero recall."""
        self.assertEqual(metrics.compute_recall(0, 5), 0.0)

    def test_standard_recall(self):
        """Test standard recall calculation."""
        # TP=8, FN=2 -> Recall = 8/(8+2) = 0.8
        self.assertAlmostEqual(metrics.compute_recall(8, 2), 0.8, places=5)

    def test_denominator_zero(self):
        """Test when denominator is zero."""
        self.assertEqual(metrics.compute_recall(0, 0), 0.0)


class TestMetricsAggregator(unittest.TestCase):
    """Test MetricsAggregator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.aggregator = metrics.MetricsAggregator()

    def test_initialization(self):
        """Test aggregator initialization."""
        self.assertEqual(len(self.aggregator.report_stats_list), 0)
        self.assertEqual(self.aggregator.global_tp, 0)
        self.assertEqual(self.aggregator.global_fp, 0)
        self.assertEqual(self.aggregator.global_fn, 0)
        self.assertEqual(self.aggregator.total_pred_findings, 0)
        self.assertEqual(self.aggregator.total_gt_findings, 0)

    def test_add_report(self):
        """Test adding a single report."""
        report_stats = {"gt_count": 5, "pred_count": 6, "tp": 4, "fp": 2, "fn": 1}
        pred_findings = [
            {"finding_id": "p1", "clinical_status": "abnormal", "measurements": []},
            {"finding_id": "p2", "clinical_status": "abnormal", "measurements": []},
            {"finding_id": "p3", "clinical_status": "normal"},
        ]
        gt_findings = [
            {"finding_id": "g1", "clinical_status": "abnormal", "measurements": []},
            {"finding_id": "g2", "clinical_status": "abnormal", "measurements": []},
        ]
        matching_results = {
            "p1": {"matched": True, "corresponding_gt_finding_id": "g1"},
            "p2": {"matched": True, "corresponding_gt_finding_id": "g2"},
            "p3": {"matched": False},
        }

        self.aggregator.add_report(
            report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
        )

        self.assertEqual(len(self.aggregator.report_stats_list), 1)
        self.assertEqual(self.aggregator.global_tp, 4)
        self.assertEqual(self.aggregator.global_fp, 2)
        self.assertEqual(self.aggregator.global_fn, 1)
        self.assertEqual(self.aggregator.total_pred_findings, 6)
        self.assertEqual(self.aggregator.total_gt_findings, 5)

    def test_add_multiple_reports(self):
        """Test adding multiple reports."""
        for i in range(3):
            report_stats = {"gt_count": 2, "pred_count": 2, "tp": 1, "fp": 1, "fn": 1}
            pred_findings = [{"finding_id": f"p{i}_1", "clinical_status": "abnormal", "measurements": []}]
            gt_findings = [{"finding_id": f"g{i}_1", "clinical_status": "abnormal", "measurements": []}]
            matching_results = {f"p{i}_1": {"matched": True, "corresponding_gt_finding_id": f"g{i}_1"}}

            self.aggregator.add_report(
                report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
            )

        self.assertEqual(len(self.aggregator.report_stats_list), 3)
        self.assertEqual(self.aggregator.global_tp, 3)
        self.assertEqual(self.aggregator.global_fp, 3)
        self.assertEqual(self.aggregator.global_fn, 3)

    def test_compute_per_report_metrics(self):
        """Test computing per-report metrics."""
        report_stats = {"gt_count": 5, "pred_count": 6, "tp": 4, "fp": 2, "fn": 1}
        pred_findings = [{"finding_id": "p1", "clinical_status": "abnormal", "measurements": []}]
        gt_findings = [{"finding_id": "g1", "clinical_status": "abnormal", "measurements": []}]
        matching_results = {"p1": {"matched": True, "corresponding_gt_finding_id": "g1"}}

        self.aggregator.add_report(
            report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
        )

        result = self.aggregator.compute_per_report_metrics()
        self.assertIn("f1", result)
        self.assertIn("precision", result)
        self.assertIn("recall", result)
        self.assertIn("gt_count", result)
        self.assertIn("pred_count", result)
        self.assertEqual(result["gt_count"], 5)
        self.assertEqual(result["pred_count"], 6)

    def test_compute_per_report_metrics_empty(self):
        """Test computing per-report metrics with no reports."""
        result = self.aggregator.compute_per_report_metrics()
        self.assertEqual(result["f1"], 0.0)
        self.assertEqual(result["precision"], 0.0)
        self.assertEqual(result["recall"], 0.0)

    def test_longitudinal_macro_excludes_absent_labels(self):
        """Absent comparison labels must not inflate the macro average.

        One unmatched 'stable' GT, no predictions: only 'stable' contributes
        to the macro (f1=0). The four absent labels (improving/worsening/
        new/resolved) stay out, otherwise macro_f1 would be (0+1+1+1+1)/5 =
        0.8 on a report where nothing was predicted correctly.
        """
        self.aggregator.longitudinal_label_match_stats["stable"] = {"tp": 0, "fp": 0, "fn": 1}

        result = self.aggregator.compute_longitudinal_metrics()

        self.assertEqual(result["macro_averaged"]["f1"], 0.0)
        self.assertEqual(result["macro_averaged"]["precision"], 0.0)
        self.assertEqual(result["macro_averaged"]["recall"], 0.0)

    def test_compute_micro_metrics(self):
        """Test computing micro-averaged metrics."""
        report_stats = {"gt_count": 5, "pred_count": 6, "tp": 4, "fp": 2, "fn": 1}
        pred_findings = [{"finding_id": "p1", "clinical_status": "abnormal", "measurements": []}]
        gt_findings = [{"finding_id": "g1", "clinical_status": "abnormal", "measurements": []}]
        matching_results = {"p1": {"matched": True, "corresponding_gt_finding_id": "g1"}}

        self.aggregator.add_report(
            report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
        )

        result = self.aggregator.compute_micro_metrics()
        self.assertIn("f1", result)
        self.assertIn("precision", result)
        self.assertIn("recall", result)
        self.assertIn("count", result)
        self.assertEqual(result["count"], 5)

    def test_compute_per_type_metrics(self):
        """Test computing per-type metrics."""
        report_stats = {"gt_count": 3, "pred_count": 3, "tp": 2, "fp": 1, "fn": 1}
        pred_findings = [
            {"finding_id": "p1", "clinical_status": "abnormal", "measurements": []},
            {"finding_id": "p2", "clinical_status": "normal"},
            {"finding_id": "p3", "clinical_status": "abnormal", "comparison": "stable", "measurements": []},
        ]
        gt_findings = [
            {"finding_id": "g1", "clinical_status": "abnormal", "measurements": []},
            {"finding_id": "g2", "clinical_status": "normal"},
            {"finding_id": "g3", "clinical_status": "abnormal", "measurements": []},
        ]
        matching_results = {
            "p1": {"matched": True, "corresponding_gt_finding_id": "g1"},
            "p2": {"matched": True, "corresponding_gt_finding_id": "g2"},
            "p3": {"matched": False},
        }

        self.aggregator.add_report(
            report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
        )

        result = self.aggregator.compute_per_type_metrics()
        self.assertIn(constants.FINDING_TYPE_ABNORMAL_REGULAR, result)
        self.assertIn(constants.FINDING_TYPE_NORMAL_REGULAR, result)
        self.assertIn(constants.FINDING_TYPE_LONGITUDINAL, result)

    def test_compute_report_level_statistics(self):
        """Test computing report-level statistics."""
        for i in range(3):
            report_stats = {"gt_count": 2, "pred_count": 2, "tp": i + 1, "fp": 1, "fn": 1}
            pred_findings = [{"finding_id": f"p{i}_1", "clinical_status": "abnormal", "measurements": []}]
            gt_findings = [{"finding_id": f"g{i}_1", "clinical_status": "abnormal", "measurements": []}]
            matching_results = {f"p{i}_1": {"matched": True, "corresponding_gt_finding_id": f"g{i}_1"}}

            self.aggregator.add_report(
                report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
            )

        result = self.aggregator.compute_report_level_statistics()
        self.assertIn("f1", result)
        self.assertIn("precision", result)
        self.assertIn("recall", result)

        for metric in ["f1", "precision", "recall"]:
            self.assertIn("avg", result[metric])
            self.assertIn("min", result[metric])
            self.assertIn("max", result[metric])
            self.assertIn("std", result[metric])

    def test_get_summary(self):
        """Test getting complete summary."""
        report_stats = {"gt_count": 2, "pred_count": 2, "tp": 1, "fp": 1, "fn": 1}
        pred_findings = [{"finding_id": "p1", "clinical_status": "abnormal", "measurements": []}]
        gt_findings = [{"finding_id": "g1", "clinical_status": "abnormal", "measurements": []}]
        matching_results = {"p1": {"matched": True, "corresponding_gt_finding_id": "g1"}}

        self.aggregator.add_report(
            report_stats, pred_findings, gt_findings, matching_results, precomputed_per_type_stats={}
        )

        summary = self.aggregator.get_summary()
        self.assertIn("report_averaged", summary)
        self.assertIn("micro_averaged", summary)
        self.assertIn("report_score_statistics", summary)
        self.assertIn("longitudinal", summary)
        self.assertIn("measurement", summary)
        self.assertIn("findings_counts", summary)
