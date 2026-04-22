"""Tests for LLM client utilities."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from radmatch import constants

# Mock external dependencies before importing llm_clients
sys.modules["mistralai"] = MagicMock()
sys.modules["openai"] = MagicMock()

from radmatch.llm_utils import llm_clients  # noqa: E402


class TestIsRateLimitError(unittest.TestCase):
    """Test is_rate_limit_error function."""

    def test_is_rate_limit_error_rate_limit(self):
        """Test detecting rate limit errors."""
        error = Exception("rate_limit exceeded")
        self.assertTrue(llm_clients.is_rate_limit_error(error))

        error = Exception("429 quota exceeded")
        self.assertTrue(llm_clients.is_rate_limit_error(error))

        error = Exception("quota exceeded")
        self.assertTrue(llm_clients.is_rate_limit_error(error))

    def test_is_rate_limit_error_not_rate_limit(self):
        """Test that non-rate-limit errors return False."""
        error = Exception("Invalid API key")
        self.assertFalse(llm_clients.is_rate_limit_error(error))

        error = Exception("Network timeout")
        self.assertFalse(llm_clients.is_rate_limit_error(error))


class TestIsContentFilterError(unittest.TestCase):
    """Test is_content_filter_error function."""

    def test_is_content_filter_error_content_filter(self):
        """Test detecting content filter errors."""
        error = Exception("content_filter triggered")
        self.assertTrue(llm_clients.is_content_filter_error(error))

        error = Exception("responsibleai error")
        self.assertTrue(llm_clients.is_content_filter_error(error))

    def test_is_content_filter_error_not_content_filter(self):
        """Test that non-content-filter errors return False."""
        error = Exception("Invalid API key")
        self.assertFalse(llm_clients.is_content_filter_error(error))

        error = Exception("Network timeout")
        self.assertFalse(llm_clients.is_content_filter_error(error))


class TestBuildSingleClient(unittest.TestCase):
    """Test build_single_client function."""

    @patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "test_key", "AZURE_OPENAI_ENDPOINT": "https://test.endpoint"})
    @patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
    def test_build_single_client_azure(self, mock_azure_client):
        """Test building Azure single client."""
        mock_client_instance = MagicMock()
        mock_azure_client.return_value = mock_client_instance

        client = llm_clients.build_single_client(model="gpt-5.2", max_tokens=1000)

        self.assertIsInstance(client, llm_clients.AzureSingleClient)
        mock_azure_client.assert_called_once()

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}, clear=False)
    @patch("radmatch.llm_utils.llm_clients.Mistral")
    def test_build_single_client_mistral(self, mock_mistral_client):
        """Test building Mistral single client."""
        mock_client_instance = MagicMock()
        mock_mistral_client.return_value = mock_client_instance

        client = llm_clients.build_single_client(model="magistral-medium-2509", max_tokens=1000)

        self.assertIsInstance(client, llm_clients.MistralSingleClient)
        mock_mistral_client.assert_called_once()

    def test_build_single_client_unknown_model(self):
        """Test building client with unknown model raises ValueError."""
        with self.assertRaises(ValueError):
            llm_clients.build_single_client(model="unknown-model-12345", max_tokens=1000)

    def test_build_single_client_case_insensitive(self):
        """Test that model name is case insensitive."""
        with patch.dict(
            os.environ, {"AZURE_OPENAI_API_KEY": "test_key", "AZURE_OPENAI_ENDPOINT": "https://test.endpoint"}
        ), patch("radmatch.llm_utils.llm_clients.AzureOpenAI"):
            client = llm_clients.build_single_client(model="GPT-5", max_tokens=1000)
            self.assertIsInstance(client, llm_clients.AzureSingleClient)


class TestBuildBatchClient(unittest.TestCase):
    """Test build_batch_client function."""

    @patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "test_key", "AZURE_OPENAI_ENDPOINT": "https://test.endpoint"})
    @patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
    def test_build_batch_client_azure(self, mock_azure_client):
        """Test building Azure batch client."""
        mock_client_instance = MagicMock()
        mock_azure_client.return_value = mock_client_instance

        client = llm_clients.build_batch_client(model="gpt-5.2", max_tokens=1000)

        self.assertIsInstance(client, llm_clients.AzureBatchClient)
        mock_azure_client.assert_called_once()

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}, clear=False)
    @patch("radmatch.llm_utils.llm_clients.Mistral")
    def test_build_batch_client_mistral(self, mock_mistral_client):
        """Test building Mistral batch client."""
        mock_client_instance = MagicMock()
        mock_mistral_client.return_value = mock_client_instance

        client = llm_clients.build_batch_client(model="magistral-medium-2509", max_tokens=1000)

        self.assertIsInstance(client, llm_clients.MistralBatchClient)
        mock_mistral_client.assert_called_once()

    def test_build_batch_client_unknown_model(self):
        """Test building batch client with unknown model raises ValueError."""
        with self.assertRaises(ValueError):
            llm_clients.build_batch_client(model="unknown-model-12345", max_tokens=1000)


class TestCallWithLLmRetry(unittest.TestCase):
    """Test call_with_llm_retry function."""

    def test_call_with_llm_retry_success_first_try(self):
        """Test retry function succeeds on first try."""
        func = MagicMock(return_value="success")

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=3)

        self.assertEqual(result, "success")
        self.assertIsNone(failure_reason)
        self.assertEqual(func.call_count, 1)

    def test_call_with_llm_retry_success_after_retries(self):
        """Test retry function succeeds after some failures."""
        func = MagicMock(side_effect=[Exception("temporary error"), Exception("temporary error"), "success"])

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=3)

        self.assertEqual(result, "success")
        self.assertIsNone(failure_reason)
        self.assertEqual(func.call_count, 3)

    def test_call_with_llm_retry_max_retries_exceeded(self):
        """Test retry function fails after max retries."""
        func = MagicMock(side_effect=Exception("persistent error"))

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=2)

        self.assertIsNone(result)
        self.assertIsNotNone(failure_reason)
        self.assertEqual(func.call_count, 2)

    @patch("time.sleep")
    def test_call_with_llm_retry_backoff(self, mock_sleep):
        """Test that retry uses exponential backoff."""
        func = MagicMock(side_effect=[Exception("error"), Exception("error"), "success"])

        llm_clients.call_with_llm_retry(func, max_retries=3, backoff_factor=2.0)

        self.assertGreater(mock_sleep.call_count, 0)

    @patch("time.sleep")
    def test_call_with_llm_retry_rate_limit_backoff(self, mock_sleep):
        """Test that rate limit errors use backoff."""
        func = MagicMock(side_effect=[Exception("rate limit exceeded"), Exception("rate limit exceeded"), "success"])

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=3)

        self.assertEqual(result, "success")
        self.assertIsNone(failure_reason)
        self.assertGreater(mock_sleep.call_count, 0)

    @patch("time.sleep")
    def test_call_with_llm_retry_content_filter_no_retry(self, mock_sleep):
        """Test that content filter errors don't retry."""
        func = MagicMock(side_effect=Exception("content_filter triggered"))

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=3)

        self.assertIsNone(result)
        self.assertEqual(failure_reason, "Content filter triggered")
        mock_sleep.assert_not_called()

    def test_call_with_llm_retry_default_max_retries(self):
        """Test that default max_retries is used when None."""
        func = MagicMock(side_effect=Exception("error"))

        result, failure_reason = llm_clients.call_with_llm_retry(func, max_retries=None)

        self.assertIsNone(result)
        self.assertIsNotNone(failure_reason)
        self.assertEqual(func.call_count, constants.MAX_RETRIES)

    def test_call_with_llm_retry_with_logger(self):
        """Test retry function with custom logger."""
        func = MagicMock(return_value="success")
        mock_logger = MagicMock()

        result, failure_reason = llm_clients.call_with_llm_retry(func, logger_instance=mock_logger)

        self.assertEqual(result, "success")
        self.assertIsNone(failure_reason)

    def test_call_with_llm_retry_with_series_uuid(self):
        """Test retry function with series_uuid."""
        func = MagicMock(return_value="success")

        result, failure_reason = llm_clients.call_with_llm_retry(func, series_uuid="test_001")

        self.assertEqual(result, "success")
        self.assertIsNone(failure_reason)


