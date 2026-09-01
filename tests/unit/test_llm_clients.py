"""LLM client utilities — retry policy and provider dispatch."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from mistralai.models import SDKError as MistralSDKError

from radmatch import constants
from radmatch.llm_utils import llm_clients


def _rate_limit() -> openai.RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
    return openai.RateLimitError("rate limit", response=response, body=None)


def _mistral_sdk_error() -> MistralSDKError:
    response = httpx.Response(500, request=httpx.Request("POST", "https://example.test"))
    return MistralSDKError("server error", raw_response=response)


def _client(*, return_value=None, side_effect=None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.complete.side_effect = side_effect
    else:
        client.complete.return_value = return_value
    return client


# ============================================================================
# call_llm — retry policy (tenacity-backed)
# ============================================================================


def test_call_llm_returns_content_on_first_try():
    client = _client(return_value="ok")
    assert llm_clients.call_llm(client, messages=[]) == "ok"
    assert client.complete.call_count == 1


@pytest.mark.parametrize(
    "side_effect",
    [
        pytest.param([_rate_limit(), _rate_limit(), "ok"], id="rate-limit-twice-then-ok"),
        pytest.param(["", "ok"], id="empty-response-then-ok"),
        pytest.param([_mistral_sdk_error(), "ok"], id="mistral-sdk-error-then-ok"),
    ],
)
@patch("tenacity.nap.time.sleep")
def test_call_llm_retries_then_succeeds(_sleep, side_effect):
    client = _client(side_effect=side_effect)
    assert llm_clients.call_llm(client, messages=[]) == "ok"
    assert client.complete.call_count == len(side_effect)


@patch("tenacity.nap.time.sleep")
def test_call_llm_gives_up_after_max_retries(_sleep):
    client = _client(side_effect=_rate_limit())
    with pytest.raises(openai.RateLimitError):
        llm_clients.call_llm(client, messages=[])
    assert client.complete.call_count == constants.MAX_RETRIES


def test_call_llm_does_not_retry_non_retryable_errors():
    client = _client(side_effect=ValueError("non-retryable"))
    with pytest.raises(ValueError):
        llm_clients.call_llm(client, messages=[])
    assert client.complete.call_count == 1


# ============================================================================
# build_client — provider dispatch
# ============================================================================


@patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "k", "AZURE_OPENAI_ENDPOINT": "https://e"}, clear=True)
@patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
def test_build_client_routes_gpt_to_azure_when_endpoint_set(mock_cls):
    """AZURE_OPENAI_ENDPOINT present → the Azure SDK class, aimed at that resource."""
    client = llm_clients.build_client(model="gpt-5.2", max_tokens=100)
    assert isinstance(client, llm_clients.OpenAIClient)
    assert mock_cls.call_args.kwargs["azure_endpoint"] == "https://e"
    assert llm_clients.OpenAIClient.describe_endpoint() == "azure: https://e"


@patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True)
@patch("radmatch.llm_utils.llm_clients.OpenAI")
def test_build_client_routes_gpt_to_openai_when_no_azure_endpoint(mock_cls):
    """No Azure endpoint → plain api.openai.com with OPENAI_API_KEY. The public-user path."""
    client = llm_clients.build_client(model="gpt-5.2", max_tokens=100)
    assert isinstance(client, llm_clients.OpenAIClient)
    assert mock_cls.call_args.kwargs["api_key"] == "k"
    assert "azure_endpoint" not in mock_cls.call_args.kwargs
    assert llm_clients.OpenAIClient.describe_endpoint() == "api.openai.com"


def test_assert_credentials_accepts_either_openai_route():
    """Either OPENAI_API_KEY or the AZURE_OPENAI_* pair satisfies an OpenAI-family model."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True):
        llm_clients.assert_credentials_for("gpt-5.2")  # no raise
    with patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "k", "AZURE_OPENAI_ENDPOINT": "https://e"}, clear=True):
        llm_clients.assert_credentials_for("gpt-5.2")  # no raise
    # A partial Azure set is not a valid route, and neither is nothing at all.
    with patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": "https://e"}, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("gpt-5.2")
    with patch.dict(os.environ, {}, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("gpt-5.2")


@patch.dict(os.environ, {"MISTRAL_API_KEY": "k"}, clear=False)
@patch("radmatch.llm_utils.llm_clients.Mistral")
def test_build_client_dispatches_mistral(_):
    client = llm_clients.build_client(model="magistral-medium-2509", max_tokens=100)
    assert isinstance(client, llm_clients.MistralClient)


def test_build_client_unknown_model_raises():
    with pytest.raises(ValueError):
        llm_clients.build_client(model="unknown-model-12345", max_tokens=100)


@patch.dict(os.environ, {"RADMATCH_LOCAL_BASE_URL": "http://localhost:8000/v1"})
@patch("radmatch.llm_utils.llm_clients.OpenAI")
def test_build_client_dispatches_local(_):
    """A `local:` prefix routes to LocalOpenAIClient and strips the prefix from the served name."""
    client = llm_clients.build_client(model="local:google/medgemma-1.5-4b-it", max_tokens=100)
    assert isinstance(client, llm_clients.LocalOpenAIClient)
    assert client.model == "google/medgemma-1.5-4b-it"  # prefix stripped, case + slashes preserved


@patch.dict(os.environ, {"RADMATCH_LOCAL_BASE_URL": "http://localhost:8000/v1"})
@patch("radmatch.llm_utils.llm_clients.OpenAI")
def test_local_client_sends_served_name_and_max_tokens(mock_cls):
    """complete() sends the served model name and uses `max_tokens` (not max_completion_tokens)."""
    inst = mock_cls.return_value
    inst.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
    client = llm_clients.build_client(model="local:qwen/Qwen3.5-9B", max_tokens=123)
    assert client.complete([{"role": "user", "content": "hi"}]) == "ok"
    kwargs = inst.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "qwen/Qwen3.5-9B"
    assert kwargs["max_tokens"] == 123
    assert "max_completion_tokens" not in kwargs


def test_assert_credentials_for_local_requires_base_url():
    """A `local:` model needs RADMATCH_LOCAL_BASE_URL; nothing else."""
    with patch.dict(os.environ, {}, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("local:google/gemma-4-26B-A4B-it")
    with patch.dict(os.environ, {"RADMATCH_LOCAL_BASE_URL": "http://localhost:8000/v1"}, clear=True):
        llm_clients.assert_credentials_for("local:google/gemma-4-26B-A4B-it")  # no raise


@patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "k", "AZURE_OPENAI_ENDPOINT": "https://e"}, clear=True)
@patch("radmatch.llm_utils.llm_clients.AzureOpenAI")
def test_build_client_case_insensitive(_):
    client = llm_clients.build_client(model="GPT-5", max_tokens=100)
    assert isinstance(client, llm_clients.OpenAIClient)


