"""Integration tests for finding extraction functionality."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from radmatch import constants, io
from radmatch.finding_extraction import extract_findings


class TestExtractFindings(unittest.TestCase):
    """Test extract_findings function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.reports_gt_dir = self.tmp_path / "reports_gt"
        self.reports_pred_dir = self.tmp_path / "reports_pred"
        self.output_dir = self.tmp_path / "output"
        self.results_dir = self.output_dir / constants.RESULTS_DIR
        self.reports_gt_dir.mkdir()
        self.reports_pred_dir.mkdir()

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def _create_report_file(self, dir_path: Path, series_uuid: str, content: str) -> None:
        """Helper to create a report text file."""
        report_file = dir_path / f"{series_uuid}.txt"
        report_file.write_text(content, encoding="utf-8")

    def _create_mock_llm_response(self, findings: list[dict]) -> str:
        """Helper to create mock LLM response."""
        return json.dumps(findings)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_basic(self, mock_retry, mock_build_client):
        """Test basic finding extraction workflow."""
        series_uuid = "test_001"
        report_text = "Pneumonia in right lower lobe. No other abnormalities."
        self._create_report_file(self.reports_gt_dir, series_uuid, report_text)
        self._create_report_file(self.reports_pred_dir, series_uuid, report_text)

        mock_findings = [
            {
                "text": "Pneumonia in right lower lobe",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]

        def retry_side_effect(call_func, **kwargs):
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        extract_findings(
            reports_gt_dir=self.reports_gt_dir,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=1,
        )

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR
        findings_pred_dir = self.results_dir / constants.FINDINGS_PRED_DIR

        self.assertTrue(findings_gt_dir.exists())
        self.assertTrue(findings_pred_dir.exists())

        gt_file = findings_gt_dir / f"{series_uuid}.json"
        pred_file = findings_pred_dir / f"{series_uuid}.json"

        self.assertTrue(gt_file.exists())
        self.assertTrue(pred_file.exists())

        gt_findings = io.load_json(gt_file)
        pred_findings = io.load_json(pred_file)

        self.assertEqual(len(gt_findings), 1)
        self.assertEqual(len(pred_findings), 1)
        self.assertEqual(gt_findings[0]["text"], "Pneumonia in right lower lobe")
        self.assertEqual(gt_findings[0]["clinical_status"], "abnormal")
        self.assertEqual(gt_findings[0]["finding_id"], f"{series_uuid}_001")

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_multiple_reports(self, mock_retry, mock_build_client):
        """Test extraction with multiple reports."""
        mock_findings = [
            {
                "text": "Test finding",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]

        def retry_side_effect(call_func, **kwargs):
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        for i in range(3):
            series_uuid = f"test_{i:03d}"
            report_text = f"Report {i} content"
            self._create_report_file(self.reports_gt_dir, series_uuid, report_text)
            self._create_report_file(self.reports_pred_dir, series_uuid, report_text)

        extract_findings(
            reports_gt_dir=self.reports_gt_dir,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=2,
        )

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR
        findings_pred_dir = self.results_dir / constants.FINDINGS_PRED_DIR

        for i in range(3):
            series_uuid = f"test_{i:03d}"
            self.assertTrue((findings_gt_dir / f"{series_uuid}.json").exists())
            self.assertTrue((findings_pred_dir / f"{series_uuid}.json").exists())

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_resume(self, mock_retry, mock_build_client):
        """Test resume functionality with existing findings."""
        series_uuid_1 = "test_001"
        series_uuid_2 = "test_002"

        self._create_report_file(self.reports_gt_dir, series_uuid_1, "Report 1")
        self._create_report_file(self.reports_pred_dir, series_uuid_1, "Report 1")
        self._create_report_file(self.reports_gt_dir, series_uuid_2, "Report 2")
        self._create_report_file(self.reports_pred_dir, series_uuid_2, "Report 2")

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR
        findings_pred_dir = self.results_dir / constants.FINDINGS_PRED_DIR
        findings_gt_dir.mkdir(parents=True)
        findings_pred_dir.mkdir(parents=True)

        existing_findings = [
            {
                "finding_id": f"{series_uuid_1}_001",
                "text": "Existing finding",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]
        io.save_json(existing_findings, findings_gt_dir / f"{series_uuid_1}.json")
        io.save_json(existing_findings, findings_pred_dir / f"{series_uuid_1}.json")

        mock_findings = [
            {
                "text": "New finding",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]

        def retry_side_effect(call_func, **kwargs):
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        extract_findings(
            reports_gt_dir=self.reports_gt_dir,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=1,
        )

        self.assertTrue((findings_gt_dir / f"{series_uuid_1}.json").exists())
        self.assertTrue((findings_gt_dir / f"{series_uuid_2}.json").exists())

        existing_loaded = io.load_json(findings_gt_dir / f"{series_uuid_1}.json")
        self.assertEqual(existing_loaded[0]["text"], "Existing finding")

        self.assertEqual(mock_retry.call_count, 2)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_with_findings_gt_dir(self, mock_retry, mock_build_client):
        """Test extraction when findings_gt_dir is provided instead of reports_gt_dir."""
        series_uuid = "test_001"
        self._create_report_file(self.reports_pred_dir, series_uuid, "Predicted report")

        findings_gt_source_dir = self.tmp_path / "findings_gt_source"
        findings_gt_source_dir.mkdir()
        existing_gt_findings = [
            {
                "finding_id": f"{series_uuid}_001",
                "text": "Ground truth finding",
                "clinical_status": "abnormal",
                "measurements": [],
            }
        ]
        io.save_json(existing_gt_findings, findings_gt_source_dir / f"{series_uuid}.json")

        mock_findings = [
            {
                "text": "Predicted finding",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]

        def retry_side_effect(call_func, **kwargs):
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        extract_findings(
            reports_gt_dir=None,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=1,
            findings_gt_dir=findings_gt_source_dir,
        )

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR
        findings_pred_dir = self.results_dir / constants.FINDINGS_PRED_DIR

        self.assertTrue((findings_gt_dir / f"{series_uuid}.json").exists())
        self.assertTrue((findings_pred_dir / f"{series_uuid}.json").exists())

        gt_findings = io.load_json(findings_gt_dir / f"{series_uuid}.json")
        self.assertEqual(gt_findings[0]["text"], "Ground truth finding")

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_with_limit(self, mock_retry, mock_build_client):
        """Test extraction with limit on number of reports."""
        mock_findings = [
            {
                "text": "Test finding",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]

        def retry_side_effect(call_func, **kwargs):
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        for i in range(5):
            series_uuid = f"test_{i:03d}"
            report_text = f"Report {i}"
            self._create_report_file(self.reports_gt_dir, series_uuid, report_text)
            self._create_report_file(self.reports_pred_dir, series_uuid, report_text)

        extract_findings(
            reports_gt_dir=self.reports_gt_dir,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=1,
            limit=3,
        )

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR

        processed_count = len(list(findings_gt_dir.glob("*.json")))
        self.assertLessEqual(processed_count, 3)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_handles_failures(self, mock_retry, mock_build_client):
        """Test that extraction handles LLM failures gracefully."""
        series_uuid_1 = "test_001"
        series_uuid_2 = "test_002"

        self._create_report_file(self.reports_gt_dir, series_uuid_1, "Report 1")
        self._create_report_file(self.reports_pred_dir, series_uuid_1, "Report 1")
        self._create_report_file(self.reports_gt_dir, series_uuid_2, "Report 2")
        self._create_report_file(self.reports_pred_dir, series_uuid_2, "Report 2")

        call_count = 0

        def retry_side_effect(call_func, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (None, "LLM API error")
            mock_findings = [
                {
                    "text": "Successful finding",
                    "clinical_status": "abnormal",
                    "comparison": None,
                    "measurements": [],
                }
            ]
            return (self._create_mock_llm_response(mock_findings), None)

        mock_retry.side_effect = retry_side_effect
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        extract_findings(
            reports_gt_dir=self.reports_gt_dir,
            reports_pred_dir=self.reports_pred_dir,
            output_dir=self.output_dir,
            model_name="test-model",
            workers=1,
        )

        findings_gt_dir = self.results_dir / constants.FINDINGS_GT_DIR

        failed_reports_file = self.results_dir / constants.FAILED_REPORTS_FILE
        self.assertTrue(failed_reports_file.exists())

        failed_reports = io.load_json(failed_reports_file)
        self.assertGreater(len(failed_reports), 0)

        self.assertTrue((findings_gt_dir / f"{series_uuid_2}.json").exists())

    def test_extract_findings_raises_without_gt(self):
        """Test that extract_findings raises error when neither reports_gt_dir nor findings_gt_dir provided."""
        with self.assertRaises(ValueError):
            extract_findings(
                reports_gt_dir=None,
                reports_pred_dir=self.reports_pred_dir,
                output_dir=self.output_dir,
                model_name="test-model",
                findings_gt_dir=None,
            )
