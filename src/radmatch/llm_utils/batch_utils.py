"""Batch processing utilities for LLM API batch operations."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from radmatch.llm_utils import llm_clients

from radmatch import constants, io

logger = logging.getLogger(__name__)


# ============================================================================
# Batch File Generation Utilities
# ============================================================================


def generate_batch_file_name(base_path: Path, batch_index: int) -> Path:
    """Generate batch file name for a given batch index."""
    stem = base_path.stem
    suffix = base_path.suffix
    return base_path.parent / f"{stem}_{batch_index + 1}{suffix}"


class BatchFileWriter:
    """Helper class for writing batch files with automatic splitting."""

    def __init__(self, base_path: Path, max_requests_per_file: int):
        self.base_path = base_path
        self.max_requests_per_file = max_requests_per_file
        self.batch_files: list[tuple[Path, dict[str, Path]]] = []
        self.current_batch_index = 0
        self.current_series_uuid_map: dict[str, Path] = {}
        self.current_file: Path | None = None
        self.current_file_handle = None
        self.request_index = 0
        self._start_new_batch()

    def _start_new_batch(self) -> None:
        """Start a new batch file."""
        self.current_file = generate_batch_file_name(self.base_path, self.current_batch_index)
        self.current_file.parent.mkdir(parents=True, exist_ok=True)
        self.current_file_handle = self.current_file.open("w", encoding="utf-8")

    def _finalize_current_batch(self) -> None:
        """Close current batch file and add to batch_files list."""
        if self.current_file_handle is not None:
            self.current_file_handle.close()
            self.current_file_handle = None

        if self.current_file and self.current_series_uuid_map:
            self.batch_files.append((self.current_file, self.current_series_uuid_map.copy()))
            logger.info(
                "✓ Created batch file %d with %d requests: %s",
                self.current_batch_index + 1,
                len(self.current_series_uuid_map),
                self.current_file,
            )

        self.current_series_uuid_map = {}
        self.current_batch_index += 1

    def add_request(self, report_path: Path, batch_request: dict) -> str:
        """Add a batch request to the current batch file."""
        if len(self.current_series_uuid_map) >= self.max_requests_per_file:
            self._finalize_current_batch()
            self._start_new_batch()

        custom_id = f"{self.current_batch_index}_{self.request_index}"
        batch_request["custom_id"] = custom_id

        self.current_series_uuid_map[custom_id] = report_path
        self.request_index += 1

        self.current_file_handle.write(json.dumps(batch_request, ensure_ascii=False) + "\n")
        return custom_id

    def finalize(self) -> list[tuple[Path, dict[str, Path]]]:
        """Finalize all batch files and return list of (file_path, series_uuid_map) tuples."""
        self._finalize_current_batch()
        return self.batch_files


def create_batch_files_from_reports(
    report_files: list[Path],
    batch_file_path: Path,
    model_name: str,
    max_tokens: int,
    build_messages_fn: Callable[[Path, str], list[dict[str, object]] | None],
    logger_instance: logging.Logger | None = None,
    reasoning: str = "none",
) -> list[tuple[Path, dict[str, Path]]]:
    """Create batch files from report files."""
    from tqdm import tqdm

    if logger_instance is None:
        logger_instance = logger

    writer = BatchFileWriter(batch_file_path, constants.MAX_REQUESTS_PER_BATCH_FILE)
    skipped_count = 0

    for report_path in tqdm(report_files, desc="Creating batch files", unit="report"):
        report_text = io.read_text_file(report_path, logger_instance)
        if not report_text:
            skipped_count += 1
            continue

        messages = build_messages_fn(report_path, report_text)
        if messages is None:
            skipped_count += 1
            continue

        body: dict[str, object] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning,
        }

        batch_request = {
            "custom_id": "",  # Will be set by add_request
            "body": body,
        }

        writer.add_request(report_path, batch_request)

    batch_files = writer.finalize()

    if skipped_count > 0:
        logger_instance.warning("Skipped %d reports", skipped_count)
        logger_instance.info("")

    if len(batch_files) > 1:
        logger_instance.info(
            "✓ Created %d batch files (max %d requests per file)",
            len(batch_files),
            constants.MAX_REQUESTS_PER_BATCH_FILE,
        )
    logger_instance.info("")
    return batch_files


# ============================================================================
# Batch Job Management
# ============================================================================


def upload_and_create_batch_jobs(
    batch_client: "llm_clients.BatchClient",
    batch_files_data: list[tuple[Path, dict[str, Path]]],
    logger_instance: logging.Logger | None = None,
) -> tuple[list[str], dict[str, Path], dict[str, list[str]]]:
    """Upload batch files and create batch jobs."""
    if logger_instance is None:
        logger_instance = logger

    job_ids: list[str] = []
    merged_series_uuid_map: dict[str, Path] = {}
    job_to_custom_ids: dict[str, list[str]] = {}
    total_batches = len(batch_files_data)

    for batch_index, (batch_file_path_item, series_uuid_map) in enumerate(batch_files_data, start=1):
        logger_instance.info("Uploading batch file %d/%d...", batch_index, total_batches)
        file_id = batch_client.upload_batch_file(batch_file_path_item)
        logger_instance.info("✓ Uploaded batch file %d (file_id: %s)", batch_index, file_id)

        logger_instance.info("Creating batch job %d/%d...", batch_index, total_batches)
        job_id = batch_client.create_batch_job(file_id)
        job_ids.append(job_id)
        logger_instance.info("✓ Batch job %d created (job_id: %s)", batch_index, job_id)

        job_to_custom_ids[job_id] = list(series_uuid_map.keys())
        merged_series_uuid_map.update(series_uuid_map)

    logger_instance.info("")
    return job_ids, merged_series_uuid_map, job_to_custom_ids


def check_batch_status(
    batch_client: "llm_clients.BatchClient",
    job_id: str,
    logger_instance: logging.Logger | None = None,
    require_complete: bool = True,
) -> str | None:
    """Check batch job status."""
    if logger_instance is None:
        logger_instance = logger

    try:
        status = batch_client.get_batch_status(job_id)
    except ValueError as exc:
        logger_instance.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger_instance.error(f"Failed to check batch job status: {exc}")
        sys.exit(1)

    if require_complete and status not in constants.COMPLETED_STATUSES:
        logger_instance.error(f"Batch job {job_id} is not complete. Current status: {status}")
        if status in constants.FAILED_STATUSES:
            logger_instance.error(f"Batch job ended with error status: {status}")
        sys.exit(1)

    return status


def check_batch_job_statuses(
    batch_client: "llm_clients.BatchClient",
    job_ids: list[str],
    logger_instance: logging.Logger | None = None,
    require_complete: bool = True,
) -> list[str]:
    """Check status for multiple batch jobs."""
    if logger_instance is None:
        logger_instance = logger

    total_jobs = len(job_ids)
    if total_jobs == 1:
        logger_instance.info("Checking batch job status...")
    else:
        logger_instance.info("Checking batch job status for %d job(s)...", total_jobs)

    statuses: list[str] = []
    for job_index, job_id in enumerate(job_ids, start=1):
        status = check_batch_status(batch_client, job_id, logger_instance, require_complete=require_complete)
        statuses.append(status)
        if total_jobs > 1:
            logger_instance.info("  Job %d/%d: %s", job_index, total_jobs, status)

    return statuses


def download_batch_results_from_jobs(
    batch_client: "llm_clients.BatchClient",
    job_ids: list[str],
    logger_instance: logging.Logger | None = None,
) -> list[dict[str, object]]:
    """Download results from multiple batch jobs."""
    if logger_instance is None:
        logger_instance = logger

    all_results: list[dict[str, object]] = []
    total_jobs = len(job_ids)
    successful_jobs = 0

    for job_index, job_id in enumerate(job_ids, start=1):
        try:
            results = batch_client.download_batch_results(job_id)
            all_results.extend(results)
            successful_jobs += 1
        except Exception as exc:
            logger_instance.warning("Failed to download from job %d/%d: %s", job_index, total_jobs, str(exc))

    logger_instance.info("✓ Downloaded %d results from %d job(s)", len(all_results), successful_jobs)
    return all_results


def extract_content_from_batch_result(result: dict, series_uuid: str) -> list | None:
    """Extract and parse JSON content from batch result (expects list)."""
    if error := result.get("error"):
        error_msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        logger.error("[%s] Error in batch result: %s", series_uuid, error_msg)
        return None

    response = result.get("response", {})
    if not response:
        logger.error("[%s] Empty response", series_uuid)
        return None

    body = response.get("body", {})
    choices = body.get("choices", [])
    if not choices:
        logger.error("[%s] No choices in response", series_uuid)
        return None

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        logger.error("[%s] Empty content in response", series_uuid)
        return None

    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            logger.error("[%s] Expected list, got %s", series_uuid, type(parsed).__name__)
            return None
        except json.JSONDecodeError:
            return None
    elif isinstance(content, list):
        return content
    else:
        logger.error("[%s] Unexpected content type: %s", series_uuid, type(content))
        return None


def build_results_map(results: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Build a map of custom_id to result dictionary."""
    results_map: dict[str, dict[str, object]] = {}
    for result in results:
        custom_id = result.get("custom_id")
        if isinstance(custom_id, str):
            results_map[custom_id] = result
    return results_map


