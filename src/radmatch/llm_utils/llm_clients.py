"""Utility classes to interact with supported LLM chat providers."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Mapping, Sequence

import anthropic
import openai
from anthropic import AnthropicFoundry
from mistralai import Mistral
from mistralai.models import SDKError as MistralSDKError
from openai import AzureOpenAI, OpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_random_exponential,
)

from radmatch import constants

# Reduce noisy HTTP logs emitted by the provider SDKs
for noisy_logger in ("httpx", "httpcore", "openai", "mistralai.http_client", "mistralai", "anthropic"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ============================================================================
# Token-usage accounting
# ============================================================================
_usage_lock = threading.Lock()
_token_usage: dict[str, dict[str, int]] = {}


def reset_token_usage() -> None:
    with _usage_lock:
        _token_usage.clear()


# A cache *write* is billed at 1.25x input (ephemeral 5-minute TTL, RadMatch's
# default); a cache *read* at the model's `cached_input` rate (~0.1x input).
_CACHE_WRITE_MULT = 1.25


def _record_usage(model: str, uncached_input: int, cache_read: int, cache_write: int, output: int) -> None:
    with _usage_lock:
        entry = _token_usage.setdefault(
            model, {"uncached_input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "calls": 0}
        )
        entry["uncached_input"] += int(uncached_input or 0)
        entry["cache_read"] += int(cache_read or 0)
        entry["cache_write"] += int(cache_write or 0)
        entry["output"] += int(output or 0)
        entry["calls"] += 1


def token_report() -> dict[str, object]:
    """The two `metrics_summary` token fields for usage since the last reset:
    `token_usage` (prompt = total input incl. cached, completion, calls) and
    `token_cost` in USD (uncached input at the `input` rate, cache reads at
    `cached_input`, cache writes at 1.25x input; models absent from
    `constants.MODEL_PRICING` — e.g. any self-hosted `local:` model — contribute 0)."""
    with _usage_lock:
        by_model = [(model, dict(counts)) for model, counts in _token_usage.items()]
    pricing = {name.lower(): price for name, price in constants.MODEL_PRICING.items()}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    cost = 0.0
    for model, c in by_model:
        usage["prompt_tokens"] += c["uncached_input"] + c["cache_read"] + c["cache_write"]
        usage["completion_tokens"] += c["output"]
        usage["calls"] += c["calls"]
        price = pricing.get(model.strip().lower())
        if price is not None:
            cost += (
                c["uncached_input"] * price["input"]
                + c["cache_read"] * price.get("cached_input", price["input"])
                + c["cache_write"] * price["input"] * _CACHE_WRITE_MULT
                + c["output"] * price["output"]
            ) / 1e6
    return {"token_usage": usage, "token_cost": round(cost, 4)}


def _usage_counts(usage: object, *, anthropic: bool = False) -> tuple[int, int, int, int]:
    """Read (uncached_input, cache_read, cache_write, output) from a provider `usage`.

    Anthropic reports `input_tokens` as the *uncached* remainder, with separate
    `cache_read_input_tokens` / `cache_creation_input_tokens`. OpenAI-style
    `prompt_tokens` is the *total* input; the cached subset is under
    `prompt_tokens_details.cached_tokens` and there is no separate write bucket."""
    if usage is None:
        return 0, 0, 0, 0
    if anthropic:
        return (
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    cache_read = int(getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
    return prompt - cache_read, cache_read, 0, int(getattr(usage, "completion_tokens", 0) or 0)


# ============================================================================
# Inference Clients
# ============================================================================


class Client:
    """Minimal interface for provider-specific inference clients."""

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        self.model = model
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """Perform a chat completion request."""
        raise NotImplementedError


class OpenAIClient(Client):
    """Chat-completions client for the OpenAI API surface.

    Two endpoints, one wire format: `AZURE_OPENAI_ENDPOINT` if set (`self.model` is
    then the deployment name), else `api.openai.com`.
    """

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if azure_endpoint:
            self._client = AzureOpenAI(
                api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
                api_version="2024-12-01-preview",
                azure_endpoint=azure_endpoint,
                timeout=constants.LLM_REQUEST_TIMEOUT_S,
                max_retries=0,  # tenacity (`call_llm`) is the single retry layer; don't stack SDK retries on top
            )
        else:
            self._client = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                timeout=constants.LLM_REQUEST_TIMEOUT_S,
                max_retries=0,
            )

    @staticmethod
    def describe_endpoint() -> str:
        azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        return f"azure: {azure_endpoint}" if azure_endpoint else "api.openai.com"

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "response_format": response_format,
            "max_completion_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "timeout": timeout if timeout is not None else openai.NOT_GIVEN,
        }
        # Some Azure GPT-5 endpoints reject reasoning_effort="none"; omit it unless set.
        if self.reasoning != "none":
            kwargs["reasoning_effort"] = self.reasoning
        response = self._client.chat.completions.create(**kwargs)
        _record_usage(self.model, *_usage_counts(getattr(response, "usage", None)))
        return response.choices[0].message.content or ""


# Self-hosted servers accept both knobs, so a local judge can be made reproducible; the
# hosted APIs offer neither a determinism guarantee nor a usable seed. vLLM falls back to
# temperature 1.0 when the field is omitted, which made repeat runs sample independently.
_LOCAL_TEMPERATURE: float = float(os.environ.get("RADMATCH_LOCAL_TEMPERATURE") or 0.0)
_LOCAL_SEED: int = int(os.environ.get("RADMATCH_LOCAL_SEED") or 42)


class LocalOpenAIClient(Client):
    """OpenAI-compatible client for self-hosted models (vLLM / SGLang / Ollama / TGI).

    `self.model` is the server's served-model name, which vLLM/SGLang default to the
    HF path. `reasoning` is not applied and `max_tokens` is used rather than
    `max_completion_tokens` — neither is portable across these servers.
    """

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        # RADMATCH_LOCAL_BASE_URL is validated upstream by `assert_credentials_for`.
        self._client = OpenAI(
            base_url=os.environ.get("RADMATCH_LOCAL_BASE_URL"),
            api_key=os.environ.get("RADMATCH_LOCAL_API_KEY") or "EMPTY",  # most local servers ignore the key
            timeout=constants.LLM_REQUEST_TIMEOUT_S,
            max_retries=0,  # tenacity (`call_llm`) is the single retry layer
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=response_format,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            temperature=_LOCAL_TEMPERATURE,
            seed=_LOCAL_SEED,
            timeout=timeout if timeout is not None else openai.NOT_GIVEN,
        )
        # Record under a `local:`-namespaced key so a served name that happens to
        # match a hosted model (e.g. `deepseek-v4-pro`) is never priced as hosted.
        _record_usage(
            f"local:{self.model}",
            *_usage_counts(getattr(response, "usage", None)),
        )
        return response.choices[0].message.content or ""


class MistralClient(Client):
    """Inference client for Mistral."""

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        # MISTRAL_API_KEY is validated upstream by `assert_credentials_for`.
        self._client = Mistral(
            api_key=os.environ.get("MISTRAL_API_KEY"),
            timeout_ms=int(constants.LLM_REQUEST_TIMEOUT_S * 1000),
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        # Mistral's chat.complete has no `reasoning_effort` param (magistral
        # reasons inherently), so the `reasoning` knob is not applied here.
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "response_format": response_format,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if timeout is not None:
            kwargs["timeout_ms"] = int(timeout * 1000)
        response = self._client.chat.complete(**kwargs)
        _record_usage(self.model, *_usage_counts(getattr(response, "usage", None)))
        content = response.choices[0].message.content
        # Mistral can return content as a list/dict for structured outputs;
        # serialise to a JSON string for downstream uniformity.
        if not isinstance(content, str):
            return json.dumps(content, ensure_ascii=False) if content is not None else ""
        return content


def _split_system_messages(
    messages: Sequence[Mapping[str, object]],
) -> tuple[str | None, list[dict[str, object]]]:
    """Anthropic takes the system prompt as a separate top-level field, not a
    `role: system` message — split it out of the OpenAI-style message list."""
    system_parts: list[str] = []
    chat: list[dict[str, object]] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(str(m.get("content", "")))
        else:
            chat.append({"role": m.get("role"), "content": m.get("content", "")})
    return ("\n\n".join(p for p in system_parts if p) or None), chat


def _ephemeral_cache_block(text: str) -> dict[str, object]:
    """A text content block marked for Anthropic prompt caching (5-minute TTL)."""
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def _closed_schema(schema: object) -> object:
    """Recursively set `additionalProperties: false`, which `output_config.format` requires."""
    if isinstance(schema, dict):
        out = {k: _closed_schema(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_closed_schema(v) for v in schema]
    return schema


class AnthropicClient(Client):
    """Claude on Azure Foundry via the Anthropic Messages API.

    Claude on Foundry answers only `/anthropic/v1/messages`, not the OpenAI
    surface, so it uses the Anthropic SDK. Three shape differences from the
    OpenAI clients are absorbed here so the rest of the pipeline is unchanged:
    the system prompt moves to a top-level field; `response_format` json_schema maps
    to Anthropic's native `output_config.format`, which returns the object as a text
    block; and the response is a list of content blocks.

    Two endpoints: Azure Foundry's Messages API when `ANTHROPIC_FOUNDRY_BASE_URL` is
    set (via the SDK's `AnthropicFoundry` class, which carries the Foundry auth
    headers), else `api.anthropic.com`. `complete()` is identical for both.

    `reasoning` maps to Anthropic's `output_config.effort` (low/medium/high);
    `none` omits it so the model uses its default (high for Opus 4.8). This
    mirrors the OpenAI clients' `reasoning_effort` so `--reasoning` controls all
    providers uniformly.
    """

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        foundry_base_url = os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL")
        if foundry_base_url:
            self._client = AnthropicFoundry(
                api_key=os.environ.get("ANTHROPIC_FOUNDRY_API_KEY"),
                base_url=foundry_base_url,
                timeout=constants.LLM_REQUEST_TIMEOUT_S,
                max_retries=0,  # tenacity (`call_llm`) is the single retry layer
            )
        else:
            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                timeout=constants.LLM_REQUEST_TIMEOUT_S,
                max_retries=0,
            )

    @staticmethod
    def describe_endpoint() -> str:
        foundry_base_url = os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL")
        return f"foundry: {foundry_base_url}" if foundry_base_url else "api.anthropic.com"

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        response_format: Mapping[str, object] | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str:
        system, chat = _split_system_messages(messages)
        # Mark the stable prefix (system + few-shot) for prompt caching. The
        # last chat entry is the varying query, so the one before it ends the prefix.
        if len(chat) >= 2 and isinstance(chat[-2].get("content"), str):
            chat[-2] = {"role": chat[-2].get("role"), "content": [_ephemeral_cache_block(chat[-2]["content"])]}
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "messages": chat,
            "timeout": timeout if timeout is not None else anthropic.NOT_GIVEN,
        }
        if system:
            kwargs["system"] = [_ephemeral_cache_block(system)]
        output_config: dict[str, object] = {}
        if self.reasoning != "none":
            output_config["effort"] = self.reasoning
        if response_format is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": _closed_schema(response_format["json_schema"]["schema"]),
            }
        if output_config:
            kwargs["output_config"] = output_config

        message = self._client.messages.create(**kwargs)
        _record_usage(self.model, *_usage_counts(getattr(message, "usage", None), anthropic=True))
        blocks = message.content or []
        return "".join(b.text for b in blocks if getattr(b, "type", None) == "text")


# ============================================================================
# Factory functions
# ============================================================================


# Self-hosted models are addressed with a `local:` scheme prefix
# (e.g. `local:google/medgemma-1.5-4b-it`) rather than a MODEL_CATALOG entry, so any
# OpenAI-compatible server (vLLM/SGLang/Ollama/...) works without a code change. The
# part after `local:` is the server's served-model name.
_LOCAL_PREFIX = "local:"

# Credentials accepted by each provider, as alternative sets: a provider is satisfied
# when *any one* of its sets is fully present. `openai` and `anthropic` each offer a
# hosted-API route and an Azure route, and the client picks whichever is configured —
# so the check must not demand both.
_PROVIDER_ENV_VARS: dict[str, tuple[tuple[str, ...], ...]] = {
    "openai": (
        ("OPENAI_API_KEY",),
        ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"),
    ),
    "anthropic": (
        ("ANTHROPIC_API_KEY",),
        ("ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_BASE_URL"),
    ),
    "mistral": (("MISTRAL_API_KEY",),),
    "local": (("RADMATCH_LOCAL_BASE_URL",),),
}


def _provider_for(model: str) -> str:
    if model.strip().lower().startswith(_LOCAL_PREFIX):
        return "local"
    provider = constants.MODEL_TO_PROVIDER.get(model.strip().lower())
    if provider is None:
        raise ValueError(
            f"Unsupported model {model!r}. Add it to `radmatch.constants.MODEL_CATALOG`, "
            f"prefix a self-hosted model with `{_LOCAL_PREFIX}`, "
            f"or pass a model from one of: {sorted(constants.MODEL_TO_PROVIDER)}"
        )
    return provider


def _served_model_name(model: str) -> str:
    """Strip the `local:` scheme prefix, preserving the (case-sensitive) served name."""
    m = model.strip()
    return m[len(_LOCAL_PREFIX) :] if m.lower().startswith(_LOCAL_PREFIX) else m


def assert_credentials_for(*models: str) -> None:
    """Raise `EnvironmentError` if a selected model has no usable credentials.

    Called at orchestrator entry points so a missing key fails fast rather than
    mid-pipeline. A provider is satisfied when any one of its alternative sets is
    fully present (e.g. `OPENAI_API_KEY` *or* the `AZURE_OPENAI_*` pair).
    """
    unsatisfied: list[str] = []
    for model in dict.fromkeys(models):
        provider = _provider_for(model)
        option_sets = _PROVIDER_ENV_VARS.get(provider, ())
        if any(all(os.environ.get(var) for var in option) for option in option_sets):
            continue
        alternatives = " or ".join(" + ".join(option) for option in option_sets)
        unsatisfied.append(f"{model!r} (provider {provider!r}) needs {alternatives}")
    if unsatisfied:
        raise EnvironmentError("Missing credentials for the selected model(s): " + "; ".join(unsatisfied))


def describe_model_endpoint(model: str) -> str:
    """Endpoint a model resolves to. Logged, since it comes from the environment."""
    provider = _provider_for(model)
    if provider == "openai":
        return OpenAIClient.describe_endpoint()
    if provider == "anthropic":
        return AnthropicClient.describe_endpoint()
    if provider == "local":
        return f"local: {os.environ.get('RADMATCH_LOCAL_BASE_URL')}"
    return "api.mistral.ai"


def build_client(model: str, max_tokens: int = constants.MAX_TOKENS, reasoning: str = "none") -> Client:
    """Build a inference client for the given model."""
    provider = _provider_for(model)
    logger.info("Model %s → provider %s (%s)", model, provider, describe_model_endpoint(model))
    if provider == "openai":
        return OpenAIClient(model=model, max_tokens=max_tokens, reasoning=reasoning)
    if provider == "mistral":
        return MistralClient(model=model, max_tokens=max_tokens, reasoning=reasoning)
    if provider == "anthropic":
        return AnthropicClient(model=model, max_tokens=max_tokens, reasoning=reasoning)
    if provider == "local":
        return LocalOpenAIClient(model=_served_model_name(model), max_tokens=max_tokens, reasoning=reasoning)
    raise ValueError(f"Unsupported provider '{provider}' for inference client.")


# ============================================================================
# Retry Logic
# ============================================================================


class _EmptyLLMResponseError(Exception):
    pass


_RETRYABLE_LLM_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    MistralSDKError,
    _EmptyLLMResponseError,
)


# Subclasses of the connection errors above, so retried by default.
LLM_TIMEOUT_ERRORS = (openai.APITimeoutError, anthropic.APITimeoutError)

_llm_retry = retry(
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(constants.MAX_RETRIES) | stop_after_delay(3 * constants.LLM_REQUEST_TIMEOUT_S),
    retry=retry_if_exception_type(_RETRYABLE_LLM_ERRORS),
    reraise=True,
)


def call_llm(
    client: Client,
    messages: Sequence[Mapping[str, object]],
    response_format: Mapping[str, object] | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> str:
    """Call `client.complete` with retry on transient errors and empty responses.

    A per-call `timeout` is raised, not retried."""

    @_llm_retry
    def _call() -> str:
        content = client.complete(
            messages=messages, response_format=response_format, max_tokens=max_tokens, timeout=timeout
        )
        if not content:
            raise _EmptyLLMResponseError("Empty API response")
        return content

    if timeout is not None:
        _call = _call.retry_with(retry=_call.retry.retry & retry_if_not_exception_type(LLM_TIMEOUT_ERRORS))
    return _call()
