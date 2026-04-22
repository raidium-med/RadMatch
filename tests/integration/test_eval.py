"""Integration tests for evaluation functionality."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from radmatch import constants, io
from radmatch.evaluation import eval


class TestEvaluateFindings(unittest.TestCase):
    """Test evaluate_findings function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.results_parent_dir = self.tmp_path / "results"
        self.result_dir = self.results_parent_dir / constants.RESULTS_DIR
        self.findings_gt_dir = self.result_dir / constants.FINDINGS_GT_DIR
        self.findings_pred_dir = self.result_dir / constants.FINDINGS_PRED_DIR
        self.findings_gt_dir.mkdir(parents=True)
        self.findings_pred_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def _create_findings_file(self, dir_path: Path, series_uuid: str, findings: list[dict]) -> None:
        """Helper to create a findings JSON file."""
        findings_file = dir_path / f"{series_uuid}.json"
        io.save_json(findings, findings_file)

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    @patch("radmatch.evaluation.eval.matching.match_findings_llm")
    def test_evaluate_findings_basic(self, mock_match, mock_build_client):
        """Test basic evaluation workflow."""
        series_uuid = "test_001"
        pred_findings = [
            {
                "finding_id": "p1",
                "text": "Pneumonia in right lower lobe",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]
        gt_findings = [
            {
                "finding_id": "g1",
                "text": "Pneumonia in right lower lobe",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]

        self._create_findings_file(self.findings_pred_dir, series_uuid, pred_findings)
        self._create_findings_file(self.findings_gt_dir, series_uuid, gt_findings)

        matching_results = {
            "p1": {
                "matched": True,
                "corresponding_gt_finding_id": "g1",
                "confidence": "high",
                "reasoning": "Exact match",
            }
        }
        mock_match.return_value = matching_results
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        matching_file = self.result_dir / "matching" / f"{series_uuid}.json"
        self.assertTrue(matching_file.exists())

        result = io.load_json(matching_file)
        self.assertIn("p1", result)
        self.assertTrue(result["p1"]["matched"])
        self.assertEqual(result["p1"]["corresponding_gt_finding_id"], "g1")

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    @patch("radmatch.evaluation.eval.matching.match_findings_llm")
    def test_evaluate_findings_multiple_reports(self, mock_match, mock_build_client):
        """Test evaluation with multiple reports."""
        for i in range(3):
            series_uuid = f"test_{i:03d}"
            pred_findings = [
                {
                    "finding_id": f"p{i}_1",
                    "text": f"Finding {i}",
                    "clinical_status": "abnormal",
                    "measurements": [],
                }
            ]
            gt_findings = [
                {
                    "finding_id": f"g{i}_1",
                    "text": f"Finding {i}",
                    "clinical_status": "abnormal",
                    "measurements": [],
                }
            ]

            self._create_findings_file(self.findings_pred_dir, series_uuid, pred_findings)
            self._create_findings_file(self.findings_gt_dir, series_uuid, gt_findings)

        def match_side_effect(pred_findings_list, gt_findings_list, series_uuid, client, workers, fewshot=None):
            return {
                pred_findings_list[0]["finding_id"]: {
                    "matched": True,
                    "corresponding_gt_finding_id": gt_findings_list[0]["finding_id"],
                    "confidence": "high",
                    "reasoning": "Match",
                }
            }

        mock_match.side_effect = match_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        matching_dir = self.result_dir / "matching"
        matching_files = list(matching_dir.glob("*.json"))

        self.assertEqual(len(matching_files), 3)
        for i in range(3):
            series_uuid = f"test_{i:03d}"
            matching_file = matching_dir / f"{series_uuid}.json"
            self.assertTrue(matching_file.exists())

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    @patch("radmatch.evaluation.eval.matching.match_findings_llm")
    def test_evaluate_findings_resume(self, mock_match, mock_build_client):
        """Test resume functionality with existing results."""
        series_uuid_1 = "test_001"
        series_uuid_2 = "test_002"

        pred_findings_1 = [{"finding_id": "p1", "text": "Finding 1", "clinical_status": "abnormal", "measurements": []}]
        gt_findings_1 = [{"finding_id": "g1", "text": "Finding 1", "clinical_status": "abnormal", "measurements": []}]
        pred_findings_2 = [{"finding_id": "p2", "text": "Finding 2", "clinical_status": "abnormal", "measurements": []}]
        gt_findings_2 = [{"finding_id": "g2", "text": "Finding 2", "clinical_status": "abnormal", "measurements": []}]

        self._create_findings_file(self.findings_pred_dir, series_uuid_1, pred_findings_1)
        self._create_findings_file(self.findings_gt_dir, series_uuid_1, gt_findings_1)
        self._create_findings_file(self.findings_pred_dir, series_uuid_2, pred_findings_2)
        self._create_findings_file(self.findings_gt_dir, series_uuid_2, gt_findings_2)

        matching_dir = self.result_dir / "matching"
        matching_dir.mkdir(parents=True)

        existing_result = {
            "p1": {
                "matched": True,
                "corresponding_gt_finding_id": "g1",
                "confidence": "high",
                "reasoning": "",
            }
        }
        io.save_json(existing_result, matching_dir / f"{series_uuid_1}.json")

        def match_side_effect(pred_findings_list, gt_findings_list, series_uuid, client, workers, fewshot=None):
            return {
                pred_findings_list[0]["finding_id"]: {
                    "matched": True,
                    "corresponding_gt_finding_id": gt_findings_list[0]["finding_id"],
                    "confidence": "high",
                    "reasoning": "Match",
                }
            }

        mock_match.side_effect = match_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        matching_dir = self.result_dir / "matching"
        self.assertTrue((matching_dir / f"{series_uuid_1}.json").exists())
        self.assertTrue((matching_dir / f"{series_uuid_2}.json").exists())

        self.assertEqual(mock_match.call_count, 1)

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    def test_evaluate_findings_no_predicted_files(self, mock_build_client):
        """Test evaluation when no predicted files exist."""
        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        matching_dir = self.result_dir / "matching"
        self.assertFalse(matching_dir.exists())

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    def test_evaluate_findings_no_matching_pairs(self, mock_build_client):
        """Test evaluation when no matching report pairs exist."""
        series_uuid = "test_001"
        pred_findings = [{"finding_id": "p1", "text": "Finding", "clinical_status": "abnormal", "measurements": []}]

        self._create_findings_file(self.findings_pred_dir, series_uuid, pred_findings)

        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        matching_dir = self.result_dir / "matching"
        self.assertFalse(matching_dir.exists())

    @patch("radmatch.evaluation.eval.llm_clients.build_single_client")
    @patch("radmatch.evaluation.eval.matching.match_findings_llm")
    def test_evaluate_findings_generates_summary(self, mock_match, mock_build_client):
        """Test that summary is generated when all reports are processed."""
        series_uuid = "test_001"
        pred_findings = [
            {
                "finding_id": "p1",
                "text": "Finding 1",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]
        gt_findings = [
            {
                "finding_id": "g1",
                "text": "Finding 1",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]

        self._create_findings_file(self.findings_pred_dir, series_uuid, pred_findings)
        self._create_findings_file(self.findings_gt_dir, series_uuid, gt_findings)

        matching_results = {
            "p1": {
                "matched": True,
                "corresponding_gt_finding_id": "g1",
                "confidence": "high",
                "reasoning": "Match",
            }
        }
        mock_match.return_value = matching_results
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        eval.evaluate_findings(self.result_dir, "test-model", workers=1)

        summary_file = self.result_dir / constants.SUMMARY_FILE
        self.assertTrue(summary_file.exists())

        summary_data = io.load_json(summary_file)
        self.assertIn("metadata", summary_data)
        self.assertIn("metrics", summary_data)

        metadata = summary_data["metadata"]
        self.assertIn("timestamp", metadata)
        self.assertIn("inputs", metadata)
        self.assertIn("config", metadata)
        self.assertEqual(metadata["num_reports"], 1)

        summary = summary_data["metrics"]
        self.assertIn("report_averaged", summary)
        self.assertIn("micro_averaged", summary)
        self.assertIn("report_score_statistics", summary)
        self.assertIn("longitudinal", summary)
        self.assertIn("measurement", summary)
        self.assertIn("findings_counts", summary)