def filter_reports_with_results(
    report_files: list[Path],
    report_path_to_custom_id: dict[Path, str],
    results_map: dict[str, dict],
) -> tuple[list[Path], int]:
    """Filter reports that have results in the batch."""
    reports_with_results = []
    reports_without_custom_id = 0

    for report_path in report_files:
        custom_id = report_path_to_custom_id.get(report_path)
        if custom_id is None:
            reports_without_custom_id += 1
            continue

        if custom_id in results_map:
            reports_with_results.append(report_path)

    return reports_with_results, reports_without_custom_id


# ============================================================================
# Batch Metadata Management
# ============================================================================


def get_batch_file_path(output_dir: Path, batch_file_name: str) -> Path:
    """Get batch file path."""
    aux_dir = output_dir / constants.BATCH_AUX_DIR / constants.BATCH_CLIENT_DIR
    aux_dir.mkdir(parents=True, exist_ok=True)
    return aux_dir / batch_file_name


def get_batch_metadata_path(output_dir: Path) -> Path:
    """Get batch metadata file path."""
    return get_batch_file_path(output_dir, constants.BATCH_METADATA_FILE)


def get_model_from_batch_file(output_dir: Path, batch_file_name: str) -> str:
    """Extract model name from batch file."""
    base_path = get_batch_file_path(output_dir, batch_file_name)
    batch_file_path = generate_batch_file_name(base_path, 0)  # First file is _1.jsonl
    if not batch_file_path.exists():
        raise FileNotFoundError(f"Batch file not found: {batch_file_path}")

    try:
        first_line = next(iter(batch_file_path.read_text(encoding="utf-8").splitlines()), "")
        if not first_line.strip():
            raise ValueError(f"Batch file {batch_file_path} is empty")
        batch_request = json.loads(first_line)
        model = batch_request.get("body", {}).get("model")
        if not model:
            raise ValueError(f"Model name not found in batch file {batch_file_path}")
        return model
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse batch file {batch_file_path}: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Failed to extract model from batch file {batch_file_path}: {exc}") from exc


