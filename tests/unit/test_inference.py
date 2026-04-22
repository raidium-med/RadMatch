"""Tests for finding extraction inference module."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from radmatch.finding_extraction import inference


class TestFindingExtractorInit(unittest.TestCase):
    """Test FindingExtractor initialization."""

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    def test_finding_extractor_init(self, mock_build_client):
        """Test FindingExtractor initialization."""
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        examples = [{"text": "example finding", "clinical_status": "abnormal"}]
        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=examples,
            workers=2,
            max_tokens=1000,
        )

        self.assertEqual(extractor.model_name, "test-model")
        self.assertEqual(extractor.examples, examples)
        self.assertEqual(extractor.workers, 2)
        self.assertEqual(extractor.max_tokens, 1000)
        self.assertEqual(extractor.client, mock_client)
        self.assertEqual(extractor._failed_reports, [])


class TestFindingExtractorExtractFindings(unittest.TestCase):
    """Test FindingExtractor._extract_findings method."""

    def setUp(self):
        """Set up test fixtures."""
        self.examples = [{"text": "example finding", "clinical_status": "abnormal"}]

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.prompts.build_report_processing_messages")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_success(self, mock_retry, mock_build_messages, mock_build_client):
        """Test successful finding extraction."""
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_build_messages.return_value = [{"role": "user", "content": "test"}]

        findings_data = [{"text": "Pneumonia", "clinical_status": "abnormal"}]
        mock_retry.return_value = (json.dumps(findings_data, ensure_ascii=False), None)

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        findings, failure_reason, raw_response = extractor._extract_findings("series_001", "Report text")

        self.assertEqual(findings, findings_data)
        self.assertIsNone(failure_reason)
        self.assertIsNotNone(raw_response)
        mock_build_messages.assert_called_once()
        mock_retry.assert_called_once()

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.prompts.build_report_processing_messages")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_api_failure(self, mock_retry, mock_build_messages, mock_build_client):
        """Test finding extraction with API failure."""
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_build_messages.return_value = [{"role": "user", "content": "test"}]
        mock_retry.return_value = (None, "API error")

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        findings, failure_reason, raw_response = extractor._extract_findings("series_001", "Report text")

        self.assertIsNone(findings)
        self.assertEqual(failure_reason, "API error")
        self.assertIsNone(raw_response)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.prompts.build_report_processing_messages")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_invalid_json(self, mock_retry, mock_build_messages, mock_build_client):
        """Test finding extraction with invalid JSON."""
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_build_messages.return_value = [{"role": "user", "content": "test"}]
        mock_retry.return_value = ("{ invalid json }", None)

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        findings, failure_reason, raw_response = extractor._extract_findings("series_001", "Report text")

        self.assertIsNone(findings)
        self.assertEqual(failure_reason, "JSON parsing failed for API response")
        self.assertIsNotNone(raw_response)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.prompts.build_report_processing_messages")
    @patch("radmatch.finding_extraction.inference.llm_clients.call_with_llm_retry")
    def test_extract_findings_not_list(self, mock_retry, mock_build_messages, mock_build_client):
        """Test finding extraction when response is not a list."""
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_build_messages.return_value = [{"role": "user", "content": "test"}]
        mock_retry.return_value = (json.dumps({"not": "a list"}, ensure_ascii=False), None)

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        findings, failure_reason, raw_response = extractor._extract_findings("series_001", "Report text")

        self.assertIsNone(findings)
        self.assertEqual(failure_reason, "LLM response is not a list")
        self.assertIsNotNone(raw_response)


class TestFindingExtractorProcessOneReport(unittest.TestCase):
    """Test FindingExtractor._process_one_report method."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.findings_dir = self.tmp_path / "findings"
        self.findings_dir.mkdir()
        self.examples = [{"text": "example finding", "clinical_status": "abnormal"}]

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.extract_utils.extract_findings_list")
    @patch("radmatch.finding_extraction.inference.FindingExtractor._extract_findings")
    def test_process_one_report_success(self, mock_extract, mock_extract_list, mock_build_client):
        """Test processing one report successfully."""
        mock_build_client.return_value = MagicMock()

        report_path = self.tmp_path / "report_001.txt"
        report_path.write_text("Report text", encoding="utf-8")

        findings_raw = [{"text": "Pneumonia", "clinical_status": "abnormal", "comparison": None, "measurements": []}]
        findings_processed = [
            {
                "finding_id": "report_001_001",
                "text": "Pneumonia",
                "clinical_status": "abnormal",
                "comparison": None,
                "measurements": [],
            }
        ]
        mock_extract.return_value = (findings_raw, None, "raw_response")
        mock_extract_list.return_value = findings_processed

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        status, series_uuid, findings_list = extractor._process_one_report(report_path, self.findings_dir)

        self.assertEqual(status, "success")
        self.assertEqual(series_uuid, "report_001")
        self.assertEqual(findings_list, findings_processed)
        mock_extract.assert_called_once_with("report_001", "Report text")
        mock_extract_list.assert_called_once_with(findings_raw, "report_001")

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.FindingExtractor._extract_findings")
    def test_process_one_report_failure(self, mock_extract, mock_build_client):
        """Test processing one report with extraction failure."""
        mock_build_client.return_value = MagicMock()

        report_path = self.tmp_path / "report_001.txt"
        report_path.write_text("Report text", encoding="utf-8")

        mock_extract.return_value = (None, "API error", None)

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        status, series_uuid, findings_list = extractor._process_one_report(report_path, self.findings_dir)

        self.assertEqual(status, "failed")
        self.assertEqual(series_uuid, "report_001")
        self.assertIsNone(findings_list)

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    @patch("radmatch.finding_extraction.inference.io.read_text_file")
    def test_process_one_report_file_read_error(self, mock_read_file, mock_build_client):
        """Test processing one report when file read fails."""
        mock_build_client.return_value = MagicMock()

        report_path = self.tmp_path / "report_001.txt"
        report_path.write_text("Report text", encoding="utf-8")

        mock_read_file.side_effect = OSError("File read error")

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=self.examples,
            workers=1,
            max_tokens=1000,
        )

        with self.assertRaises(OSError):
            extractor._process_one_report(report_path, self.findings_dir)


class TestFindingExtractorRecordFailure(unittest.TestCase):
    """Test FindingExtractor._record_failure method."""

    @patch("radmatch.finding_extraction.inference.llm_clients.build_single_client")
    def test_record_failure(self, mock_build_client):
        """Test recording a failure."""
        mock_build_client.return_value = MagicMock()

        extractor = inference.FindingExtractor(
            model_name="test-model",
            examples=[],
            workers=1,
            max_tokens=1000,
        )

        extractor._record_failure("series_001", "Error message")

        with extractor._failed_lock:
            self.assertEqual(len(extractor._failed_reports), 1)
            self.assertEqual(extractor._failed_reports[0]["series_uuid"], "series_001")
            self.assertEqual(extractor._failed_reports[0]["reason"], "Error message")
