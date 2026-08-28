"""Stage 1 — extract findings from radiology reports using an LLM."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from radmatch import constants, io
from radmatch.finding_extraction import extract_utils
from radmatch.llm_utils import llm_clients, prompts

logger = logging.getLogger(__name__)


# Deliberately soft on enum values (open `string` for clinical_*, comparison,
# measurement.category) — `extract_utils.validate_and_normalize_finding` normalizes
# them downstream, as Stage 3b does after its own soft schema.
_FINDINGS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "findings_output",
        "schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "clinical_status": {"type": "string"},
                            "clinical_significance": {"type": "string"},
                            "comparison": {"type": ["string", "null"]},
                            "measurements": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "number"},
                                        "unit": {"type": ["string", "null"]},
                                        "category": {"type": "string"},
                                    },
                                    "required": ["value", "unit", "category"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "text",
                            "clinical_status",
                            "clinical_significance",
                            "comparison",
                            "measurements",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["findings"],
            "additionalProperties": False,
        },
    },
}


# ============================================================================
# Per-stage data shapes
# ============================================================================


@dataclass
class ExtractionStats:
    """Counts returned by `run_extraction` for one side (GT or pred).

    `findings` is the total number of findings across all processed reports.
    """

    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    findings: int = 0

    @property
    def avg_findings_per_report(self) -> float:
        return self.findings / self.processed if self.processed else 0.0


@dataclass
class _FailedReport:
    series_uuid: str
    reason: str
    raw_response: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {"series_uuid": self.series_uuid, "reason": self.reason}
        if self.raw_response is not None:
            out["raw_response"] = self.raw_response
        return out


@dataclass
class _ExtractionResult:
    series_uuid: str
    findings: list[dict[str, object]] | None
    failure: _FailedReport | None = None


# ============================================================================
# Per-report extraction
# ============================================================================


def _extract_one_report(
    report_path: Path,
    client: llm_clients.Client,
    fewshot_messages: tuple[dict, ...],
    indication: str = "",
) -> _ExtractionResult:
    """Extract findings for a single report; returns either findings or a failure record."""
    series_uuid = report_path.stem
    report_text = io.read_text_file(report_path)
    if not report_text:
        return _ExtractionResult(
            series_uuid, None, _FailedReport(series_uuid, "Failed to read report or report is empty")
        )

    messages = prompts.build_messages(
        prompts.load_prompt(prompts.PROMPT_FINDING_EXTRACTION),
        report_text,
        fewshot_messages,
        indication=indication or None,
    )
    try:
        content = llm_clients.call_llm(client, messages, response_format=_FINDINGS_SCHEMA)
    except Exception as exc:  # noqa: BLE001 — LLM clients can raise anything provider-specific
        logger.error("[Report %s] LLM call failed: %s", series_uuid, exc)
        return _ExtractionResult(series_uuid, None, _FailedReport(series_uuid, f"LLM call failed: {exc}"))

    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return _ExtractionResult(
            series_uuid, None, _FailedReport(series_uuid, "JSON parsing failed for API response", content)
        )
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        return _ExtractionResult(
            series_uuid, None, _FailedReport(series_uuid, 'LLM response missing "findings" array', content)
        )

    findings = extract_utils.extract_findings_list(raw["findings"], series_uuid)
    return _ExtractionResult(series_uuid, findings)


# ============================================================================
# Dataset-level extraction
# ============================================================================


def run_extraction(
    report_files: list[Path],
    findings_dir: Path,
    client: llm_clients.Client,
    fewshot_messages: tuple[dict, ...],
    workers: int,
    indications: dict[str, str] | None = None,
) -> ExtractionStats:
    """Extract findings into `findings_dir/<series>.json`, skipping reports that already
    have output. Failures accumulate into `failed_reports.json`.

    `fewshot_messages` is pre-serialized once by `prompts.extraction_fewshot_messages`
    and passed to every worker as-is.
    """
    total = len(report_files)
    to_process, skipped = io.filter_files_needing_processing(report_files, findings_dir, ".json")
    stats = ExtractionStats(total=total, skipped=skipped)
    if not to_process:
        return stats

    logger.info("Processing %d/%d reports with %d worker(s)", len(to_process), total, min(workers, len(to_process)))

    indications = indications or {}
    failures: list[_FailedReport] = []
    for result in io.process_pairs_in_parallel(
        to_process,
        lambda path: _extract_one_report(path, client, fewshot_messages, indications.get(path.stem, "")),
        workers=workers,
        desc="Processing",
        unit="report",
    ):
        if result.failure is not None:
            failures.append(result.failure)
            stats.failed += 1
            logger.error("Failed %s: %s", result.series_uuid, result.failure.reason)
            continue
        if result.findings is None:
            stats.failed += 1
            continue
        io.save_json(result.findings, findings_dir / f"{result.series_uuid}.json")
        stats.processed += 1
        stats.findings += len(result.findings)

    if failures:
        failed_path = findings_dir.parent / constants.FAILED_REPORTS_FILE
        io.save_json([f.as_dict() for f in failures], failed_path)
        logger.info("Saved %d failed reports to: %s", len(failures), failed_path)

    return stats


# ============================================================================
# Top-level orchestrator
# ============================================================================


def _prepare_predicted_reports(
    reports_pred_dir: Path,
    limit: int | None,
) -> list[Path]:
    """Discover predicted reports and apply `limit` if any. Fails fast on empty input."""
    if not reports_pred_dir.exists():
        raise FileNotFoundError(f"Reports directory not found: {reports_pred_dir}")
    report_files = sorted(reports_pred_dir.glob("*.txt"))
    if not report_files:
        raise ValueError(f"No .txt reports found in {reports_pred_dir}")
    if limit is not None:
        report_files = report_files[:limit]
        logger.info("Limited processing to first %d reports", len(report_files))
    return report_files


def _adapt_gt_findings(findings_gt_dir: Path, output_dir: Path, series_uuids: list[str]) -> ExtractionStats:
    """Copy + filter existing GT findings into `output_dir`. Returns the resulting stats."""
    logger.info("")
    logger.info("-" * 90)
    logger.info("(1) Adapting existing ground truth findings...")
    copied = extract_utils.copy_findings_from_directory(findings_gt_dir, output_dir, series_uuids)
    total_files = sum(1 for _ in output_dir.glob("*.json"))
    total_findings = 0
    for findings_file in output_dir.glob("*.json"):
        loaded = io.load_json(findings_file, raise_on_error=False)
        if isinstance(loaded, list):
            total_findings += len(loaded)
    return ExtractionStats(
        total=total_files,
        processed=copied,
        skipped=total_files - copied,
        failed=0,
        findings=total_findings,
    )


def _extract_gt_findings(
    reports_gt_dir: Path,
    output_dir: Path,
    series_uuids: list[str],
    client: llm_clients.Client,
    fewshot_messages: tuple[dict, ...],
    workers: int,
    indications: dict[str, str] | None = None,
) -> ExtractionStats | None:
    """Extract GT findings from raw reports. Returns None if no GT reports match the pred series."""
    all_gt = sorted(reports_gt_dir.glob("*.txt"))
    if not all_gt:
        raise ValueError(f"No .txt reports found in {reports_gt_dir}")
    series_set = set(series_uuids)
    report_files = [f for f in all_gt if f.stem in series_set]
    if not report_files:
        logger.warning("No matching ground truth reports found for the predicted reports")
        return None
    logger.info("")
    logger.info("-" * 90)
    logger.info("(1) Processing ground truth reports...")
    return run_extraction(report_files, output_dir, client, fewshot_messages, workers, indications)


def _side_summary_lines(label: str, stats: ExtractionStats | None) -> list[str]:
    """Format one side of the EXTRACTION SUMMARY block (returns no lines if stats is None)."""
    if stats is None:
        return []
    return [
        f"{label}:",
        f"  Total reports:     {stats.total:6d}",
        f"    • processed:     {stats.processed:6d}",
        f"    • skipped:       {stats.skipped:6d}",
        f"    • failed:        {stats.failed:6d}",
        f"  Total findings:    {stats.findings:6d}",
        f"  Avg findings/report: {stats.avg_findings_per_report:.1f}",
        "",
    ]


def extract_findings(
    reports_gt_dir: Path | None,
    reports_pred_dir: Path,
    output_dir: Path,
    llm_extractor: str,
    fewshot: str | None = None,
    workers: int = 15,
    limit: int | None = None,
    findings_gt_dir: Path | None = None,
    reasoning: str = "none",
    client_factory=None,
    indications_dir: Path | None = None,
) -> None:
    """Extract findings from ground-truth and predicted reports into
    `output_dir/radmatch_results/findings_{gt,pred}/`.

    Exactly one of `reports_gt_dir` (raw text) or `findings_gt_dir` (already
    extracted) is required; predicted reports are always extracted.
    `indications_dir` is injected as context and copied into the results directory so
    later stages find it without the flag.
    `client_factory(model, max_tokens, reasoning) -> Client` overrides construction
    for testing.
    """
    if not reports_gt_dir and not findings_gt_dir:
        raise ValueError("Either reports_gt_dir or findings_gt_dir must be provided")

    result_dir = output_dir / constants.RESULTS_DIR
    config = [
        ("model", llm_extractor),
        ("reports_gt", reports_gt_dir),
        ("findings_gt", findings_gt_dir),
        ("reports_pred", reports_pred_dir),
        ("output", result_dir),
        ("fewshot", fewshot),
        ("workers", workers),
        ("limit", limit),
        ("indications", indications_dir),
    ]
    io.log_stage_banner(
        "FINDING EXTRACTION",
        [(label, value) for label, value in config if value is not None or label in {"fewshot", "limit"}],
    )

    if client_factory is None:
        llm_clients.assert_credentials_for(llm_extractor)
        client_factory = llm_clients.build_client

    output_gt_dir, output_pred_dir = extract_utils.create_output_directories(result_dir)
    report_files_pred = _prepare_predicted_reports(reports_pred_dir, limit)
    fewshot_messages = prompts.extraction_fewshot_messages(fewshot)
    if fewshot:
        logger.info("Loaded %d few-shot example(s) for '%s'", len(fewshot_messages) // 2, fewshot)

    series_uuids = [f.stem for f in report_files_pred]
    indications = io.load_indications(indications_dir)
    if indications:
        nonempty = sum(1 for v in indications.values() if v)
        logger.info("Loaded %d indications (%d non-empty) from %s", len(indications), nonempty, indications_dir)
    # One client serves both sides — same model, same provider.
    client = client_factory(model=llm_extractor, max_tokens=constants.MAX_TOKENS, reasoning=reasoning)

    stats_gt: ExtractionStats | None = None
    if findings_gt_dir:
        stats_gt = _adapt_gt_findings(Path(findings_gt_dir), output_gt_dir, series_uuids)
    elif reports_gt_dir:
        stats_gt = _extract_gt_findings(
            reports_gt_dir, output_gt_dir, series_uuids, client, fewshot_messages, workers, indications
        )

    if reports_gt_dir and reports_gt_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_gt_dir, result_dir / constants.REPORTS_GT_DIR, series_uuids)
    if indications_dir:
        # Skip the copy when source == target (e.g. `run_all --extract-indications` wrote
        # straight into the results dir).
        target_indications_dir = result_dir / constants.INDICATIONS_DIR
        if indications_dir.resolve() != target_indications_dir.resolve():
            logger.info("Copying indications to results directory...")
            extract_utils.copy_reports_directory(indications_dir, target_indications_dir, series_uuids)

    logger.info("")
    logger.info("-" * 90)
    logger.info("(2) Processing predicted reports...")
    stats_pred = run_extraction(report_files_pred, output_pred_dir, client, fewshot_messages, workers, indications)

    if reports_pred_dir.exists():
        logger.info("Copying reports to results directory...")
        extract_utils.copy_reports_directory(reports_pred_dir, result_dir / constants.REPORTS_PRED_DIR, series_uuids)

    io.log_stage_summary(
        "EXTRACTION SUMMARY",
        _side_summary_lines("PREDICTED REPORTS", stats_pred) + _side_summary_lines("GROUND TRUTH REPORTS", stats_gt),
    )
