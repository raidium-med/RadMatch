"""Tests for batch processing utilities."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radmatch.llm_utils import batch_utils


class TestGenerateBatchFileName(unittest.TestCase):
    """Test generate_batch_file_name function."""

    def test_generate_batch_file_name_basic(self):
        """Test generating batch file name."""
        base_path = Path("/path/to/batch_requests.jsonl")
        result = batch_utils.generate_batch_file_name(base_path, 0)
        self.assertEqual(result, Path("/path/to/batch_requests_1.jsonl"))

    def test_generate_batch_file_name_with_index(self):
        """Test generating batch file name with index."""
        base_path = Path("/path/to/batch_requests.jsonl")
        result = batch_utils.generate_batch_file_name(base_path, 5)
        self.assertEqual(result, Path("/path/to/batch_requests_6.jsonl"))

    def test_generate_batch_file_name_large_index(self):
        """Test generating batch file name with large index."""
        base_path = Path("/path/to/batch_requests.jsonl")
        result = batch_utils.generate_batch_file_name(base_path, 123)
        self.assertEqual(result, Path("/path/to/batch_requests_124.jsonl"))


class TestBatchFileWriter(unittest.TestCase):
    """Test BatchFileWriter class."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_batch_file_writer_initialization(self):
        """Test BatchFileWriter initialization."""
        batch_file = self.tmp_path / "batch.jsonl"
        report_file = self.tmp_path / "report_001.txt"
        report_file.write_text("report content", encoding="utf-8")

        writer = batch_utils.BatchFileWriter(batch_file, max_requests_per_file=100)
        self.assertEqual(writer.base_path, batch_file)
        self.assertEqual(writer.max_requests_per_file, 100)
        self.assertEqual(writer.current_batch_index, 0)
        self.assertIsNotNone(writer.current_file)

        writer._finalize_current_batch()

    def test_batch_file_writer_add_request(self):
        """Test adding a request."""
        batch_file = self.tmp_path / "batch.jsonl"
        report_file = self.tmp_path / "report_001.txt"
        report_file.write_text("report content", encoding="utf-8")

        writer = batch_utils.BatchFileWriter(batch_file, max_requests_per_file=100)
        request = {"method": "POST", "url": "/v1/chat/completions"}

        custom_id = writer.add_request(report_file, request)

        self.assertIsNotNone(custom_id)
        self.assertEqual(len(writer.current_series_uuid_map), 1)
        batch_files = writer.finalize()
        self.assertEqual(len(batch_files), 1)
        self.assertTrue(batch_files[0][0].exists())

    def test_batch_file_writer_multiple_requests(self):
        """Test adding multiple requests."""
        batch_file = self.tmp_path / "batch.jsonl"
        writer = batch_utils.BatchFileWriter(batch_file, max_requests_per_file=100)

        for i in range(5):
            report_file = self.tmp_path / f"report_{i:03d}.txt"
            report_file.write_text("content", encoding="utf-8")
            request = {"method": "POST", "url": "/v1/chat/completions"}
            writer.add_request(report_file, request)

        self.assertEqual(len(writer.current_series_uuid_map), 5)
        batch_files = writer.finalize()
        self.assertEqual(len(batch_files), 1)

    def test_batch_file_writer_splits_at_max(self):
        """Test that BatchFileWriter splits files at max_requests_per_file."""
        batch_file = self.tmp_path / "batch.jsonl"
        writer = batch_utils.BatchFileWriter(batch_file, max_requests_per_file=2)

        for i in range(5):
            report_file = self.tmp_path / f"report_{i:03d}.txt"
            report_file.write_text("content", encoding="utf-8")
            request = {"method": "POST", "url": "/v1/chat/completions"}
            writer.add_request(report_file, request)

        batch_files = writer.finalize()
        self.assertGreaterEqual(len(batch_files), 2)


class TestExtractContentFromBatchResult(unittest.TestCase):
    """Test extract_content_from_batch_result function."""

    def test_extract_content_from_batch_result_success_string(self):
        """Test extracting content from successful batch result with string content."""
        findings_data = [{"finding_id": "f1", "text": "Finding 1", "clinical_status": "abnormal"}]
        result = {
            "custom_id": "series_001",
            "response": {
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(findings_data, ensure_ascii=False),
                            }
                        }
                    ]
                }
            },
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertEqual(content, findings_data)

    def test_extract_content_from_batch_result_success_list(self):
        """Test extracting content when content is already a list."""
        findings_data = [{"finding_id": "f1", "text": "Finding 1", "clinical_status": "abnormal"}]
        result = {
            "custom_id": "series_001",
            "response": {
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": findings_data,
                            }
                        }
                    ]
                }
            },
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertEqual(content, findings_data)

    def test_extract_content_from_batch_result_not_list(self):
        """Test extracting content when result is not a list."""
        result = {
            "custom_id": "series_001",
            "response": {
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"not": "a list"}, ensure_ascii=False),
                            }
                        }
                    ]
                }
            },
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_invalid_json(self):
        """Test extracting content with invalid JSON."""
        result = {
            "custom_id": "series_001",
            "response": {
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": "{ invalid json }",
                            }
                        }
                    ]
                }
            },
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_missing_response(self):
        """Test extracting content when response is missing."""
        result = {"custom_id": "series_001"}

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_missing_body(self):
        """Test extracting content when body is missing."""
        result = {"custom_id": "series_001", "response": {}}

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_missing_choices(self):
        """Test extracting content when choices are missing."""
        result = {"custom_id": "series_001", "response": {"body": {}}}

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_empty_choices(self):
        """Test extracting content when choices list is empty."""
        result = {"custom_id": "series_001", "response": {"body": {"choices": []}}}

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_with_error(self):
        """Test extracting content when result has error."""
        result = {
            "custom_id": "series_001",
            "error": {"message": "API error"},
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_error_string(self):
        """Test extracting content when error is a string."""
        result = {
            "custom_id": "series_001",
            "error": "Error message",
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)

    def test_extract_content_from_batch_result_empty_content(self):
        """Test extracting content when content is empty."""
        result = {
            "custom_id": "series_001",
            "response": {
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                            }
                        }
                    ]
                }
            },
        }

        content = batch_utils.extract_content_from_batch_result(result, "series_001")

        self.assertIsNone(content)


