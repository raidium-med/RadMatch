"""Evaluation logic for comparing predicted findings against ground truth."""

from __future__ import annotations

import logging
import time
from pathlib import Path  # noqa: TC003

from tqdm import tqdm

from radmatch import constants, io
from radmatch.evaluation import eval_logging, eval_utils, matching, metrics
from radmatch.llm_utils import llm_clients

logger = logging.getLogger(__name__)


def _detect_failed_findings(matching_dir: Path) -> dict[str, list[str]]:
    """Detect findings with API failures from all matching files.

    Returns:
        Dictionary mapping series_uuid to list of failed finding IDs.
    """
    series_uuid_to_failed_ids: dict[str, list[str]] = {}
    for matching_file in matching_dir.glob("*.json"):
        matching_data = io.load_json(matching_file, raise_on_error=False)
        if not isinstance(matching_data, dict):
            continue
        failed_ids = [finding_id for finding_id, result in matching_data.items() if result.get("api_failed", False)]
        if failed_ids:
            series_uuid_to_failed_ids[matching_file.stem] = failed_ids
    return series_uuid_to_failed_ids


def _save_report_metrics(
    result_dir: Path,
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    series_uuid: str,
    pred_findings_list: list[dict[str, object]],
    gt_findings_list: list[dict[str, object]],
    matching_results: dict[str, dict[str, object]],
    model_name: str,
) -> None:
    """Compute and save per-report metrics."""
    per_report_metrics_dir = result_dir / "per_report_metrics"
    per_report_metrics_dir.mkdir(parents=True, exist_ok=True)

    pred_file = findings_pred_dir / f"{series_uuid}.json"
    gt_file = findings_gt_dir / f"{series_uuid}.json"

    report_metadata = eval_utils.create_metadata(
        findings_gt_dir=findings_gt_dir,
        findings_pred_dir=findings_pred_dir,
        model_name=model_name,
    )
    report_metadata["inputs"] = {
        "findings_gt": str(gt_file.resolve()),
        "findings_pred": str(pred_file.resolve()),
    }

    metrics_by_type = metrics.compute_report_metrics(
        gt_findings_list=gt_findings_list,
        pred_findings_list=pred_findings_list,
        matching_results=matching_results,
    )
    overall = metrics_by_type.get("__overall__", {})
    measurement_type_metrics = metrics_by_type.get(constants.FINDING_TYPE_MEASUREMENT, {})

    report_metrics = {
        "micro_averaged": {
            "f1": round(v, 4) if (v := overall.get("f1")) is not None else None,
            "precision": round(v, 4) if (v := overall.get("precision")) is not None else None,
            "recall": round(v, 4) if (v := overall.get("recall")) is not None else None,
            "gt_count": overall.get("gt_count", 0),
            "pred_count": overall.get("pred_count", 0),
        },
        constants.FINDING_TYPE_ABNORMAL_REGULAR: {
            "micro_averaged": {
                k: v
                for k, v in metrics_by_type.get(constants.FINDING_TYPE_ABNORMAL_REGULAR, {}).items()
                if k not in {"tp", "fp", "fn"}
            },
        },
        constants.FINDING_TYPE_NORMAL_REGULAR: {
            "micro_averaged": {
                k: v
                for k, v in metrics_by_type.get(constants.FINDING_TYPE_NORMAL_REGULAR, {}).items()
                if k not in {"tp", "fp", "fn"}
            },
        },
        "longitudinal": {
            k: v
            for k, v in metrics.compute_report_longitudinal_metrics(
                gt_findings_list=gt_findings_list,
                pred_findings_list=pred_findings_list,
                matching_results=matching_results,
            ).items()
            if k != "per_category"
        },
        "measurement": {
            k: v
            for k, v in metrics.compute_report_measurement_metrics(
                gt_findings_list=gt_findings_list,
                pred_findings_list=pred_findings_list,
                matching_results=matching_results,
                measurement_type_metrics=measurement_type_metrics,
            ).items()
            if k != "per_category"
        },
        "findings_counts": {
            "gt": overall.get("gt_count", 0),
            "pred": overall.get("pred_count", 0),
            "tp": overall.get("tp", 0),
            "fp": overall.get("fp", 0),
            "fn": overall.get("fn", 0),
        },
    }

    output_file = per_report_metrics_dir / f"{series_uuid}.json"
    io.save_json({"metadata": report_metadata, "metrics": report_metrics}, output_file)


