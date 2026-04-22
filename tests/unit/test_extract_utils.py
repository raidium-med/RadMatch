"""Tests for finding extraction utilities."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radmatch import constants
from radmatch.finding_extraction import extract_utils


class TestCreateOutputDirectories(unittest.TestCase):
    """Test create_output_directories function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_create_output_directories(self):
        """Test creating output directories."""
        output_dir = self.tmp_path / "output"

        findings_gt_dir, findings_pred_dir = extract_utils.create_output_directories(output_dir)

        self.assertTrue(findings_gt_dir.exists())
        self.assertTrue(findings_pred_dir.exists())
        self.assertEqual(findings_gt_dir.name, constants.FINDINGS_GT_DIR)
        self.assertEqual(findings_pred_dir.name, constants.FINDINGS_PRED_DIR)

    def test_create_output_directories_exists(self):
        """Test creating output directories when they already exist."""
        output_dir = self.tmp_path / "output"
        findings_gt_dir = output_dir / constants.FINDINGS_GT_DIR
        findings_gt_dir.mkdir(parents=True)

        extract_utils.create_output_directories(output_dir)

        self.assertTrue(findings_gt_dir.exists())
        self.assertTrue((output_dir / constants.FINDINGS_PRED_DIR).exists())


class TestExtractFindingsList(unittest.TestCase):
    """Test extract_findings_list function."""

    def test_extract_findings_list_basic(self):
        """Test basic finding extraction and normalization."""
        findings_raw = [
            {
                "text": "Pneumonia in right lower lobe",
                "clinical_status": "abnormal",
                "comparison": "worsening",
                "measurements": [],
            }
        ]

        result = extract_utils.extract_findings_list(findings_raw, "series_001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["finding_id"], "series_001_001")
        self.assertEqual(result[0]["text"], "Pneumonia in right lower lobe")
        self.assertEqual(result[0]["clinical_status"], "abnormal")
        self.assertEqual(result[0]["comparison"], "worsening")
        self.assertEqual(result[0]["measurements"], [])

    def test_extract_findings_list_normalize_clinical_status(self):
        """Test clinical_status normalization."""
        findings_raw = [
            {"text": "Valid status", "clinical_status": "abnormal"},
            {"text": "Invalid status", "clinical_status": "invalid_status"},
            {"text": "Missing status"},
        ]

        result = extract_utils.extract_findings_list(findings_raw, "series_001")

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["clinical_status"], "abnormal")
        self.assertEqual(result[1]["clinical_status"], constants.DEFAULT_CLINICAL_STATUS)
        self.assertEqual(result[2]["clinical_status"], constants.DEFAULT_CLINICAL_STATUS)

    def test_extract_findings_list_normalize_comparison(self):
        """Test comparison normalization."""
        findings_raw = [
            {"text": "Valid comparison", "comparison": "improving"},
            {"text": "Invalid comparison", "comparison": "invalid_comparison"},
            {"text": "No comparison"},
        ]

        result = extract_utils.extract_findings_list(findings_raw, "series_001")

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["comparison"], "improving")
        self.assertIsNone(result[1]["comparison"])
        self.assertIsNone(result[2]["comparison"])

    def test_extract_findings_list_normalize_measurements(self):
        """Test measurements normalization."""
        findings_raw = [
            {
                "text": "With measurements",
                "measurements": [
                    {"value": "5.2", "category": "size"},
                    {"value": "3.1", "category": "invalid_category"},
                ],
            },
            {"text": "No measurements", "measurements": []},
            {"text": "Invalid measurements", "measurements": "not_a_list"},
        ]

        result = extract_utils.extract_findings_list(findings_raw, "series_001")

        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]["measurements"]), 2)
        self.assertEqual(result[0]["measurements"][0]["category"], "size")
        self.assertEqual(result[0]["measurements"][1]["category"], constants.DEFAULT_MEASUREMENT_CATEGORY)
        self.assertEqual(result[1]["measurements"], [])
        self.assertEqual(result[2]["measurements"], [])

    def test_extract_findings_list_skips_invalid_items(self):
        """Test that invalid items are skipped."""
        findings_raw = [
            {"text": "Valid finding", "clinical_status": "abnormal"},
            "not_a_dict",
            {"text": "Another valid finding"},
            None,
            42,
        ]

        result = extract_utils.extract_findings_list(findings_raw, "series_001")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "Valid finding")
        self.assertEqual(result[1]["text"], "Another valid finding")

    def test_extract_findings_list_raises_on_non_list(self):
        """Test that non-list input raises ValueError."""
        with self.assertRaises(ValueError):
            extract_utils.extract_findings_list({"not": "a list"}, "series_001")

    def test_extract_findings_list_finding_ids(self):
        """Test finding ID generation."""
        findings_raw = [
            {"text": "Finding 1"},
            {"text": "Finding 2"},
            {"text": "Finding 3"},
        ]

        result = extract_utils.extract_findings_list(findings_raw, "abc123")

        self.assertEqual(result[0]["finding_id"], "abc123_001")
        self.assertEqual(result[1]["finding_id"], "abc123_002")
        self.assertEqual(result[2]["finding_id"], "abc123_003")


