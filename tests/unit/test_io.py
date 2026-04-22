"""Tests for I/O operations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radmatch import io


class TestReadTextFile(unittest.TestCase):
    """Test read_text_file function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_read_text_file_success(self):
        """Test reading valid text file."""
        text_file = self.tmp_path / "test.txt"
        content = "Test content\nwith multiple lines"
        text_file.write_text(content, encoding="utf-8")

        result = io.read_text_file(text_file)
        self.assertEqual(result, content.strip())

    def test_read_text_file_empty(self):
        """Test reading empty file returns None."""
        text_file = self.tmp_path / "empty.txt"
        text_file.write_text("   \n  ", encoding="utf-8")

        result = io.read_text_file(text_file)
        self.assertIsNone(result)

    def test_read_text_file_not_found(self):
        """Test reading non-existent file returns None."""
        text_file = self.tmp_path / "nonexistent.txt"

        result = io.read_text_file(text_file)
        self.assertIsNone(result)


class TestLoadJson(unittest.TestCase):
    """Test load_json function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_load_json_valid(self):
        """Test loading valid JSON file."""
        json_file = self.tmp_path / "test.json"
        data = {"key": "value", "number": 42, "list": [1, 2, 3]}
        json_file.write_text(json.dumps(data), encoding="utf-8")

        result = io.load_json(json_file)
        self.assertEqual(result, data)

    def test_load_json_invalid_raises(self):
        """Test loading invalid JSON raises error by default."""
        json_file = self.tmp_path / "invalid.json"
        json_file.write_text("{ invalid json }", encoding="utf-8")

        with self.assertRaises(ValueError):
            io.load_json(json_file)

    def test_load_json_invalid_no_raise(self):
        """Test loading invalid JSON returns default when raise_on_error=False."""
        json_file = self.tmp_path / "invalid.json"
        json_file.write_text("{ invalid json }", encoding="utf-8")

        result = io.load_json(json_file, default=None, raise_on_error=False)
        self.assertIsNone(result)

    def test_load_json_missing_raises(self):
        """Test loading missing file raises FileNotFoundError by default."""
        json_file = self.tmp_path / "missing.json"

        with self.assertRaises(FileNotFoundError):
            io.load_json(json_file)

    def test_load_json_missing_no_raise(self):
        """Test loading missing file returns default when raise_on_error=False."""
        json_file = self.tmp_path / "missing.json"

        result = io.load_json(json_file, default=None, raise_on_error=False)
        self.assertIsNone(result)

    def test_load_json_empty_raises(self):
        """Test loading empty JSON file raises error by default."""
        json_file = self.tmp_path / "empty.json"
        json_file.write_text("   ", encoding="utf-8")

        with self.assertRaises(ValueError):
            io.load_json(json_file)


class TestSaveJson(unittest.TestCase):
    """Test save_json function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_save_json(self):
        """Test saving JSON file."""
        json_file = self.tmp_path / "subdir" / "test.json"
        data = {"key": "value", "number": 42}

        io.save_json(data, json_file)

        self.assertTrue(json_file.exists())
        self.assertTrue(json_file.parent.exists())
        loaded = json.loads(json_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded, data)

    def test_save_json_creates_directories(self):
        """Test save_json creates parent directories."""
        json_file = self.tmp_path / "deep" / "nested" / "path" / "test.json"
        data = {"test": True}

        io.save_json(data, json_file)

        self.assertTrue(json_file.exists())
        self.assertTrue(json_file.parent.exists())


class TestFindReportFiles(unittest.TestCase):
    """Test find_report_files function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_find_report_files(self):
        """Test finding .txt report files."""
        (self.tmp_path / "report1.txt").write_text("content1")
        (self.tmp_path / "report2.txt").write_text("content2")
        (self.tmp_path / "other.json").write_text("{}")
        (self.tmp_path / "subdir").mkdir()
        (self.tmp_path / "subdir" / "report3.txt").write_text("content3")

        result = io.find_report_files(self.tmp_path)

        self.assertEqual(len(result), 2)
        self.assertTrue(all(f.name in ["report1.txt", "report2.txt"] for f in result))
        self.assertEqual(result[0].name, "report1.txt")
        self.assertEqual(result[1].name, "report2.txt")

    def test_find_report_files_empty_dir(self):
        """Test finding report files in empty directory."""
        result = io.find_report_files(self.tmp_path)
        self.assertEqual(result, [])


class TestFilterFilesNeedingProcessing(unittest.TestCase):
    """Test filter_files_needing_processing function."""

    def setUp(self):
        """Set up test fixtures."""
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        """Clean up after tests."""
        self.tmp_dir.cleanup()

    def test_filter_files_needing_processing_all_new(self):
        """Test filtering files when no outputs exist."""
        input_dir = self.tmp_path / "input"
        output_dir = self.tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        (input_dir / "file1.txt").write_text("content1")
        (input_dir / "file2.txt").write_text("content2")

        input_files = list(input_dir.glob("*.txt"))
        files_to_process, skipped = io.filter_files_needing_processing(input_files, output_dir)

        self.assertEqual(len(files_to_process), 2)
        self.assertEqual(skipped, 0)

    def test_filter_files_needing_processing_some_exist(self):
        """Test filtering files when some outputs already exist."""
        input_dir = self.tmp_path / "input"
        output_dir = self.tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        (input_dir / "file1.txt").write_text("content1")
        (input_dir / "file2.txt").write_text("content2")
        (output_dir / "file1.json").write_text("{}")

        input_files = list(input_dir.glob("*.txt"))
        files_to_process, skipped = io.filter_files_needing_processing(input_files, output_dir)

        self.assertEqual(len(files_to_process), 1)
        self.assertEqual(files_to_process[0].name, "file2.txt")
        self.assertEqual(skipped, 1)