def test_assert_credentials_for_mistral_missing_key():
    """Missing MISTRAL_API_KEY surfaces at the assert_credentials_for entry, not mid-pipeline."""
    with patch.dict(os.environ, {}, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("magistral-medium-2509")


@patch.dict(
    os.environ,
    {"ANTHROPIC_FOUNDRY_API_KEY": "k", "ANTHROPIC_FOUNDRY_BASE_URL": "https://r.services.ai.azure.com/anthropic"},
    clear=True,
)
@patch("radmatch.llm_utils.llm_clients.AnthropicFoundry")
def test_build_client_routes_claude_to_foundry_when_base_url_set(mock_cls):
    client = llm_clients.build_client(model="claude-opus-4-8", max_tokens=100)
    assert isinstance(client, llm_clients.AnthropicClient)
    assert mock_cls.call_args.kwargs["base_url"] == "https://r.services.ai.azure.com/anthropic"


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True)
@patch("radmatch.llm_utils.llm_clients.anthropic.Anthropic")
def test_build_client_routes_claude_to_direct_api_when_no_foundry_url(mock_cls):
    """No Foundry base URL → api.anthropic.com with ANTHROPIC_API_KEY. The public-user path."""
    client = llm_clients.build_client(model="claude-opus-4-8", max_tokens=100)
    assert isinstance(client, llm_clients.AnthropicClient)
    assert mock_cls.call_args.kwargs["api_key"] == "k"
    assert llm_clients.AnthropicClient.describe_endpoint() == "api.anthropic.com"


