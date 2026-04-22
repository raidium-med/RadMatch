"""Batch inference functions for finding extraction."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from tqdm import tqdm

from radmatch import constants, io
from radmatch.finding_extraction import extract_utils
from radmatch.llm_utils import batch_utils, llm_clients, prompts

logger = logging.getLogger(__name__)


def _submit_batch_for_reports(
    reports_dir: Path,
    output_findings_dir: Path,
    output_dir: Path,
    batch_file_suffix: str,
    metadata_type: str,
    model_name: str,
    fewshot: str | None,
    limit: int | None,
    logger_instance: logging.Logger,
    report_files: list[Path] | None = None,
    reasoning: str = "none",
) -> None:
    """Submit batch jobs for a set of reports.

    Args:
        reports_dir: Directory containing report files
        output_findings_dir: Output directory for findings
        output_dir: Base output directory
        batch_file_suffix: Suffix for batch file (e.g., "gt" or "pred")
        metadata_type: Type for metadata (e.g., "gt" or "pred")
        model_name: LLM model name
        fewshot: Optional name of few-shot example set
        limit: Optional limit on number of reports (used if report_files not provided)
        logger_instance: Logger instance
        report_files: Optional pre-filtered list of report files to process
    """
    if report_files is None:
        try:
            report_files, examples_list = extract_utils.setup_processing_context(reports_dir, fewshot, limit)
        except (FileNotFoundError, ValueError) as exc:
            logger_instance.error(str(exc))
            sys.exit(1)
    else:
        # Load examples separately when report_files are provided
        examples_list = prompts.load_fewshot(fewshot) if fewshot else []

    reports_to_process, _ = io.filter_files_needing_processing(
        report_files, output_findings_dir, ".json", logger_instance
    )
    if not reports_to_process:
        logger_instance.warning(f"No {metadata_type} reports to process")
        return

    batch_file_path = batch_utils.get_batch_file_path(output_dir, f"batch_requests_{batch_file_suffix}.jsonl")

    def build_messages(report_path: Path, report_text: str) -> list[dict[str, object]]:  # noqa: ARG001
        """Build messages for finding extraction batch request."""
        return prompts.build_report_processing_messages(report_text, examples_list)

    batch_files_data = batch_utils.create_batch_files_from_reports(
        reports_to_process,
        batch_file_path,
        model_name,
        constants.MAX_TOKENS,
        build_messages,
        logger_instance,
        reasoning=reasoning,
    )

    batch_client = llm_clients.build_batch_client(model=model_name, max_tokens=constants.MAX_TOKENS)
    job_ids, series_uuid_map, job_to_custom_ids = batch_utils.upload_and_create_batch_jobs(
        batch_client, batch_files_data, logger_instance
    )

    metadata = {
        "jobs": [{"job_id": job_id, "custom_ids": custom_ids} for job_id, custom_ids in job_to_custom_ids.items()],
        "series_uuid_map": {custom_id: str(path) for custom_id, path in series_uuid_map.items()},
        "type": metadata_type,
    }
    metadata_path = batch_utils.get_batch_metadata_path(output_dir).parent / f"batch_metadata_{batch_file_suffix}.json"
    io.save_json(metadata, metadata_path)
    logger_instance.info(f"✓ Submitted {len(job_ids)} batch job(s) for {metadata_type} reports")


def _retrieve_batch_for_reports(
    metadata_path: Path,
    findings_dir: Path,
    output_dir: Path,
    batch_file_suffix: str,
    failed_reports: list[dict[str, object]],
    job_id: str | None,
    logger_instance: logging.Logger,
) -> None:
    """Retrieve and process batch results for a set of reports.

    Args:
        metadata_path: Path to batch metadata file
        findings_dir: Directory for findings output
        output_dir: Base output directory
        batch_file_suffix: Suffix for batch file (e.g., "gt" or "pred")
        failed_reports: List to append failed reports to
        job_id: Optional specific job ID to retrieve
        logger_instance: Logger instance
    """
    if not metadata_path.exists():
        logger_instance.warning(f"No batch metadata found for {batch_file_suffix} reports")
        return

    metadata = io.load_json(metadata_path, raise_on_error=True)
    jobs = metadata.get("jobs", [])
    if job_id:
        jobs = [job for job in jobs if job.get("job_id") == job_id]
    job_ids = [job["job_id"] for job in jobs]
    series_uuid_map = {custom_id: Path(path) for custom_id, path in metadata.get("series_uuid_map", {}).items()}
    report_files = list(series_uuid_map.values())

    if not job_ids:
        return

    logger_instance.info(f"Processing {batch_file_suffix} batch results...")
    try:
        model_name = batch_utils.get_model_from_batch_file(output_dir, f"batch_requests_{batch_file_suffix}.jsonl")
    except (FileNotFoundError, ValueError) as exc:
        logger_instance.error(str(exc))
        sys.exit(1)

    batch_client = llm_clients.build_batch_client(model=model_name, max_tokens=constants.MAX_TOKENS)
    statuses = batch_utils.check_batch_job_statuses(batch_client, job_ids, logger_instance, require_complete=False)

    completed_job_ids = [jid for jid, s in zip(job_ids, statuses) if s in batch_utils.COMPLETED_STATUSES]
    if completed_job_ids:
        all_results = batch_utils.download_batch_results_from_jobs(batch_client, completed_job_ids, logger_instance)
        reports_to_process, _ = io.filter_files_needing_processing(report_files, findings_dir, ".json", logger_instance)

        processed, failed, missing, total_findings = process_batch_results(
            all_results, series_uuid_map, reports_to_process, findings_dir, failed_reports
        )

        logger_instance.info(
            f"{batch_file_suffix.capitalize()}: processed={processed}, failed={failed}, "
            f"missing={missing}, findings={total_findings}"
        )


def _check_batch_status_for_reports(
    metadata_path: Path, output_dir: Path, batch_file_suffix: str, job_id: str | None, logger_instance: logging.Logger
) -> None:
    """Check batch job status for a set of reports.

    Args:
        metadata_path: Path to batch metadata file
        output_dir: Base output directory
        batch_file_suffix: Suffix for batch file (e.g., "gt" or "pred")
        job_id: Optional specific job ID to check
        logger_instance: Logger instance
    """
    if not metadata_path.exists():
        return

    metadata = io.load_json(metadata_path, raise_on_error=True)
    jobs = metadata.get("jobs", [])
    if job_id:
        jobs = [job for job in jobs if job.get("job_id") == job_id]
    job_ids = [job["job_id"] for job in jobs]

    if not job_ids:
        return

    logger_instance.info(f"{batch_file_suffix.capitalize()} batch jobs:")
    try:
        model_name = batch_utils.get_model_from_batch_file(output_dir, f"batch_requests_{batch_file_suffix}.jsonl")
        batch_client = llm_clients.build_batch_client(model=model_name, max_tokens=constants.MAX_TOKENS)
        statuses = batch_utils.check_batch_job_statuses(batch_client, job_ids, logger_instance, require_complete=False)
        for jid, status in zip(job_ids, statuses):
            logger_instance.info("  Job %s: %s", jid, status)
    except Exception as exc:
        logger_instance.error(f"Failed to check {batch_file_suffix} batch status: {exc}")


def process_batch_results(
    results: list[dict[str, object]],
    series_uuid_map: dict[str, Path],
    report_files: list[Path],
    findings_dir: Path,
    failed_reports: list[dict[str, object]],
) -> tuple[int, int, int, int]:
    """Process batch results and write output files."""
    processed_reports = 0
    failed_reports_count = 0
    missing_reports_count = 0
    total_findings = 0

    results_map = batch_utils.build_results_map(results)
    report_path_to_custom_id = {path: custom_id for custom_id, path in series_uuid_map.items()}

    reports_with_results, reports_without_custom_id = batch_utils.filter_reports_with_results(
        report_files, report_path_to_custom_id, results_map
    )

    if reports_without_custom_id > 0:
        for report_path in report_files:
            if report_path not in reports_with_results:
                custom_id = report_path_to_custom_id.get(report_path)
                if custom_id is None:
                    series_uuid = report_path.stem
                    failed_reports.append({"series_uuid": series_uuid, "reason": "Could not find custom_id"})
                    failed_reports_count += 1

    missing_reports_count = len(report_files) - len(reports_with_results) - reports_without_custom_id

    for report_path in tqdm(
        reports_with_results, desc="Processing batch results", total=len(reports_with_results), unit="report"
    ):
        series_uuid = report_path.stem
        custom_id = report_path_to_custom_id[report_path]
        result = results_map[custom_id]

        result_data = batch_utils.extract_content_from_batch_result(result, series_uuid)
        if result_data is None:
            failed_reports.append({"series_uuid": series_uuid, "reason": "Failed to extract content from batch result"})
            failed_reports_count += 1
            continue

        try:
            if not isinstance(result_data, list):
                failed_reports.append({"series_uuid": series_uuid, "reason": "LLM response is not a list"})
                failed_reports_count += 1
                continue
            findings_list = extract_utils.extract_findings_list(result_data, series_uuid)
            extract_utils.write_findings_output(series_uuid, findings_list, findings_dir)
            processed_reports += 1
            total_findings += len(findings_list)
        except Exception as exc:
            logger.error("Error processing %s: %s", report_path.name, exc)
            failed_reports.append({"series_uuid": series_uuid, "reason": f"Processing error: {exc}"})
            failed_reports_count += 1

    return processed_reports, failed_reports_count, missing_reports_count, total_findings


def extract_findings_batch_submit(
    reports_gt_dir: Path | None,
    reports_pred_dir: Path,
    output_dir: Path,
    model_name: str,
    fewshot: str | None = None,
    limit: int | None = None,
    findings_gt_dir: Path | None = None,
    reasoning: str = "none",
) -> None:
    """Submit batch jobs for finding extraction."""
    # Validate: either reports_gt_dir or findings_gt_dir must be provided
    if not reports_gt_dir and not findings_gt_dir:
        raise ValueError("Either reports_gt_dir or findings_gt_dir must be provided")

    result_dir = output_dir / constants.RESULTS_DIR

    logger.info("")
    logger.info("=" * 90)
    logger.info("FINDING EXTRACTION - BATCH SUBMIT (1/2)")
    logger.info("-" * 90)
    logger.info("Configuration:")
    logger.info("  • model:         %s", model_name)
    if reports_gt_dir:
        logger.info("  • reports_gt:    %s", reports_gt_dir)
    if findings_gt_dir:
        logger.info("  • findings_gt:   %s", findings_gt_dir)
    logger.info("  • reports_pred:  %s", reports_pred_dir)
    logger.info("  • output:        %s", result_dir)
    logger.info("  • fewshot:       %s", fewshot or "None")
    logger.info("  • limit:         %s", limit or "None")
    logger.info("=" * 90)
    logger.info("")

    output_findings_gt_dir, output_findings_pred_dir = extract_utils.create_output_directories(result_dir)

    # Get series_uuid list from predicted reports to align GT processing
    report_files_pred, _ = extract_utils.setup_processing_context(reports_pred_dir, fewshot, limit)
    series_uuid_list = [f.stem for f in report_files_pred]

    # Handle ground truth: either adapt existing findings or process reports
    if findings_gt_dir:
        findings_gt_path = findings_gt_dir if isinstance(findings_gt_dir, Path) else Path(findings_gt_dir)
        logger.info("")
        logger.info("-" * 90)
        logger.info("(1) Adapting existing ground truth findings...")
        extract_utils.copy_findings_from_directory(findings_gt_path, output_findings_gt_dir, logger, series_uuid_list)

    elif reports_gt_dir:
        # Filter GT reports to match the predicted reports that will be processed
        all_report_files_gt = io.find_report_files(reports_gt_dir)
        if not all_report_files_gt:
            raise ValueError(f"No .txt reports found in {reports_gt_dir}")

        if series_uuid_list:
            # Create a set for fast lookup
            series_uuid_set = set(series_uuid_list)
            report_files_gt = [f for f in all_report_files_gt if f.stem in series_uuid_set]
        else:
            report_files_gt = all_report_files_gt

        if not report_files_gt:
            logger.warning("No matching ground truth reports found for the predicted reports")
        else:
            logger.info("")
            logger.info("-" * 90)
            logger.info("(1) Processing ground truth reports...")
            logger.info("Processing %d ground truth reports (aligned with predicted reports)", len(report_files_gt))
            _submit_batch_for_reports(
                reports_gt_dir,
                output_findings_gt_dir,
                result_dir,
                "gt",
                "gt",
                model_name,
                fewshot,
                None,  # limit not needed since we're passing filtered report_files
                logger,
                report_files=report_files_gt,
                reasoning=reasoning,
            )

    # Copy ground truth reports
    if reports_gt_dir and reports_gt_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_gt_dir, result_dir / "reports_gt", logger, series_uuid_list)

    # Process predicted reports
    logger.info("")
    logger.info("-" * 90)
    logger.info("(2) Processing predicted reports...")
    _submit_batch_for_reports(
        reports_pred_dir,
        output_findings_pred_dir,
        result_dir,
        "pred",
        "pred",
        model_name,
        fewshot,
        limit,
        logger,
        reasoning=reasoning,
    )

    # Copy predicted reports
    if reports_pred_dir and reports_pred_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_pred_dir, result_dir / "reports_pred", logger, series_uuid_list)

    logger.info("")
    logger.info("Next step: Retrieve results with:")
    logger.info("  cli.py extract_findings infer_batch retrieve --output-dir %s", output_dir)
    logger.info("")


def extract_findings_batch_retrieve(
    output_dir: Path,
    job_id: str | None = None,
) -> None:
    """Retrieve and process batch results."""
    result_dir = output_dir / constants.RESULTS_DIR
    logger.info("")
    logger.info("=" * 90)
    logger.info("FINDING EXTRACTION - BATCH RETRIEVE (2/2)")
    logger.info("-" * 90)
    logger.info("Retrieving and processing batch results")
    logger.info("=" * 90)
    logger.info("")

    findings_gt_dir, findings_pred_dir = extract_utils.create_output_directories(result_dir)

    failed_reports: list[dict[str, object]] = []

    # Process ground truth
    metadata_path_gt = batch_utils.get_batch_metadata_path(result_dir).parent / "batch_metadata_gt.json"
    _retrieve_batch_for_reports(metadata_path_gt, findings_gt_dir, result_dir, "gt", failed_reports, job_id, logger)

    # Process predicted
    logger.info("")
    metadata_path_pred = batch_utils.get_batch_metadata_path(result_dir).parent / "batch_metadata_pred.json"
    _retrieve_batch_for_reports(
        metadata_path_pred, findings_pred_dir, result_dir, "pred", failed_reports, job_id, logger
    )

    if failed_reports:
        failed_path = result_dir / constants.FAILED_REPORTS_FILE
        io.save_json(failed_reports, failed_path)
        logger.info("Saved %d failed reports to: %s", len(failed_reports), failed_path)

    logger.info("")
    logger.info("Batch retrieval complete!")
    logger.info("")


def extract_findings_batch_status(
    output_dir: Path,
    job_id: str | None = None,
) -> None:
    """Check batch job status."""
    result_dir = output_dir / constants.RESULTS_DIR
    logger.info("")
    logger.info("=" * 90)
    logger.info("BATCH JOB STATUS")
    logger.info("-" * 90)

    # Check ground truth
    metadata_path_gt = batch_utils.get_batch_metadata_path(result_dir).parent / "batch_metadata_gt.json"
    _check_batch_status_for_reports(metadata_path_gt, result_dir, "gt", job_id, logger)

    # Check predicted
    metadata_path_pred = batch_utils.get_batch_metadata_path(result_dir).parent / "batch_metadata_pred.json"
    _check_batch_status_for_reports(metadata_path_pred, result_dir, "pred", job_id, logger)

    logger.info("=" * 90)
    logger.info("")