def save_batch_metadata(
    output_dir: Path,
    job_to_custom_ids: dict[str, list[str]],
    series_uuid_map: dict[str, Path],
) -> None:
    """Save batch metadata."""
    metadata_path = get_batch_metadata_path(output_dir)
    metadata = {
        "jobs": [{"job_id": job_id, "custom_ids": custom_ids} for job_id, custom_ids in job_to_custom_ids.items()],
        "series_uuid_map": {custom_id: str(path) for custom_id, path in series_uuid_map.items()},
    }
    io.save_json(metadata, metadata_path)
    logger.info("Saved batch metadata to: %s", metadata_path)


def load_batch_metadata(
    output_dir: Path,
    job_id: str | None = None,
    include_report_files: bool = False,
) -> tuple[list[str], dict[str, Path]] | tuple[list[str], dict[str, Path], list[Path]]:
    """Load batch metadata."""
    metadata_path = get_batch_metadata_path(output_dir)
    if not metadata_path.exists():
        raise FileNotFoundError(f"Batch metadata not found: {metadata_path}")

    metadata = io.load_json(metadata_path, raise_on_error=True)
    jobs = metadata.get("jobs", [])
    series_uuid_map_data = metadata.get("series_uuid_map", {})

    # Filter by job_id if provided
    if job_id:
        jobs = [job for job in jobs if job.get("job_id") == job_id]
        if not jobs:
            raise ValueError(f"Job ID '{job_id}' not found in batch metadata")

    job_ids = [job["job_id"] for job in jobs]
    series_uuid_map = {custom_id: Path(path) for custom_id, path in series_uuid_map_data.items()}

    if include_report_files:
        report_files = list(series_uuid_map.values())
        return job_ids, series_uuid_map, report_files

    return job_ids, series_uuid_map