def _reprocess_failed_findings(
    result_dir: Path,
    matching_dir: Path,
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    series_uuid_to_failed_ids: dict[str, list[str]],
    model_name: str,
    workers: int,
    fewshot: str | None,
    reasoning: str = "none",
) -> None:
    """Reprocess findings that had API failures."""
    client = llm_clients.build_single_client(model=model_name, max_tokens=constants.MAX_TOKENS, reasoning=reasoning)
    still_failed: dict[str, list[str]] = {}

    for series_uuid, failed_ids_list in tqdm(
        series_uuid_to_failed_ids.items(),
        desc="Retrying failed findings",
        unit="report",
    ):
        pred_file = findings_pred_dir / f"{series_uuid}.json"
        gt_file = findings_gt_dir / f"{series_uuid}.json"
        matching_file = matching_dir / f"{series_uuid}.json"

        if not pred_file.exists() or not gt_file.exists() or not matching_file.exists():
            logger.warning("Missing files for %s, skipping", series_uuid)
            continue

        pred_findings_list = io.load_json(pred_file, raise_on_error=True)
        gt_findings_list = io.load_json(gt_file, raise_on_error=True)

        failed_ids_set = set(failed_ids_list)
        findings_to_retry = [f for f in pred_findings_list if f.get("finding_id") in failed_ids_set]

        if not findings_to_retry:
            logger.warning(
                "No findings found to retry for %s. Failed finding IDs may have been removed from findings file.",
                series_uuid,
            )
            continue

        new_matching_results = matching.match_findings_llm(
            pred_findings_list=findings_to_retry,
            gt_findings_list=gt_findings_list,
            series_uuid=series_uuid,
            client=client,
            workers=workers,
            fewshot=fewshot,
        )

        existing_matching = io.load_json(matching_file, raise_on_error=True)
        for finding_id, result in new_matching_results.items():
            existing_matching[finding_id] = {
                "matched": result.get("matched", False),
                "corresponding_gt_finding_id": result.get("corresponding_gt_finding_id"),
                "confidence": result.get("confidence", "unknown"),
                "reasoning": result.get("reasoning", ""),
                "api_failed": result.get("api_failed", False),
            }

        pred_id_to_finding = {f.get("finding_id", ""): f for f in pred_findings_list}
        matching_ordered = {
            finding_id: existing_matching[finding_id]
            for finding_id in pred_id_to_finding
            if finding_id in existing_matching
        }

        io.save_json(matching_ordered, matching_file)

        still_failed_ids = [
            finding_id for finding_id, result in matching_ordered.items() if result.get("api_failed", False)
        ]
        if still_failed_ids:
            still_failed[series_uuid] = still_failed_ids

        _save_report_metrics(
            result_dir=result_dir,
            findings_gt_dir=findings_gt_dir,
            findings_pred_dir=findings_pred_dir,
            series_uuid=series_uuid,
            pred_findings_list=pred_findings_list,
            gt_findings_list=gt_findings_list,
            matching_results=matching_ordered,
            model_name=model_name,
        )

    failed_file = result_dir / constants.FAILED_FINDINGS_FILE
    if still_failed:
        io.save_json(still_failed, failed_file)
        total_failed = sum(len(ids) for ids in still_failed.values())
        logger.warning(
            "Still have %d findings with API failures across %d reports. Run again to retry.",
            total_failed,
            len(still_failed),
        )
    elif failed_file.exists():
        failed_file.unlink()
        logger.info("All previously failed findings have been successfully processed.")


