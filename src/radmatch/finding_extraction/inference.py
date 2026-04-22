"""Core extraction logic for finding extraction."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
from pathlib import Path

from tqdm import tqdm

from radmatch import constants, io
from radmatch.finding_extraction import extract_utils
from radmatch.llm_utils import llm_clients, prompts

logger = logging.getLogger(__name__)


class FindingExtractor:
    """Extract findings from radiology reports using an LLM."""

    def __init__(
        self,
        model_name: str,
        examples: list[dict[str, object]],
        workers: int,
        max_tokens: int,
        reasoning: str = "none",
    ):
        """Initialize the finding extractor."""
        self.model_name = model_name
        self.examples = examples
        self.workers = workers
        self.max_tokens = max_tokens
        self.client = llm_clients.build_single_client(
            model=self.model_name, max_tokens=self.max_tokens, reasoning=reasoning
        )
        self._failed_lock = threading.Lock()
        self._failed_reports: list[dict[str, object]] = []
        logger.info(f"Initialized with model: {model_name}")

    def _extract_findings(
        self, series_uuid: str, report_text: str
    ) -> tuple[list[dict[str, object]] | None, str | None, str | None]:
        """Extract findings from report text using LLM with automatic retry.

        Returns:
            Tuple of (findings_list, failure_reason, raw_response)
        """
        messages = prompts.build_report_processing_messages(report_text, self.examples)

        def _call_api() -> str:
            content = self.client.complete(messages=messages, response_format=None)
            if not content:
                raise ValueError("Empty API response")
            return content

        content, failure_reason = llm_clients.call_with_llm_retry(
            _call_api,
            series_uuid=series_uuid,
            logger_instance=logger,
        )

        if content is None:
            return None, failure_reason, None

        try:
            result = json.loads(content)
            if not isinstance(result, list):
                return None, "LLM response is not a list", content
            return result, None, content
        except json.JSONDecodeError:
            return None, "JSON parsing failed for API response", content

    def run(self, report_files: list[Path], findings_dir: Path) -> tuple[int, int, int, int, int]:
        """Extract findings from all reports using concurrent workers.

        Returns:
            Tuple of (total_reports, processed_reports, skipped_reports, failed_reports, total_findings)
        """
        total_reports = len(report_files)

        # Filter reports that need processing (skip those with existing results)
        reports_to_process, skipped_reports = io.filter_files_needing_processing(
            report_files, findings_dir, ".json", logger
        )

        if not reports_to_process:
            return (total_reports, 0, skipped_reports, 0, 0)

        # Adapt workers to actual number of files to process
        actual_workers = min(self.workers, len(reports_to_process))
        logger.info(
            "Processing %d/%d reports with %d worker(s)",
            len(reports_to_process),
            total_reports,
            actual_workers,
        )

        with self._failed_lock:
            self._failed_reports = []

        processed_reports = 0
        failed_reports = 0
        total_findings = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {
                executor.submit(
                    self._process_one_report,
                    report_path,
                    findings_dir,
                ): report_path
                for report_path in reports_to_process
            }

            for future in tqdm(
                concurrent.futures.as_completed(futures),
                total=len(reports_to_process),
                desc="Processing",
                unit="report",
            ):
                report_path = futures[future]
                try:
                    status, series_uuid, findings_list = future.result()
                except (OSError, ValueError, RuntimeError, KeyError) as exc:
                    self._record_failure(report_path.stem, f"Unexpected error: {exc}")
                    logger.error("Error processing %s: %s", report_path.name, exc)
                    failed_reports += 1
                    continue

                if status == "failed":
                    failed_reports += 1
                    continue

                if status == "success" and findings_list is not None:
                    extract_utils.write_findings_output(series_uuid, findings_list, findings_dir)
                    processed_reports += 1
                    total_findings += len(findings_list)

        # Save failed reports
        with self._failed_lock:
            failed_entries = list(self._failed_reports)

        if failed_entries:
            failed_path = findings_dir.parent / constants.FAILED_REPORTS_FILE
            io.save_json(failed_entries, failed_path)
            logger.info("Saved %d failed reports to: %s", len(failed_entries), failed_path)

        return (total_reports, processed_reports, skipped_reports, failed_reports, total_findings)

    def _process_one_report(
        self,
        report_path: Path,
        findings_dir: Path,
    ) -> tuple[str, str, list[dict[str, object]] | None]:
        """Process a single report file and return findings."""
        series_uuid = report_path.stem

        report_text = io.read_text_file(report_path, logger)
        if not report_text:
            error_msg = "Failed to read report or report is empty"
            self._record_failure(series_uuid, error_msg)
            return ("failed", series_uuid, None)

        findings_raw, failure_reason, raw_response = self._extract_findings(series_uuid, report_text)
        if findings_raw is None:
            reason = failure_reason or "Unknown processing error"
            logger.error("Failed %s: %s", series_uuid, reason)
            self._record_failure(series_uuid, reason, raw_response)
            return ("failed", series_uuid, None)

        findings_list = extract_utils.extract_findings_list(findings_raw, series_uuid)

        return ("success", series_uuid, findings_list)

    def _record_failure(self, series_uuid: str, reason: str, raw_response: str | None = None) -> None:
        """Record a failed report (for in-memory tracking)."""
        entry: dict[str, str | None] = {
            "series_uuid": series_uuid,
            "reason": reason,
        }
        if raw_response is not None:
            entry["raw_response"] = raw_response
        with self._failed_lock:
            self._failed_reports.append(entry)


def extract_findings(
    reports_gt_dir: Path | None,
    reports_pred_dir: Path,
    output_dir: Path,
    model_name: str,
    fewshot: str | None = None,
    workers: int = 5,
    limit: int | None = None,
    findings_gt_dir: Path | None = None,
    reasoning: str = "none",
) -> None:
    """Extract findings from ground truth and predicted reports.

    Args:
        reports_gt_dir: Directory containing ground truth report .txt files (optional if findings_gt_dir provided)
        reports_pred_dir: Directory containing predicted report .txt files
        output_dir: Output directory
        model_name: LLM model name
        fewshot: Optional name of few-shot example set to load
        workers: Number of concurrent workers
        limit: Optional limit on number of reports to process
        findings_gt_dir: Optional path to existing ground truth findings to adapt (alternative to reports_gt_dir)
    """
    # Validate: either reports_gt_dir or findings_gt_dir must be provided
    if not reports_gt_dir and not findings_gt_dir:
        raise ValueError("Either reports_gt_dir or findings_gt_dir must be provided")

    logger.info("")
    logger.info("=" * 90)
    logger.info("FINDING EXTRACTION")
    logger.info("-" * 90)
    logger.info("Configuration:")
    logger.info("  • model:         %s", model_name)
    if reports_gt_dir:
        logger.info("  • reports_gt:    %s", reports_gt_dir)
    if findings_gt_dir:
        logger.info("  • findings_gt:   %s", findings_gt_dir)
    logger.info("  • reports_pred:  %s", reports_pred_dir)
    result_dir = output_dir / constants.RESULTS_DIR
    logger.info("  • output:        %s", result_dir)
    logger.info("  • fewshot:       %s", fewshot or "None")
    logger.info("  • workers:       %d", workers)
    logger.info("  • limit:         %s", limit or "None")
    logger.info("=" * 90)
    logger.info("")

    # Create output directories
    output_findings_gt_dir, output_findings_pred_dir = extract_utils.create_output_directories(result_dir)

    # Get series_uuid list from predicted reports to align GT processing
    report_files_pred, examples_list = extract_utils.setup_processing_context(reports_pred_dir, fewshot, limit)
    series_uuid_list = [f.stem for f in report_files_pred]

    # Handle ground truth: either adapt existing findings or process reports
    stats_gt: tuple[int, int, int, int, int] | None = None
    if findings_gt_dir:
        findings_gt_path = findings_gt_dir if isinstance(findings_gt_dir, Path) else Path(findings_gt_dir)
        logger.info("")
        logger.info("-" * 90)
        logger.info("(1) Adapting existing ground truth findings...")
        copied_count = extract_utils.copy_findings_from_directory(
            findings_gt_path, output_findings_gt_dir, logger, series_uuid_list
        )
        # For adapted findings, count total findings files and findings
        total_gt_files = len([f for f in output_findings_gt_dir.glob("*.json")])
        total_gt_findings = 0
        for findings_file in output_findings_gt_dir.glob("*.json"):
            try:
                findings_list = io.load_json(findings_file, raise_on_error=False)
                if isinstance(findings_list, list):
                    total_gt_findings += len(findings_list)
            except (OSError, ValueError, KeyError):
                pass
        stats_gt = (total_gt_files, copied_count, total_gt_files - copied_count, 0, total_gt_findings)
    elif reports_gt_dir:
        # Filter GT reports to match the predicted reports that will be processed
        all_report_files_gt = io.find_report_files(reports_gt_dir)
        if not all_report_files_gt:
            raise ValueError(f"No .txt reports found in {reports_gt_dir}")

        # Create a set for fast lookup
        series_uuid_set = set(series_uuid_list)
        report_files_gt = [f for f in all_report_files_gt if f.stem in series_uuid_set]

        if not report_files_gt:
            logger.warning("No matching ground truth reports found for the predicted reports")
        else:
            logger.info("")
            logger.info("-" * 90)
            logger.info("(1) Processing ground truth reports...")
            extractor_gt = FindingExtractor(
                model_name=model_name,
                examples=examples_list,
                workers=workers,
                max_tokens=constants.MAX_TOKENS,
                reasoning=reasoning,
            )
            stats_gt = extractor_gt.run(report_files_gt, output_findings_gt_dir)

    # Copy ground truth reports
    if reports_gt_dir and reports_gt_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_gt_dir, result_dir / "reports_gt", logger, series_uuid_list)

    # Process predicted reports
    logger.info("")
    logger.info("-" * 90)
    logger.info("(2) Processing predicted reports...")
    extractor_pred = FindingExtractor(
        model_name=model_name,
        examples=examples_list,
        workers=workers,
        max_tokens=constants.MAX_TOKENS,
        reasoning=reasoning,
    )
    stats_pred = extractor_pred.run(report_files_pred, output_findings_pred_dir)

    # Copy predicted reports
    if reports_pred_dir and reports_pred_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_pred_dir, result_dir / "reports_pred", logger, series_uuid_list)

    # Display combined statistics
    logger.info("")
    logger.info("-" * 90)
    logger.info("EXTRACTION SUMMARY")

    if stats_pred:
        total_pred, processed_pred, skipped_pred, failed_pred, findings_pred = stats_pred
        avg_pred = findings_pred / processed_pred if processed_pred > 0 else 0
        logger.info("PREDICTED REPORTS:")
        logger.info("  Total reports:     %6d", total_pred)
        logger.info("    • processed:     %6d", processed_pred)
        logger.info("    • skipped:       %6d", skipped_pred)
        logger.info("    • failed:        %6d", failed_pred)
        logger.info("  Total findings:    %6d", findings_pred)
        logger.info("  Avg findings/report: %.1f", avg_pred)
        logger.info("")

    if stats_gt:
        total_gt, processed_gt, skipped_gt, failed_gt, findings_gt = stats_gt
        avg_gt = findings_gt / processed_gt if processed_gt > 0 else 0
        logger.info("GROUND TRUTH REPORTS:")
        logger.info("  Total reports:     %6d", total_gt)
        logger.info("    • processed:     %6d", processed_gt)
        logger.info("    • skipped:       %6d", skipped_gt)
        logger.info("    • failed:        %6d", failed_gt)
        logger.info("  Total findings:    %6d", findings_gt)
        logger.info("  Avg findings/report: %.1f", avg_gt)

    logger.info("=" * 90)
