"""Tests for matching logic."""

from __future__ import annotations

import unittest

from radmatch.evaluation import matching


class TestComputeReportMatchingStats(unittest.TestCase):
    """Test compute_report_matching_stats function."""

    def test_perfect_match(self):
        """Test perfect matching scenario."""
        pred_findings = [
            {"finding_id": "p1", "text": "Finding 1"},
            {"finding_id": "p2", "text": "Finding 2"},
        ]
        gt_findings = [
            {"finding_id": "g1", "text": "Finding 1"},
            {"finding_id": "g2", "text": "Finding 2"},
        ]
        matching_results = {
            "p1": {"matched": True, "corresponding_gt_finding_id": "g1"},
            "p2": {"matched": True, "corresponding_gt_finding_id": "g2"},
        }

        stats = matching.compute_report_matching_stats(pred_findings, gt_findings, matching_results)

        self.assertEqual(stats["gt_count"], 2)
        self.assertEqual(stats["pred_count"], 2)
        self.assertEqual(stats["tp"], 2)
        self.assertEqual(stats["fp"], 0)
        self.assertEqual(stats["fn"], 0)

    def test_no_matches(self):
        """Test scenario with no matches."""
        pred_findings = [
            {"finding_id": "p1", "text": "Finding 1"},
            {"finding_id": "p2", "text": "Finding 2"},
        ]
        gt_findings = [
            {"finding_id": "g1", "text": "Different finding"},
            {"finding_id": "g2", "text": "Another different finding"},
        ]
        matching_results = {
            "p1": {"matched": False},
            "p2": {"matched": False},
        }

        stats = matching.compute_report_matching_stats(pred_findings, gt_findings, matching_results)

        self.assertEqual(stats["gt_count"], 2)
        self.assertEqual(stats["pred_count"], 2)
        self.assertEqual(stats["tp"], 0)
        self.assertEqual(stats["fp"], 2)
        self.assertEqual(stats["fn"], 2)

    def test_partial_match(self):
        """Test partial matching scenario."""
        pred_findings = [
            {"finding_id": "p1", "text": "Finding 1"},
            {"finding_id": "p2", "text": "Finding 2"},
            {"finding_id": "p3", "text": "Finding 3"},
        ]
        gt_findings = [
            {"finding_id": "g1", "text": "Finding 1"},
            {"finding_id": "g2", "text": "Different finding"},
        ]
        matching_results = {
            "p1": {"matched": True, "corresponding_gt_finding_id": "g1"},
            "p2": {"matched": False},
            "p3": {"matched": False},
        }

        stats = matching.compute_report_matching_stats(pred_findings, gt_findings, matching_results)

        self.assertEqual(stats["gt_count"], 2)
        self.assertEqual(stats["pred_count"], 3)
        self.assertEqual(stats["tp"], 1)
        self.assertEqual(stats["fp"], 2)
        self.assertEqual(stats["fn"], 1)

    def test_empty_findings(self):
        """Test with empty findings lists."""
        stats = matching.compute_report_matching_stats([], [], {})
        self.assertEqual(stats["gt_count"], 0)
        self.assertEqual(stats["pred_count"], 0)
        self.assertEqual(stats["tp"], 0)
        self.assertEqual(stats["fp"], 0)
        self.assertEqual(stats["fn"], 0)

    def test_no_predicted_findings(self):
        """Test with no predicted findings."""
        gt_findings = [
            {"finding_id": "g1", "text": "Finding 1"},
            {"finding_id": "g2", "text": "Finding 2"},
        ]
        stats = matching.compute_report_matching_stats([], gt_findings, {})

        self.assertEqual(stats["gt_count"], 2)
        self.assertEqual(stats["pred_count"], 0)
        self.assertEqual(stats["tp"], 0)
        self.assertEqual(stats["fp"], 0)
        self.assertEqual(stats["fn"], 2)

    def test_no_ground_truth_findings(self):
        """Test with no ground truth findings."""
        pred_findings = [
            {"finding_id": "p1", "text": "Finding 1"},
            {"finding_id": "p2", "text": "Finding 2"},
        ]
        matching_results = {
            "p1": {"matched": False},
            "p2": {"matched": False},
        }
        stats = matching.compute_report_matching_stats(pred_findings, [], matching_results)

        self.assertEqual(stats["gt_count"], 0)
        self.assertEqual(stats["pred_count"], 2)
        self.assertEqual(stats["tp"], 0)
        self.assertEqual(stats["fp"], 2)
        self.assertEqual(stats["fn"], 0)

    def test_duplicate_matches(self):
        """Test handling of duplicate matches (same GT matched twice)."""
        pred_findings = [
            {"finding_id": "p1", "text": "Finding 1"},
            {"finding_id": "p2", "text": "Finding 2"},
        ]
        gt_findings = [
            {"finding_id": "g1", "text": "Finding 1"},
        ]
        matching_results = {
            "p1": {"matched": True, "corresponding_gt_finding_id": "g1"},
            "p2": {"matched": True, "corresponding_gt_finding_id": "g1"},  # Duplicate match
        }

        stats = matching.compute_report_matching_stats(pred_findings, gt_findings, matching_results)

        self.assertEqual(stats["gt_count"], 1)
        self.assertEqual(stats["pred_count"], 2)
        self.assertEqual(stats["tp"], 2)  # Both predictions matched
        self.assertEqual(stats["fp"], 0)
        self.assertEqual(stats["fn"], 0)  # GT was matched (even if twice)