def test_assert_credentials_accepts_either_anthropic_route():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
        llm_clients.assert_credentials_for("claude-opus-4-8")  # no raise
    with patch.dict(
        os.environ, {"ANTHROPIC_FOUNDRY_API_KEY": "k", "ANTHROPIC_FOUNDRY_BASE_URL": "https://r"}, clear=True
    ):
        llm_clients.assert_credentials_for("claude-opus-4-8")  # no raise
    with patch.dict(os.environ, {}, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("claude-opus-4-8")


@patch.dict(
    os.environ,
    {"ANTHROPIC_FOUNDRY_API_KEY": "k", "ANTHROPIC_FOUNDRY_BASE_URL": "https://r/anthropic"},
    clear=True,
)
@patch("radmatch.llm_utils.llm_clients.AnthropicFoundry")
def test_anthropic_maps_reasoning_to_effort(mock_cls):
    """`reasoning` → Anthropic `output_config.effort`; `none` omits it (model default)."""
    inst = mock_cls.return_value
    block = MagicMock()
    block.type = "text"
    block.text = "ok"
    inst.messages.create.return_value = MagicMock(content=[block])

    high = llm_clients.build_client(model="claude-opus-4-8", max_tokens=100, reasoning="high")
    high.complete([{"role": "user", "content": "hi"}])
    assert inst.messages.create.call_args.kwargs["output_config"] == {"effort": "high"}

    none = llm_clients.build_client(model="claude-opus-4-8", max_tokens=100, reasoning="none")
    none.complete([{"role": "user", "content": "hi"}])
    assert "output_config" not in inst.messages.create.call_args.kwargs


def test_assert_credentials_for_claude_requires_dedicated_vars():
    """Claude needs its own ANTHROPIC_FOUNDRY_* vars — the Azure ones don't satisfy it."""
    azure_only = {"AZURE_OPENAI_API_KEY": "k", "AZURE_OPENAI_ENDPOINT": "https://e"}
    with patch.dict(os.environ, azure_only, clear=True), pytest.raises(EnvironmentError):
        llm_clients.assert_credentials_for("claude-opus-4-8")
    env = {"ANTHROPIC_FOUNDRY_API_KEY": "k", "ANTHROPIC_FOUNDRY_BASE_URL": "https://r/anthropic"}
    with patch.dict(os.environ, env, clear=True):
        llm_clients.assert_credentials_for("claude-opus-4-8")  # no raise


# ============================================================================
# _coerce_structured_tool_input — undo Claude's double-encoded tool input
# ============================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        # whole object stringified under the single schema key
        ({"findings": '{"findings": [{"text": "a"}]}'}, {"findings": [{"text": "a"}]}),
        # just the array stringified under its key
        ({"findings": '[{"text": "a"}]'}, {"findings": [{"text": "a"}]}),
        # individual field stringified in a multi-key object
        ({"matches": "[1, 2]", "note": "plain"}, {"matches": [1, 2], "note": "plain"}),
        # already-clean object is untouched
        ({"findings": [{"text": "a"}]}, {"findings": [{"text": "a"}]}),
        # free-text that isn't JSON stays a string
        ({"text": "Stable cardiomegaly."}, {"text": "Stable cardiomegaly."}),
    ],
)
def test_coerce_structured_tool_input(raw, expected):
    assert llm_clients._coerce_structured_tool_input(raw) == expected


@patch.dict(
    os.environ,
    {"ANTHROPIC_FOUNDRY_API_KEY": "k", "ANTHROPIC_FOUNDRY_BASE_URL": "https://r/anthropic"},
    clear=True,
)
@patch("radmatch.llm_utils.llm_clients.AnthropicFoundry")
def test_anthropic_structured_output_unwraps_double_encoding(mock_cls):
    """A tool_use block whose input double-encodes the answer is unwrapped to clean JSON."""
    inst = mock_cls.return_value
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"findings": '{"findings": [{"text": "pneumothorax"}]}'}
    inst.messages.create.return_value = MagicMock(content=[block])

    client = llm_clients.build_client(model="claude-opus-4-8", max_tokens=100)
    out = client.complete(
        [{"role": "user", "content": "hi"}],
        response_format={"json_schema": {"schema": {"type": "object", "properties": {"findings": {}}}}},
    )
    assert json.loads(out) == {"findings": [{"text": "pneumothorax"}]}
