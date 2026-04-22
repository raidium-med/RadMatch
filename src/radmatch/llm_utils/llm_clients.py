"""Utility classes to interact with supported LLM chat providers."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path  # noqa: TC003
from typing import Callable, Mapping, Sequence, TypeVar

from mistralai import Mistral
from openai import AzureOpenAI

from radmatch import constants

# Reduce noisy HTTP logs emitted by the provider SDKs
for noisy_logger in ("httpx", "httpcore", "openai", "mistralai.http_client", "mistralai"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# ============================================================================
# Single Inference Clients
# ============================================================================


class SingleClient:
    """Minimal interface for provider-specific single inference clients."""

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        self.model = model
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def complete(
        self, messages: Sequence[Mapping[str, object]], response_format: Mapping[str, object] | None = None
    ) -> str:
        """Perform a chat completion request."""
        raise NotImplementedError


class AzureSingleClient(SingleClient):
    """Wrapper around the Azure OpenAI chat completions API for single inference."""

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        self._client = AzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version="2024-12-01-preview",
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        )

    def complete(
        self, messages: Sequence[Mapping[str, object]], response_format: Mapping[str, object] | None = None
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=response_format,
            max_completion_tokens=self.max_tokens,
            reasoning_effort=self.reasoning,
        )
        return response.choices[0].message.content


class MistralSingleClient(SingleClient):
    """Single inference client for Mistral."""

    def __init__(self, model: str, max_tokens: int, reasoning: str = "none"):
        super().__init__(model=model, max_tokens=max_tokens, reasoning=reasoning)
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise EnvironmentError("Missing MISTRAL_API_KEY environment variable.")
        self._client = Mistral(api_key=api_key)

    def complete(
        self, messages: Sequence[Mapping[str, object]], response_format: Mapping[str, object] | None = None
    ) -> str:
        response = self._client.chat.complete(
            model=self.model,
            messages=messages,
            response_format=response_format,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning,
        )
        content = response.choices[0].message.content
        # Handle case where content is already parsed (list/dict) instead of string
        if not isinstance(content, str):
            return json.dumps(content, ensure_ascii=False)
        return content


# ============================================================================
# Batch Clients
# ============================================================================


class BatchClient:
    """Minimal interface for provider-specific batch clients."""

    def __init__(self, model: str, max_tokens: int):
        self.model = model
        self.max_tokens = max_tokens

    def upload_batch_file(self, batch_file_path: Path) -> str:
        """Upload batch file and return file ID."""
        raise NotImplementedError

    def create_batch_job(self, file_id: str) -> str:
        """Create a batch job and return job ID."""
        raise NotImplementedError

    def wait_for_batch_completion(self, job_id: str, check_interval: int = 10) -> None:
        """Wait for batch job to complete, polling status periodically."""
        raise NotImplementedError

    def get_batch_status(self, job_id: str) -> str:
        """Get the current status of a batch job.

        Returns:
            Status string (e.g., "SUCCESS", "FAILED", "IN_PROGRESS", etc.)
        """
        raise NotImplementedError

    def download_batch_results(self, job_id: str) -> list[dict[str, object]]:
        """Download and parse batch job results."""
        raise NotImplementedError


class MistralBatchClient(BatchClient):
    """Batch client for Mistral."""

    def __init__(self, model: str, max_tokens: int):
        super().__init__(model=model, max_tokens=max_tokens)
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise EnvironmentError("Missing MISTRAL_API_KEY environment variable for batch inference.")
        self._client = Mistral(api_key=api_key)

    def upload_batch_file(self, batch_file_path: Path) -> str:
        """Upload batch file to Mistral and return file ID."""
        with batch_file_path.open("rb") as f:
            batch_data = self._client.files.upload(
                file={"file_name": batch_file_path.name, "content": f}, purpose="batch"
            )
        return batch_data.id

    def create_batch_job(self, file_id: str) -> str:
        """Create a batch job and return job ID."""
        created_job = self._client.batch.jobs.create(
            input_files=[file_id],
            model=self.model,
            endpoint="/v1/chat/completions",
            metadata={"job_type": "finding_extraction"},
        )
        return created_job.id

    def get_batch_status(self, job_id: str) -> str:
        """Get the current status of a batch job."""
        try:
            job = self._client.batch.jobs.get(job_id=job_id)
            return job.status
        except Exception as exc:
            # SDK can raise various exceptions; check error string for specific cases
            error_str = str(exc)
            if "404" in error_str or "Not Found" in error_str:
                raise ValueError(f"Batch job ID '{job_id}' not found. Please verify the job ID is correct.") from exc
            raise RuntimeError(f"Failed to get batch job status: {exc}") from exc

    def wait_for_batch_completion(self, job_id: str, check_interval: int = 10) -> None:
        """Wait for batch job to complete, polling status periodically."""
        logger = logging.getLogger(__name__)
        while True:
            job = self._client.batch.jobs.get(job_id=job_id)
            status = job.status

            logger.info(f"Batch job status: {status}")

            if status in ("SUCCESS", "FAILED", "TIMEOUT_EXCEEDED", "CANCELLED"):
                break

            if status == "CANCELLATION_REQUESTED":
                logger.warning("Batch job cancellation requested")
                time.sleep(check_interval)
                continue

            time.sleep(check_interval)

        if status != "SUCCESS":
            raise RuntimeError(f"Batch job {job_id} ended with status: {status}")

    def download_batch_results(self, job_id: str) -> list[dict[str, object]]:
        """Download and parse batch job results."""
        import json

        job = self._client.batch.jobs.get(job_id=job_id)

        if not job.output_file:
            raise RuntimeError(f"Batch job {job_id} has no output file")

        output_file_stream = self._client.files.download(file_id=job.output_file)
        content = output_file_stream.read().decode("utf-8")

        results = []
        logger = logging.getLogger(__name__)
        for line in content.strip().splitlines():
            if not line.strip():
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning(f"Failed to parse batch result line: {exc}")

        return results


class AzureBatchClient(BatchClient):
    """Batch client for Azure OpenAI."""

    def __init__(self, model: str, max_tokens: int):
        super().__init__(model=model, max_tokens=max_tokens)
        self._client = AzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            api_version="2024-12-01-preview",
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        )

    def upload_batch_file(self, batch_file_path: Path) -> str:
        """Upload batch file to Azure OpenAI and return file ID."""
        with batch_file_path.open("rb") as f:
            batch_data = self._client.files.create(file=f, purpose="batch")
        return batch_data.id

    def create_batch_job(self, file_id: str) -> str:
        """Create a batch job and return job ID."""
        created_job = self._client.batches.create(
            input_file_id=file_id, endpoint="/chat/completions", completion_window="24h"
        )
        return created_job.id

    def get_batch_status(self, job_id: str) -> str:
        """Get the current status of a batch job."""
        try:
            job = self._client.batches.retrieve(batch_id=job_id)
            return job.status
        except Exception as exc:
            # SDK can raise various exceptions; check error string for specific cases
            error_str = str(exc)
            if "404" in error_str or "Not Found" in error_str:
                raise ValueError(f"Batch job ID '{job_id}' not found. Please verify the job ID is correct.") from exc
            raise RuntimeError(f"Failed to get batch job status: {exc}") from exc

    def wait_for_batch_completion(self, job_id: str, check_interval: int = 10) -> None:
        """Wait for batch job to complete, polling status periodically."""
        logger = logging.getLogger(__name__)
        while True:
            job = self._client.batches.retrieve(batch_id=job_id)
            status = job.status

            logger.info(f"Batch job status: {status}")

            if status in ("completed", "failed", "expired", "cancelled"):
                break

            if status == "cancelling":
                logger.warning("Batch job cancellation requested")
                time.sleep(check_interval)
                continue

            time.sleep(check_interval)

        if status != "completed":
            raise RuntimeError(f"Batch job {job_id} ended with status: {status}")

    def download_batch_results(self, job_id: str) -> list[dict[str, object]]:
        """Download and parse batch job results."""
        import json

        job = self._client.batches.retrieve(batch_id=job_id)

        if not job.output_file_id:
            raise RuntimeError(f"Batch job {job_id} has no output file")

        output_file_stream = self._client.files.content(file_id=job.output_file_id)
        content = output_file_stream.read().decode("utf-8")

        results = []
        logger = logging.getLogger(__name__)
        for line in content.strip().splitlines():
            if not line.strip():
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning(f"Failed to parse batch result line: {exc}")

        return results


# ============================================================================
# Factory Functions
# ============================================================================


def build_single_client(model: str, max_tokens: int, reasoning: str = "none") -> SingleClient:
    """Build a single inference client for the given model."""
    provider = constants.MODEL_TO_PROVIDER.get(model.strip().lower())
    if provider == "azure":
        return AzureSingleClient(model=model, max_tokens=max_tokens, reasoning=reasoning)
    elif provider == "mistral":
        return MistralSingleClient(model=model, max_tokens=max_tokens, reasoning=reasoning)
    else:
        raise ValueError(f"Unsupported provider '{provider}' for single inference client.")


def build_batch_client(model: str, max_tokens: int) -> BatchClient:
    """Build a batch client for the given model."""
    provider = constants.MODEL_TO_PROVIDER.get(model.strip().lower())
    if provider == "azure":
        return AzureBatchClient(model=model, max_tokens=max_tokens)
    elif provider == "mistral":
        return MistralBatchClient(model=model, max_tokens=max_tokens)
    else:
        raise ValueError(f"Unsupported provider '{provider}' for batch client. Supported providers: azure, mistral")


# ============================================================================
# Retry Logic
# ============================================================================

T = TypeVar("T")


def is_rate_limit_error(error: Exception) -> bool:
    """Check if error is a rate limit error."""
    error_msg = str(error).lower()
    return "rate_limit" in error_msg or "quota" in error_msg


def is_content_filter_error(error: Exception) -> bool:
    """Check if error is a content filter error."""
    error_msg = str(error).lower()
    return "content_filter" in error_msg or "responsibleai" in error_msg


def call_with_llm_retry(
    func: Callable[[], T],
    max_retries: int | None = None,
    backoff_factor: float = 2.0,
    series_uuid: str | None = None,
    logger_instance: logging.Logger | None = None,
) -> tuple[T | None, str | None]:
    """Call a function with retry logic for LLM API calls using exponential backoff."""
    if max_retries is None:
        max_retries = constants.MAX_RETRIES
    if logger_instance is None:
        logger_instance = logging.getLogger(__name__)

    failure_reason = "Unknown API failure"
    for attempt in range(max_retries):
        try:
            result = func()
            return result, None
        except Exception as exc:
            failure_reason = str(exc)

            # Content filter errors: don't retry
            if is_content_filter_error(exc):
                if series_uuid:
                    logger_instance.warning("[Report %s] Content filter triggered", series_uuid)
                failure_reason = "Content filter triggered"
                break

            # Rate limit errors: retry with backoff
            if is_rate_limit_error(exc):
                wait = (attempt + 1) * backoff_factor
                if series_uuid:
                    logger_instance.warning("[Report %s] Rate limited, waiting %ss", series_uuid, wait)
                time.sleep(wait)
                continue

            # Other errors: retry if attempts remain
            if attempt < max_retries - 1:
                wait = (attempt + 1) * backoff_factor
                if series_uuid:
                    logger_instance.warning(
                        f"[Report %s] ({attempt + 1}/{max_retries}) API error, retrying in %ss: %s",
                        series_uuid,
                        wait,
                        exc,
                    )
                time.sleep(wait)
            else:
                if series_uuid:
                    logger_instance.error("[Report %s] Failed after %s attempts: %s", series_uuid, max_retries, exc)
                failure_reason = f"API call failed after {max_retries} attempts: {exc}"

    return None, failure_reason