class TestBuildResultsMap(unittest.TestCase):
    """Test build_results_map function."""

    def test_build_results_map_basic(self):
        """Test building results map."""
        results = [
            {"custom_id": "series_001", "status": "completed", "data": "result1"},
            {"custom_id": "series_002", "status": "completed", "data": "result2"},
        ]

        result_map = batch_utils.build_results_map(results)

        self.assertEqual(len(result_map), 2)
        self.assertEqual(result_map["series_001"]["status"], "completed")
        self.assertEqual(result_map["series_002"]["status"], "completed")

    def test_build_results_map_empty(self):
        """Test building results map from empty list."""
        results = []
        result_map = batch_utils.build_results_map(results)
        self.assertEqual(result_map, {})

    def test_build_results_map_duplicate_custom_id(self):
        """Test building results map with duplicate custom_id (last one wins)."""
        results = [
            {"custom_id": "series_001", "data": "result1"},
            {"custom_id": "series_001", "data": "result2"},
        ]

        result_map = batch_utils.build_results_map(results)

        self.assertEqual(len(result_map), 1)
        self.assertEqual(result_map["series_001"]["data"], "result2")

    def test_build_results_map_missing_custom_id(self):
        """Test building results map when custom_id is missing."""
        results = [
            {"status": "completed", "data": "result1"},
            {"custom_id": "series_002", "status": "completed", "data": "result2"},
        ]

        result_map = batch_utils.build_results_map(results)

        self.assertEqual(len(result_map), 1)
        self.assertIn("series_002", result_map)


class TestFilterReportsWithResults(unittest.TestCase):
    """Test filter_reports_with_results function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_filter_reports_with_results_all_have_results(self):
        """Test filtering when all reports have results."""
        report_files = [
            self.tmp_path / "report_001.txt",
            self.tmp_path / "report_002.txt",
        ]
        for f in report_files:
            f.write_text("report content", encoding="utf-8")

        report_path_to_custom_id = {
            self.tmp_path / "report_001.txt": "custom_001",
            self.tmp_path / "report_002.txt": "custom_002",
        }
        results_map = {
            "custom_001": {"status": "completed"},
            "custom_002": {"status": "completed"},
        }

        filtered, count = batch_utils.filter_reports_with_results(report_files, report_path_to_custom_id, results_map)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(count, 0)
        self.assertEqual(set(filtered), set(report_files))

    def test_filter_reports_with_results_some_have_results(self):
        """Test filtering when some reports have results."""
        report_files = [
            self.tmp_path / "report_001.txt",
            self.tmp_path / "report_002.txt",
            self.tmp_path / "report_003.txt",
        ]
        for f in report_files:
            f.write_text("report content", encoding="utf-8")

        report_path_to_custom_id = {
            self.tmp_path / "report_001.txt": "custom_001",
            self.tmp_path / "report_002.txt": "custom_002",
            self.tmp_path / "report_003.txt": "custom_003",
        }
        results_map = {
            "custom_001": {"status": "completed"},
            "custom_003": {"status": "completed"},
        }

        filtered, count = batch_utils.filter_reports_with_results(report_files, report_path_to_custom_id, results_map)

        self.assertEqual(len(filtered), 2)
        self.assertEqual(count, 0)
        self.assertIn(self.tmp_path / "report_001.txt", filtered)
        self.assertIn(self.tmp_path / "report_003.txt", filtered)
        self.assertNotIn(self.tmp_path / "report_002.txt", filtered)

    def test_filter_reports_with_results_none_have_results(self):
        """Test filtering when no reports have results."""
        report_files = [
            self.tmp_path / "report_001.txt",
            self.tmp_path / "report_002.txt",
        ]
        for f in report_files:
            f.write_text("report content", encoding="utf-8")

        report_path_to_custom_id = {
            self.tmp_path / "report_001.txt": "custom_001",
            self.tmp_path / "report_002.txt": "custom_002",
        }
        results_map = {}

        filtered, count = batch_utils.filter_reports_with_results(report_files, report_path_to_custom_id, results_map)

        self.assertEqual(filtered, [])
        self.assertEqual(count, 0)

    def test_filter_reports_with_results_empty_list(self):
        """Test filtering with empty report files list."""
        filtered, count = batch_utils.filter_reports_with_results([], {}, {})
        self.assertEqual(filtered, [])
        self.assertEqual(count, 0)

    def test_filter_reports_with_results_missing_custom_id(self):
        """Test filtering when some reports are missing from custom_id map."""
        report_files = [
            self.tmp_path / "report_001.txt",
            self.tmp_path / "report_002.txt",
        ]
        for f in report_files:
            f.write_text("content", encoding="utf-8")

        report_path_to_custom_id = {
            self.tmp_path / "report_001.txt": "custom_001",
        }
        results_map = {
            "custom_001": {"status": "completed"},
        }

        filtered, count = batch_utils.filter_reports_with_results(report_files, report_path_to_custom_id, results_map)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(count, 1)
        self.assertIn(self.tmp_path / "report_001.txt", filtered)
        self.assertNotIn(self.tmp_path / "report_002.txt", filtered)
