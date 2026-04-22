"""Tests for prompt building and LLM message construction utilities."""

from __future__ import annotations

import json
import unittest

from radmatch import constants
from radmatch.llm_utils import prompts


class TestFilterFindingFields(unittest.TestCase):
    """Test filter_finding_fields function."""

    def test_filter_finding_fields_complete(self):
        """Test filtering finding with all required fields."""
        finding = {
            "finding_id": "test_001",
            "text": "Pneumonia in right lower lobe",
            "clinical_status": "abnormal",
            "comparison": "worsening",
            "measurements": [{"value": "5.2", "category": "size"}],
        }

        result = prompts.filter_finding_fields(finding)

        self.assertEqual(result["finding_id"], "test_001")
        self.assertEqual(result["text"], "Pneumonia in right lower lobe")
        self.assertEqual(result["clinical_status"], "abnormal")
        self.assertEqual(result["comparison"], "worsening")
        self.assertEqual(result["measurements"], [{"value": "5.2", "category": "size"}])

    def test_filter_finding_fields_extra_fields(self):
        """Test filtering finding with extra fields that should be removed."""
        finding = {
            "finding_id": "test_001",
            "text": "Finding",
            "clinical_status": "abnormal",
            "abnormality_category": "pulmonary",
            "organ": "lung",
            "comparison": None,
            "measurements": [],
        }

        result = prompts.filter_finding_fields(finding)

        self.assertNotIn("abnormality_category", result)
        self.assertNotIn("organ", result)
        self.assertEqual(result["finding_id"], "test_001")
        self.assertEqual(result["text"], "Finding")

    def test_filter_finding_fields_missing_fields(self):
        """Test filtering finding with missing fields uses defaults."""
        finding = {
            "finding_id": "test_001",
            "text": "Finding",
        }

        result = prompts.filter_finding_fields(finding)

        self.assertEqual(result["clinical_status"], constants.DEFAULT_CLINICAL_STATUS)
        self.assertIsNone(result["comparison"])
        self.assertEqual(result["measurements"], [])

    def test_filter_finding_fields_empty_strings(self):
        """Test filtering finding with empty string fields."""
        finding = {
            "finding_id": "",
            "text": "",
            "clinical_status": "",
        }

        result = prompts.filter_finding_fields(finding)

        self.assertEqual(result["finding_id"], "")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["clinical_status"], constants.DEFAULT_CLINICAL_STATUS)


class TestGetUserPrompt(unittest.TestCase):
    """Test get_user_prompt function."""

    def test_get_user_prompt(self):
        """Test formatting user prompt with report text."""
        report = "Patient has pneumonia in right lower lobe."
        result = prompts.get_user_prompt(report)

        self.assertIn(report, result)
        self.assertIn("Please extract findings", result)


class TestBuildMessages(unittest.TestCase):
    """Test build_messages function."""

    def test_build_messages_no_examples(self):
        """Test building messages without examples."""
        system_instructions = "You are a helpful assistant."
        report = "Patient has pneumonia."

        result = prompts.build_messages(system_instructions, report)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[0]["content"], system_instructions)
        self.assertEqual(result[1]["role"], "user")
        self.assertIn(report, result[1]["content"])

    def test_build_messages_with_examples(self):
        """Test building messages with few-shot examples."""
        system_instructions = "You are a helpful assistant."
        report = "Patient has pneumonia."
        examples = [
            {
                "report": "Example report 1",
                "assistant": [{"finding_id": "ex1_001", "text": "Example finding", "clinical_status": "abnormal"}],
            },
            {
                "report": "Example report 2",
                "assistant": [{"finding_id": "ex2_001", "text": "Another finding", "clinical_status": "normal"}],
            },
        ]

        result = prompts.build_messages(system_instructions, report, examples)

        self.assertEqual(len(result), 6)
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[1]["role"], "user")
        self.assertEqual(result[2]["role"], "assistant")
        self.assertEqual(result[3]["role"], "user")
        self.assertEqual(result[4]["role"], "assistant")
        self.assertEqual(result[5]["role"], "user")
        self.assertIn(report, result[5]["content"])

        assistant_content = json.loads(result[2]["content"])
        self.assertEqual(assistant_content[0]["finding_id"], "ex1_001")

    def test_build_messages_empty_examples(self):
        """Test building messages with empty examples list."""
        system_instructions = "You are a helpful assistant."
        report = "Patient has pneumonia."

        result = prompts.build_messages(system_instructions, report, [])

        self.assertEqual(len(result), 2)

    def test_build_messages_example_missing_report(self):
        """Test building messages with example missing report."""
        system_instructions = "You are a helpful assistant."
        report = "Patient has pneumonia."
        examples = [{"assistant": [{"finding_id": "ex1_001", "text": "Finding"}]}]

        result = prompts.build_messages(system_instructions, report, examples)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]["role"], "assistant")
        self.assertEqual(result[2]["role"], "user")

    def test_build_messages_example_missing_assistant(self):
        """Test building messages with example missing assistant."""
        system_instructions = "You are a helpful assistant."
        report = "Patient has pneumonia."
        examples = [{"report": "Example report"}]

        result = prompts.build_messages(system_instructions, report, examples)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]["role"], "user")
        self.assertEqual(result[2]["role"], "user")


class TestLoadPrompt(unittest.TestCase):
    """Test load_prompt function.

    Note: This function reads from assets directory, so tests verify
    that it raises FileNotFoundError for missing files and can load
    existing files. The actual file loading is tested via integration tests.
    """

    def test_load_prompt_missing_file(self):
        """Test loading a missing prompt file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            prompts.load_prompt("nonexistent_prompt_file_12345.txt")


class TestLoadFewshot(unittest.TestCase):
    """Test load_fewshot function.

    Note: This function reads from assets directory. Most functionality
    is tested via integration tests. Unit tests verify basic behavior.
    """

    def test_load_fewshot_none(self):
        """Test loading fewshot with None returns empty list."""
        result = prompts.load_fewshot(None)
        self.assertEqual(result, [])

    def test_load_fewshot_missing_set(self):
        """Test loading fewshot for non-existent set returns empty list."""
        result = prompts.load_fewshot("nonexistent_example_set_12345")
        self.assertEqual(result, [])