def _compute_and_save_summary(
    result_dir: Path,
    matching_dir: Path,
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    model_name: str,
    execution_time_seconds: float | None = None,
    all_reports: list[tuple[Path, Path, str]] | None = None,
) -> None:
    """Compute and save aggregated metrics summary."""
    aggregator = metrics.MetricsAggregator()
    num_reports_included = 0

    matching_files_to_process = (
        [matching_dir / f"{series_uuid}.json" for _, _, series_uuid in all_reports]
        if all_reports
        else list(matching_dir.glob("*.json"))
    )

    for matching_file in matching_files_to_process:
        series_uuid = matching_file.stem
        if not matching_file.exists():
            continue

        pred_file = findings_pred_dir / f"{series_uuid}.json"
        gt_file = findings_gt_dir / f"{series_uuid}.json"

        if not pred_file.exists() or not gt_file.exists():
            continue

        matching_results = io.load_json(matching_file, raise_on_error=False)
        if not isinstance(matching_results, dict):
            logger.warning("Skipping corrupted matching file in summary: %s", matching_file)
            continue

        pred_findings_list = io.load_json(pred_file, raise_on_error=False)
        if not isinstance(pred_findings_list, list):
            logger.warning("Skipping report %s: invalid pred findings file", series_uuid)
            continue

        gt_findings_list = io.load_json(gt_file, raise_on_error=False)
        if not isinstance(gt_findings_list, list):
            logger.warning("Skipping report %s: invalid gt findings file", series_uuid)
            continue

        metrics_by_type = metrics.compute_report_metrics(
            gt_findings_list=gt_findings_list,
            pred_findings_list=pred_findings_list,
            matching_results=matching_results,
        )
        overall = metrics_by_type.get("__overall__", {})

        aggregator.add_report(
            report_stats={
                "tp": overall.get("tp", 0),
                "fp": overall.get("fp", 0),
                "fn": overall.get("fn", 0),
                "gt_count": overall.get("gt_count", 0),
                "pred_count": overall.get("pred_count", 0),
            },
            pred_findings_list=pred_findings_list,
            gt_findings_list=gt_findings_list,
            matching_results=matching_results,
            precomputed_per_type_stats={
                finding_type: {
                    "tp": metrics_by_type.get(finding_type, {}).get("tp", 0),
                    "fp": metrics_by_type.get(finding_type, {}).get("fp", 0),
                    "fn": metrics_by_type.get(finding_type, {}).get("fn", 0),
                    "gt": metrics_by_type.get(finding_type, {}).get("gt_count", 0),
                    "pred": metrics_by_type.get(finding_type, {}).get("pred_count", 0),
                }
                for finding_type in constants.FINDING_TYPES
            },
        )
        num_reports_included += 1

    metrics_summary = aggregator.get_summary()
    metadata = eval_utils.create_metadata(
        findings_gt_dir=findings_gt_dir,
        findings_pred_dir=findings_pred_dir,
        model_name=model_name,
        execution_time_seconds=execution_time_seconds,
        num_reports=num_reports_included,
    )
    summary_file = result_dir / constants.SUMMARY_FILE
    io.save_json({"metadata": metadata, "metrics": metrics_summary}, summary_file)
    logger.info("Saved summary to: %s", summary_file)
    eval_logging.log_metrics_summary(metrics_summary, metadata=metadata)


