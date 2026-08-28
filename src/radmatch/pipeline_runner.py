"""Chained Stage 1 → 2 → 3 orchestration over a single output directory."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from radmatch import constants
from radmatch.finding_extraction.inference import extract_findings
from radmatch.indication_extraction.inference import extract_indications
from radmatch.llm_utils.llm_clients import assert_credentials_for, reset_token_usage
from radmatch.matching import inference as matching_defaults
from radmatch.matching.inference import match_dataset
from radmatch.scoring import inference as scoring_defaults
from radmatch.scoring.pipeline import score_dataset

if TYPE_CHECKING:
    from os import PathLike

logger = logging.getLogger(__name__)


def run_all(
    reports_pred_dir: PathLike[str] | str,
    output_dir: PathLike[str] | str,
    llm_extractor: str,
    llm_judge: str,
    reports_gt_dir: PathLike[str] | str | None = None,
    findings_gt_dir: PathLike[str] | str | None = None,
    fewshot: str | None = None,
    workers: int = 15,
    limit: int | None = None,
    reasoning: str = "none",
    indications_dir: PathLike[str] | str | None = None,
    auto_extract_indications: bool = False,
    max_match_retries: int = matching_defaults.DEFAULT_MAX_RETRIES,
    max_score_retries: int = scoring_defaults.DEFAULT_MAX_RETRIES,
    retry_passes: int = 1,
    retry_degraded: bool = False,
    client_factory=None,
) -> dict:
    """Chain Stage 1 → 2 → 3 over one output dir, returning `metrics_summary.json`.

    Rerunning with the same paths skips any stage whose output is already on disk.

    `indications_dir` holds per-series `<series>.txt` files (from
    `extract_indications`); they are injected into every LLM stage and copied into the
    results directory for the dashboard. `auto_extract_indications` runs that
    preprocessor first instead — the two are mutually exclusive.

    `max_match_retries` / `max_score_retries` are the extra attempts Stage 2 and
    Stage 3b make on a malformed LLM reply before falling back. They are outside both
    cache fingerprints, so raising them does not invalidate existing results.

    `retry_passes` runs the whole chain up to that many times (1 = a single pass, the
    default). Because every stage caches on success, a later pass only revisits reports
    that dropped. It stops early once nothing is missing, or once a pass recovers
    nothing.

    `retry_degraded` additionally revisits reports that *fell back* rather than failed —
    a Stage 2 validation fallback or a degraded Stage 3b payload. Those write valid
    cached output, so without this they are never retried.

    `client_factory(model, max_tokens, reasoning) -> Client` overrides construction in
    every stage and skips the up-front credential check.
    """
    if indications_dir and auto_extract_indications:
        raise ValueError("`indications_dir` and `auto_extract_indications` are mutually exclusive.")

    if client_factory is None:
        assert_credentials_for(llm_extractor, llm_judge)
    reset_token_usage()
    pipeline_start = time.time()
    output_path = Path(output_dir)
    results_dir = output_path / constants.RESULTS_DIR
    indications_path = Path(indications_dir) if indications_dir else None

    if auto_extract_indications:
        # Prefer GT reports as the indication source (matches Stage 1 GT-side
        # extraction context). Fall back to pred when only `--findings-gt` is set.
        indication_source = Path(reports_gt_dir) if reports_gt_dir else Path(reports_pred_dir)
        indications_path = results_dir / constants.INDICATIONS_DIR
        logger.info("Auto-extracting indications from %s → %s", indication_source, indications_path)
        extract_indications(
            reports_dir=indication_source,
            output_dir=indications_path,
            llm_extractor=llm_extractor,
            workers=workers,
            reasoning=reasoning,
            client_factory=client_factory,
        )

    # Pin the series before extraction, so a later stage can't widen the run by
    # picking up stale findings from a bigger prior pass. Sorted as Stage 1 sorts.
    series_allowlist: set[str] | None = None
    if limit is not None:
        pred_report_files = sorted(Path(reports_pred_dir).glob("*.txt"))
        series_allowlist = {f.stem for f in pred_report_files[:limit]}

    expected = (
        len(series_allowlist) if series_allowlist is not None else len(list(Path(reports_pred_dir).glob("*.txt")))
    )

    # Each stage caches on success only, so re-running the chain retries exactly the
    # reports that dropped and skips the rest. Stop as soon as a pass recovers nothing:
    # a report failing for a deterministic reason (unreadable file, a prompt the judge
    # always mangles) would otherwise re-pay LLM cost on every remaining pass.
    dropped = expected
    for pass_index in range(1, max(1, retry_passes) + 1):
        if pass_index > 1:
            logger.info("Retry pass %d/%d — %d report(s) still missing", pass_index, retry_passes, dropped)
        else:
            logger.info("Running full pipeline: extract_findings → match → score")

        extract_findings(
            reports_gt_dir=Path(reports_gt_dir) if reports_gt_dir else None,
            reports_pred_dir=Path(reports_pred_dir),
            output_dir=output_path,
            llm_extractor=llm_extractor,
            fewshot=fewshot,
            workers=workers,
            limit=limit,
            findings_gt_dir=Path(findings_gt_dir) if findings_gt_dir else None,
            reasoning=reasoning,
            indications_dir=indications_path,
            client_factory=client_factory,
        )
        match_dataset(
            findings_gt_dir=results_dir / constants.FINDINGS_GT_DIR,
            findings_pred_dir=results_dir / constants.FINDINGS_PRED_DIR,
            output_dir=results_dir,
            llm_judge=llm_judge,
            fewshot=fewshot,
            workers=workers,
            reasoning=reasoning,
            series_allowlist=series_allowlist,
            indications_dir=indications_path,
            max_match_retries=max_match_retries,
            retry_degraded=retry_degraded,
            client_factory=client_factory,
        )
        summary = score_dataset(
            findings_gt_dir=results_dir / constants.FINDINGS_GT_DIR,
            findings_pred_dir=results_dir / constants.FINDINGS_PRED_DIR,
            matching_dir=results_dir / constants.MATCHING_DIR,
            output_dir=results_dir,
            llm_judge=llm_judge,
            fewshot=fewshot,
            workers=workers,
            reasoning=reasoning,
            series_allowlist=series_allowlist,
            indications_dir=indications_path,
            runtime_start_s=pipeline_start,
            max_score_retries=max_score_retries,
            retry_degraded=retry_degraded,
            client_factory=client_factory,
        )

        metadata = summary.get("metadata", {}) if isinstance(summary, dict) else {}
        n_reports = int(metadata.get("n_reports", 0))
        n_failed_in_score = int(metadata.get("n_failed_reports", 0))
        still_dropped = max(0, expected - n_reports - n_failed_in_score)
        if still_dropped == 0:
            break
        if pass_index > 1 and still_dropped >= dropped:
            logger.warning(
                "Retry pass %d recovered nothing (%d still missing); stopping early.", pass_index, still_dropped
            )
            dropped = still_dropped
            break
        dropped = still_dropped

    # Cross-stage sum, so silent drops between stages are at least visible.
    if dropped:
        logger.warning(
            "Coverage: %d of %d input reports missing from the summary "
            "(%d scored, %d Stage-3 failures, %d dropped earlier — see Stage 1 / Stage 2 logs).",
            dropped,
            expected,
            n_reports,
            n_failed_in_score,
            dropped,
        )

    return summary