class TestAzureSingleClient(unittest.TestCase):
    """Test AzureSingleClient class."""

    @patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "test_key", "AZURE_OPENAI_ENDPOINT": "https://test.endpoint"})
    @patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
    def test_azure_single_client_complete(self, mock_azure_client_class):
        """Test AzureSingleClient complete method."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response content"
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_client_class.return_value = mock_client

        client = llm_clients.AzureSingleClient(model="gpt-5.2", max_tokens=1000)
        messages = [{"role": "user", "content": "test"}]

        result = client.complete(messages)

        self.assertEqual(result, "response content")
        mock_client.chat.completions.create.assert_called_once()

    @patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "test_key", "AZURE_OPENAI_ENDPOINT": "https://test.endpoint"})
    @patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
    def test_azure_single_client_complete_with_response_format(self, mock_azure_client_class):
        """Test AzureSingleClient complete with response_format."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response content"
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_client_class.return_value = mock_client

        client = llm_clients.AzureSingleClient(model="gpt-5.2", max_tokens=1000)
        messages = [{"role": "user", "content": "test"}]
        response_format = {"type": "json_object"}

        result = client.complete(messages, response_format=response_format)

        self.assertEqual(result, "response content")
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs["response_format"], response_format)


class TestMistralSingleClient(unittest.TestCase):
    """Test MistralSingleClient class."""

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}, clear=False)
    @patch("radmatch.llm_utils.llm_clients.Mistral")
    def test_mistral_single_client_complete_string(self, mock_mistral_client_class):
        """Test MistralSingleClient complete with string content."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response content"
        mock_client.chat.complete.return_value = mock_response
        mock_mistral_client_class.return_value = mock_client

        client = llm_clients.MistralSingleClient(model="magistral-medium-2509", max_tokens=1000)
        messages = [{"role": "user", "content": "test"}]

        result = client.complete(messages)

        self.assertEqual(result, "response content")
        mock_client.chat.complete.assert_called_once()

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}, clear=False)
    @patch("radmatch.llm_utils.llm_clients.Mistral")
    def test_mistral_single_client_complete_list_content(self, mock_mistral_client_class):
        """Test MistralSingleClient complete with list content (converts to JSON)."""
        import json

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        findings_data = [{"finding_id": "f1", "text": "Finding"}]
        mock_response.choices[0].message.content = findings_data
        mock_client.chat.complete.return_value = mock_response
        mock_mistral_client_class.return_value = mock_client

        client = llm_clients.MistralSingleClient(model="magistral-medium-2509", max_tokens=1000)
        messages = [{"role": "user", "content": "test"}]

        result = client.complete(messages)

        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertEqual(parsed, findings_data)

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key"}, clear=False)
    @patch("radmatch.llm_utils.llm_clients.Mistral")
    def test_mistral_single_client_complete_dict_content(self, mock_mistral_client_class):
        """Test MistralSingleClient complete with dict content (converts to JSON)."""
        import json

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        dict_data = {"key": "value"}
        mock_response.choices[0].message.content = dict_data
        mock_client.chat.complete.return_value = mock_response
        mock_mistral_client_class.return_value = mock_client

        client = llm_clients.MistralSingleClient(model="magistral-medium-2509", max_tokens=1000)
        messages = [{"role": "user", "content": "test"}]

        result = client.complete(messages)

        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertEqual(parsed, dict_data)

    def test_mistral_single_client_missing_api_key(self):
        """Test MistralSingleClient raises error when API key is missing."""
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(EnvironmentError):
            llm_clients.MistralSingleClient(model="magistral-medium-2509", max_tokens=1000)