def evaluate_findings(
    result_dir: Path,
    model_name: str,
    workers: int = 5,
    fewshot: str | None = None,
    reasoning: str = "none",
) -> None:
    """Evaluate findings by comparing predicted against ground truth."""
    start_time = time.time()
    findings_gt_dir = result_dir / constants.FINDINGS_GT_DIR
    findings_pred_dir = result_dir / constants.FINDINGS_PRED_DIR

    logger.info("")
    logger.info("=" * 90)
    logger.info("RADMATCH EVALUATION")
    logger.info("-" * 90)
    logger.info("Configuration:")
    logger.info("  • findings_gt:   %s", findings_gt_dir)
    logger.info("  • findings_pred: %s", findings_pred_dir)
    logger.info("  • output:        %s", result_dir)
    logger.info("  • llm_judge:     %s", model_name)
    logger.info("  • workers:       %d", workers)
    logger.info("=" * 90)
    logger.info("")

    pred_files = sorted(findings_pred_dir.glob("*.json"))
    gt_files_dict = {f.stem: f for f in findings_gt_dir.glob("*.json")}

    if not pred_files:
        logger.error("No predicted findings files found in %s", findings_pred_dir)
        return

    all_reports: list[tuple[Path, Path, str]] = []
    for pred_file in pred_files:
        series_uuid = pred_file.stem
        if gt_file := gt_files_dict.get(series_uuid):
            all_reports.append((pred_file, gt_file, series_uuid))
        else:
            logger.warning("No ground truth findings found for %s", series_uuid)

    if not all_reports:
        logger.error("No matching report pairs found for evaluation")
        return

    matching_dir = result_dir / "matching"
    matching_dir.mkdir(parents=True, exist_ok=True)
    per_report_metrics_dir = result_dir / "per_report_metrics"
    per_report_metrics_dir.mkdir(parents=True, exist_ok=True)

    reports_to_evaluate: list[tuple[Path, Path, str]] = []
    skipped_count = 0

    for pred_file, gt_file, series_uuid in all_reports:
        matching_file = matching_dir / f"{series_uuid}.json"
        if matching_file.exists():
            if not pred_file.exists() or not gt_file.exists():
                logger.warning("Matching file exists but findings files missing for %s, will re-evaluate", series_uuid)
                reports_to_evaluate.append((pred_file, gt_file, series_uuid))
                continue

            skipped_count += 1
            metrics_file = per_report_metrics_dir / f"{series_uuid}.json"
            matching_results = io.load_json(matching_file, raise_on_error=False)

            if not isinstance(matching_results, dict):
                logger.warning("Corrupted matching file for %s, will re-evaluate", series_uuid)
                matching_file.unlink()
                if metrics_file.exists():
                    metrics_file.unlink()
                reports_to_evaluate.append((pred_file, gt_file, series_uuid))
                continue

            has_failed_findings = any(result.get("api_failed", False) for result in matching_results.values())
            if not metrics_file.exists() or has_failed_findings:
                pred_findings_list = io.load_json(pred_file, raise_on_error=True)
                gt_findings_list = io.load_json(gt_file, raise_on_error=True)
                _save_report_metrics(
                    result_dir=result_dir,
                    findings_gt_dir=findings_gt_dir,
                    findings_pred_dir=findings_pred_dir,
                    series_uuid=series_uuid,
                    pred_findings_list=pred_findings_list,
                    gt_findings_list=gt_findings_list,
                    matching_results=matching_results,
                    model_name=model_name,
                )
        else:
            reports_to_evaluate.append((pred_file, gt_file, series_uuid))

    failed_file = result_dir / constants.FAILED_FINDINGS_FILE
    previous_failed = io.load_json(failed_file, raise_on_error=False) if failed_file.exists() else {}
    if not isinstance(previous_failed, dict):
        previous_failed = {}

    if not reports_to_evaluate:
        logger.info("")
        logger.info("All reports have already been evaluated.")

        if previous_failed:
            total_failed = sum(len(ids) for ids in previous_failed.values())
            logger.info(
                "Found %d findings with API failures across %d reports to retry.",
                total_failed,
                len(previous_failed),
            )
            _reprocess_failed_findings(
                result_dir=result_dir,
                matching_dir=matching_dir,
                findings_gt_dir=findings_gt_dir,
                findings_pred_dir=findings_pred_dir,
                series_uuid_to_failed_ids=previous_failed,
                model_name=model_name,
                workers=workers,
                fewshot=fewshot,
                reasoning=reasoning,
            )
            execution_time = time.time() - start_time
            _compute_and_save_summary(
                result_dir,
                matching_dir,
                findings_gt_dir,
                findings_pred_dir,
                model_name,
                execution_time,
                all_reports=all_reports,
            )
            return

        logger.info("Recomputing global metrics summary from existing results...")
        execution_time = time.time() - start_time
        _compute_and_save_summary(
            result_dir,
            matching_dir,
            findings_gt_dir,
            findings_pred_dir,
            model_name,
            execution_time,
            all_reports=all_reports,
        )
        return

    if skipped_count > 0:
        logger.info("Skipping %d reports that already have results", skipped_count)
    logger.info("Evaluating %d/%d report pairs with %d worker(s)", len(reports_to_evaluate), len(all_reports), workers)

    client = llm_clients.build_single_client(model=model_name, max_tokens=constants.MAX_TOKENS, reasoning=reasoning)

    for pred_file, gt_file, series_uuid in tqdm(reports_to_evaluate, desc="Evaluating", unit="report"):
        pred_findings_list = io.load_json(pred_file, raise_on_error=True)
        gt_findings_list = io.load_json(gt_file, raise_on_error=True)

        matching_results = matching.match_findings_llm(
            pred_findings_list=pred_findings_list,
            gt_findings_list=gt_findings_list,
            series_uuid=series_uuid,
            client=client,
            workers=workers,
            fewshot=fewshot,
        )

        matching_file = matching_dir / f"{series_uuid}.json"
        io.save_json(
            {
                finding_id: {
                    "matched": result.get("matched", False),
                    "corresponding_gt_finding_id": result.get("corresponding_gt_finding_id"),
                    "confidence": result.get("confidence", "unknown"),
                    "reasoning": result.get("reasoning", ""),
                    "api_failed": result.get("api_failed", False),
                }
                for finding_id, result in matching_results.items()
            },
            matching_file,
        )

        _save_report_metrics(
            result_dir=result_dir,
            findings_gt_dir=findings_gt_dir,
            findings_pred_dir=findings_pred_dir,
            series_uuid=series_uuid,
            pred_findings_list=pred_findings_list,
            gt_findings_list=gt_findings_list,
            matching_results=matching_results,
            model_name=model_name,
        )

    failed = _detect_failed_findings(matching_dir)

    if failed:
        total_failed = sum(len(ids) for ids in failed.values())
        logger.info("")
        logger.info(
            "Found %d findings with API failures across %d reports. Reprocessing failed findings...",
            total_failed,
            len(failed),
        )
        _reprocess_failed_findings(
            result_dir=result_dir,
            matching_dir=matching_dir,
            findings_gt_dir=findings_gt_dir,
            findings_pred_dir=findings_pred_dir,
            series_uuid_to_failed_ids=failed,
            model_name=model_name,
            workers=workers,
            fewshot=fewshot,
            reasoning=reasoning,
        )
        failed = _detect_failed_findings(matching_dir)

    if failed:
        io.save_json(failed, failed_file)
        total_failed = sum(len(ids) for ids in failed.values())
        logger.warning(
            "Still have %d findings with API failures across %d reports. Run evaluation again to retry these findings.",
            total_failed,
            len(failed),
        )
    elif failed_file.exists():
        failed_file.unlink()

    processed_count = sum(1 for _, _, series_uuid in all_reports if (matching_dir / f"{series_uuid}.json").exists())
    if processed_count == len(all_reports):
        execution_time = time.time() - start_time
        _compute_and_save_summary(
            result_dir,
            matching_dir,
            findings_gt_dir,
            findings_pred_dir,
            model_name,
            execution_time,
            all_reports=all_reports,
        )
    else:
        remaining = len(all_reports) - processed_count
        logger.info("")
        logger.info(
            "Processed %d/%d reports. %d remaining. Metrics summary will be computed when all reports are processed.",
            processed_count,
            len(all_reports),
            remaining,
        )