class TestWriteFindingsOutput(unittest.TestCase):
    """Test write_findings_output function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_write_findings_output(self):
        """Test writing findings output to JSON file."""
        findings_dir = self.tmp_path / "findings"
        findings_dir.mkdir()
        findings_list = [
            {"finding_id": "test_001", "text": "Finding 1", "clinical_status": "abnormal", "measurements": []}
        ]

        extract_utils.write_findings_output("series_001", findings_list, findings_dir)

        output_file = findings_dir / "series_001.json"
        self.assertTrue(output_file.exists())
        import json

        loaded = json.loads(output_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded, findings_list)


class TestCopyFindingsFromDirectory(unittest.TestCase):
    """Test copy_findings_from_directory function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_copy_findings_from_directory(self):
        """Test copying findings from directory."""
        source_dir = self.tmp_path / "source"
        target_dir = self.tmp_path / "target"
        source_dir.mkdir()

        findings1 = [{"finding_id": "test_001", "text": "Finding 1", "clinical_status": "abnormal", "measurements": []}]
        findings2 = [{"finding_id": "test_002", "text": "Finding 2", "clinical_status": "normal", "measurements": []}]
        findings3 = [{"finding_id": "test_003", "text": "Finding 3", "clinical_status": "abnormal", "measurements": []}]

        from radmatch import io

        io.save_json(findings1, source_dir / "file1.json")
        io.save_json(findings2, source_dir / "file2.json")
        io.save_json(findings3, source_dir / "file3.json")

        count = extract_utils.copy_findings_from_directory(source_dir, target_dir)

        self.assertEqual(count, 3)
        self.assertTrue((target_dir / "file1.json").exists())
        self.assertTrue((target_dir / "file2.json").exists())
        self.assertTrue((target_dir / "file3.json").exists())

    def test_copy_findings_from_directory_missing_source(self):
        """Test copying from non-existent directory returns 0."""
        source_dir = self.tmp_path / "nonexistent"
        target_dir = self.tmp_path / "target"

        count = extract_utils.copy_findings_from_directory(source_dir, target_dir)

        self.assertEqual(count, 0)

    def test_copy_findings_from_directory_skips_existing(self):
        """Test that existing files are skipped."""
        source_dir = self.tmp_path / "source"
        target_dir = self.tmp_path / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        findings = [{"finding_id": "test_001", "text": "Finding", "clinical_status": "abnormal", "measurements": []}]

        from radmatch import io

        io.save_json(findings, source_dir / "file1.json")
        io.save_json(findings, target_dir / "file1.json")

        count = extract_utils.copy_findings_from_directory(source_dir, target_dir)

        self.assertEqual(count, 0)
