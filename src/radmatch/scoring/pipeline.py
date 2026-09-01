"""Stage 3 — per-pair scoring (`score_pair`) and dataset orchestration
(`score_dataset`, which fans out over the series on disk and writes
`metrics_summary.json`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping, Sequence

from radmatch import constants, io
from radmatch.finding_extraction.extract_utils import validate_and_normalize_finding
from radmatch.llm_utils import llm_clients, prompts
from radmatch.scoring import comparators, inference, metrics

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Per-pair pipeline
# ============================================================================


@dataclass
class ScoringContext:
    """Stable per-run config for `score_pair`. Built once by `score_dataset`."""

    client: llm_clients.Client
    fewshot: str | None = None
    output_dir: Path | None = None
    max_score_retries: int = inference.DEFAULT_MAX_RETRIES
    retry_degraded: bool = False


# Fields whose value changes should invalidate the Stage 3b cache. Mirrors the
# inputs Stage 3b actually consumes (text + structured attributes referenced by
# comparators). Keep in sync with `inference.detect_attribute_errors`.
_FINGERPRINTED_FIELDS: tuple[str, ...] = ("text", "clinical_status", "comparison", "measurements")


def _fingerprint_matched_findings(
    matches: Sequence[dict],
    pred_by_id: dict[str, dict],
    gt_by_id: dict[str, dict],
    indication: str = "",
    stage3b_config: Mapping[str, object] | None = None,
) -> str:
    """Hash of everything Stage 3b sees, so the cache invalidates on re-extracted
    findings, a changed indication, or a different judge / fewshot / reasoning.
    """
    payload = {
        "indication": indication,
        "stage3b_config": dict(stage3b_config) if stage3b_config else None,
        "pairs": [
            {
                "pred_id": m["pred_id"],
                "gt_id": m["gt_id"],
                "pred": {k: pred_by_id[m["pred_id"]].get(k) for k in _FINGERPRINTED_FIELDS},
                "gt": {k: gt_by_id[m["gt_id"]].get(k) for k in _FINGERPRINTED_FIELDS},
            }
            for m in matches
        ],
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _load_cached_text_errors(
    output_dir: Path | None,
    series_uuid: str,
    matches: list[dict],
    findings_fingerprint: str,
    retry_degraded: bool = False,
) -> tuple[list[list[dict]], bool] | None:
    """Return cached Stage 3b text errors if the on-disk match list still aligns.

    Returns None when there's no cache, the cache can't be read, the cached
    match list differs from `matches`, or the matched-finding payload
    fingerprint has changed since the cache was written (in which case
    rerunning the LLM is safer than reusing stale per-pair errors).
    """
    if output_dir is None:
        return None
    cached_path = output_dir / constants.ATTRIBUTE_ERRORS_DIR / f"{series_uuid}.json"
    if not cached_path.exists():
        return None
    cached = io.load_json(cached_path, raise_on_error=False)
    if not isinstance(cached, dict):
        return None
    if retry_degraded and cached.get("stage3b_degraded"):
        logger.info("[Report %s] Cached attribute_errors is degraded; recomputing", series_uuid)
        return None
    cached_matches = cached.get("matches") or []
    if [(m.get("pred_id"), m.get("gt_id")) for m in cached_matches] != [(m["pred_id"], m["gt_id"]) for m in matches]:
        logger.info("[Report %s] Cached attribute_errors no longer aligns with matches; recomputing", series_uuid)
        return None
    if cached.get("findings_fingerprint") != findings_fingerprint:
        logger.info(
            "[Report %s] Cached attribute_errors built from different finding payloads; recomputing", series_uuid
        )
        return None
    text_errors = cached.get("text_errors_per_pair")
    if not isinstance(text_errors, list) or len(text_errors) != len(matches):
        return None
    # Carry the marker forward: rewriting it as False on a cache hit would erase the
    # record that these text errors came from a degraded call.
    return text_errors, bool(cached.get("stage3b_degraded"))


def build_per_report_summary(
    muc_records: Sequence[dict],
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
    series_uuid: str | None = None,
) -> dict:
    """Per-report summary, keyed identically to `metrics_summary.json` minus the
    aggregate-only fields. `series_uuid` is None when the dataset aggregator reuses
    this for the same shape.
    """
    counts = metrics.effective_muc_counts(muc_records, n_spu=len(unmatched_pred), n_mis=len(unmatched_gt))
    distinct_matched_preds, distinct_matched_gts = metrics.count_distinct_findings(muc_records)
    metadata: dict[str, object] = {
        "total_gt_findings": distinct_matched_gts + counts["MIS"],
        "total_pred_findings": distinct_matched_preds + counts["SPU"],
    }
    if series_uuid is not None:
        metadata = {"series_uuid": series_uuid, **metadata}
    return {
        "metadata": metadata,
        "actionable_errors_total": metrics.compute_actionable_errors(muc_records, unmatched_pred, unmatched_gt),
        "clinical_safety_summary": metrics.compute_safety_summary(muc_records, unmatched_gt, unmatched_pred),
        "muc_counts": counts,
        "attribute_breakdown": metrics.compute_attribute_breakdown(muc_records),
    }


def score_pair(
    matching_output: dict,
    findings_pred: list[dict],
    findings_gt: list[dict],
    series_uuid: str,
    ctx: ScoringContext,
    indication: str = "",
) -> dict:
    """Stage 3a + 3b + 3c for one report pair.

    Findings must already be normalised — pass raw ones through
    `finding_extraction.extract_utils.validate_and_normalize_finding` first.
    `indication` is injected into the Stage 3b prompt and folded into the cache
    fingerprint. Returns `{series_uuid, muc_records, unmatched_pred (SPU),
    unmatched_gt (MIS), matching}`, and writes `attribute_errors/` +
    `per_report_metrics/` when `ctx.output_dir` is set.
    """
    pred_by_id = {f["finding_id"]: f for f in findings_pred}
    gt_by_id = {f["finding_id"]: f for f in findings_gt}
    matches = matching_output["matches"]

    structured_per_pair: list[list[dict]] = [
        comparators.compute_structured_errors(pred_by_id[m["pred_id"]], gt_by_id[m["gt_id"]]) for m in matches
    ]
    stage3b_config = {
        "judge": getattr(ctx.client, "model", None),
        "reasoning": getattr(ctx.client, "reasoning", None),
        "fewshot": ctx.fewshot,
        "prompt_hash": prompts.prompt_fingerprint(prompts.PROMPT_ATTRIBUTE_ERRORS),
    }
    findings_fingerprint = _fingerprint_matched_findings(
        matches, pred_by_id, gt_by_id, indication, stage3b_config=stage3b_config
    )
    # Stage 3b — resume from cache when the on-disk matches AND the matched-finding payloads still align.
    cached_text = _load_cached_text_errors(
        ctx.output_dir, series_uuid, matches, findings_fingerprint, ctx.retry_degraded
    )
    if cached_text is not None:
        text_per_pair, stage3b_degraded = cached_text
    else:
        text_per_pair, stage3b_degraded = inference.detect_attribute_errors(
            matches=matches,
            findings_pred=pred_by_id,
            findings_gt=gt_by_id,
            structured_errors_per_pair=structured_per_pair,
            series_uuid=series_uuid,
            client=ctx.client,
            fewshot=ctx.fewshot,
            indication=indication,
            max_retries=ctx.max_score_retries,
        )

    muc_records: list[dict] = [
        metrics.build_muc_record(
            match=m,
            pred_finding=pred_by_id[m["pred_id"]],
            gt_finding=gt_by_id[m["gt_id"]],
            structured_errors=structured_per_pair[i],
            text_errors=text_per_pair[i] if i < len(text_per_pair) else [],
        )
        for i, m in enumerate(matches)
    ]
    # Fail loud rather than silently dropping IDs the matching file references
    # but the loaded findings no longer contain: a stale cached matching artifact
    # would otherwise produce inflated per-report metrics (missing SPU/MIS).
    stale_pred = [pid for pid in matching_output["unmatched_pred"] if pid not in pred_by_id]
    stale_gt = [gid for gid in matching_output["unmatched_gt"] if gid not in gt_by_id]
    if stale_pred or stale_gt:
        raise ValueError(
            f"Matching file for series '{series_uuid}' references unknown finding IDs — "
            f"likely stale cache. Re-run Stage 2 against the current findings. "
            f"unmatched_pred unknowns: {stale_pred}; unmatched_gt unknowns: {stale_gt}"
        )
    unmatched_pred = [pred_by_id[pid] for pid in matching_output["unmatched_pred"]]
    unmatched_gt = [gt_by_id[gid] for gid in matching_output["unmatched_gt"]]

    if ctx.output_dir is not None:
        attr_dir = ctx.output_dir / constants.ATTRIBUTE_ERRORS_DIR
        attr_dir.mkdir(parents=True, exist_ok=True)
        io.save_json(
            {
                "matches": matches,
                "findings_fingerprint": findings_fingerprint,
                "structured_errors_per_pair": structured_per_pair,
                "text_errors_per_pair": text_per_pair,
                "stage3b_degraded": stage3b_degraded,
                "muc_records": muc_records,
            },
            attr_dir / f"{series_uuid}.json",
        )
        per_report_dir = ctx.output_dir / constants.PER_REPORT_METRICS_DIR
        per_report_dir.mkdir(parents=True, exist_ok=True)
        io.save_json(
            build_per_report_summary(muc_records, unmatched_pred, unmatched_gt, series_uuid=series_uuid),
            per_report_dir / f"{series_uuid}.json",
        )

    return {
        "series_uuid": series_uuid,
        "muc_records": muc_records,
        "unmatched_pred": unmatched_pred,
        "unmatched_gt": unmatched_gt,
        "matching": matching_output,
    }


def _fmt_recall(value: float | None) -> str:
    """Format a safety recall for the SCORING SUMMARY log line.

    ``compute_safety_recall`` returns ``None`` on an empty pool; the formatter
    must not apply ``:.4f`` to that (would raise ``TypeError`` after the
    summary JSON is already on disk).
    """
    return f"{value:.4f}" if isinstance(value, (int, float)) else "n/a"


# ============================================================================
# Dataset-level aggregation helpers
# ============================================================================


def _bucket_metrics(records: Sequence[dict], unmatched_pred: Sequence[dict], unmatched_gt: Sequence[dict]) -> dict:
    """MUC counts + actionable errors + safety summary for one subset of records.

    `actionable_errors_per_finding` normalises by the subset's actionable-finding
    pool, not by report count — a per-report average understates a rare subset
    purely by prevalence, so it would not compare across subsets.
    """
    counts = metrics.effective_muc_counts(records, n_spu=len(unmatched_pred), n_mis=len(unmatched_gt))
    actionable_errors_total = metrics.compute_actionable_errors(records, unmatched_pred, unmatched_gt)
    actionable_findings_total = metrics.compute_actionable_opportunities(records, unmatched_pred, unmatched_gt)
    return {
        "muc_counts": counts,
        "actionable_errors_total": actionable_errors_total,
        "actionable_findings_total": actionable_findings_total,
        "actionable_errors_per_finding": (
            actionable_errors_total / actionable_findings_total if actionable_findings_total else 0.0
        ),
        "clinical_safety_summary": metrics.compute_safety_summary(records, unmatched_gt, unmatched_pred),
    }


def _compute_subset_metrics(per_report: list[dict]) -> dict[str, dict]:
    """Compute effective MUC counts + actionable_errors on each subset.

    Subset membership uses GT side for matched / MIS records; pred side for SPU.
    """
    buckets: dict[str, dict[str, list]] = {
        s: {"records": [], "unmatched_pred": [], "unmatched_gt": []} for s in constants.SUBSETS
    }
    for report in per_report:
        for r in report["muc_records"]:
            for s in r.get("gt_subsets", []):
                buckets[s]["records"].append(r)
        for f in report["unmatched_pred"]:
            for s in metrics.assign_subsets(f):
                buckets[s]["unmatched_pred"].append(f)
        for f in report["unmatched_gt"]:
            for s in metrics.assign_subsets(f):
                buckets[s]["unmatched_gt"].append(f)
    return {s: _bucket_metrics(b["records"], b["unmatched_pred"], b["unmatched_gt"]) for s, b in buckets.items()}


# ============================================================================
# Dataset-level entry point
# ============================================================================


def score_dataset(
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    matching_dir: Path,
    output_dir: Path,
    llm_judge: str,
    fewshot: str | None = None,
    workers: int = 15,
    reasoning: str = "none",
    client_factory=None,
    series_allowlist: set[str] | None = None,
    indications_dir: Path | None = None,
    runtime_start_s: float | None = None,
    max_score_retries: int = inference.DEFAULT_MAX_RETRIES,
    retry_degraded: bool = False,
) -> dict:
    """Score every series with a matching output, aggregate, write
    `metrics_summary.json`. A failing pair is logged and counted, not fatal.

    `series_allowlist` restricts the run to the given stems, so `--limit` against a
    directory holding a larger prior run does not silently aggregate stale files.
    `indications_dir` defaults to `output_dir/indications/` when present.
    `client_factory(model, max_tokens, reasoning) -> Client` overrides construction
    for testing.
    """
    if client_factory is None:
        llm_clients.assert_credentials_for(llm_judge)

    start_time = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    indications_dir = io.resolve_indications_dir(indications_dir, output_dir)
    indications = io.load_indications(indications_dir)

    gt_files = {p.stem: p for p in findings_gt_dir.glob("*.json")}
    pred_files = {p.stem: p for p in findings_pred_dir.glob("*.json")}
    matching_files = {p.stem: p for p in matching_dir.glob("*.json")}
    shared_set = set(gt_files) & set(pred_files) & set(matching_files)
    if series_allowlist is not None:
        shared_set &= series_allowlist
    shared = sorted(shared_set)
    attr_dir = output_dir / constants.ATTRIBUTE_ERRORS_DIR
    cached_reports = sum(1 for s in shared if (attr_dir / f"{s}.json").exists())

    io.log_stage_banner(
        "SCORING (Stage 3)",
        [
            ("judge", llm_judge),
            ("findings_gt", findings_gt_dir),
            ("findings_pred", findings_pred_dir),
            ("matching", matching_dir),
            ("output", output_dir),
            ("fewshot", fewshot),
            ("workers", workers),
            ("reasoning", reasoning),
            ("retries", max_score_retries),
            ("indications", indications_dir),
        ],
    )
    logger.info("Reports to score:  %6d  (gt ∩ pred ∩ matching)", len(shared))
    logger.info("  • Stage 3b cached: %6d  (text errors reused from prior run)", cached_reports)

    if client_factory is None:
        client_factory = llm_clients.build_client
    ctx = ScoringContext(
        client=client_factory(model=llm_judge, max_tokens=constants.MAX_TOKENS, reasoning=reasoning),
        fewshot=fewshot,
        output_dir=output_dir,
        max_score_retries=max_score_retries,
        retry_degraded=retry_degraded,
    )

    def _score_one(series_uuid: str) -> tuple[str, dict | None, dict[str, dict] | None, str | None]:
        try:
            gt_findings = [validate_and_normalize_finding(f) for f in io.load_json(gt_files[series_uuid])]
            pred_findings = [validate_and_normalize_finding(f) for f in io.load_json(pred_files[series_uuid])]
            matching_output = io.load_json(matching_files[series_uuid], raise_on_error=True)
            per_pair = score_pair(
                matching_output,
                pred_findings,
                gt_findings,
                series_uuid,
                ctx,
                indications.get(series_uuid, ""),
            )
            gt_by_id = {f["finding_id"]: f for f in gt_findings}
            return series_uuid, per_pair, gt_by_id, None
        except Exception as exc:  # noqa: BLE001 — soft-fail per pair, surface in summary
            logger.error("[Report %s] Stage 3 failed: %s", series_uuid, exc)
            return series_uuid, None, None, str(exc)

    per_report: list[dict] = []
    gt_by_series: dict[str, dict[str, dict]] = {}
    failures: list[dict] = []
    for series_uuid, pair_result, gt_map, error in io.process_pairs_in_parallel(
        shared, _score_one, workers=workers, desc="Scoring", unit="pair"
    ):
        if pair_result is None:
            failures.append({"series_uuid": series_uuid, "reason": error})
            continue
        per_report.append(pair_result)
        gt_by_series[series_uuid] = gt_map

    if failures:
        failed_path = output_dir / constants.FAILED_REPORTS_SCORING_FILE
        io.save_json(failures, failed_path)
        logger.info("Saved %d failed reports to: %s", len(failures), failed_path)

    all_records: list[dict] = []
    all_u_pred: list[dict] = []
    all_u_gt: list[dict] = []
    for report in per_report:
        gt_map = gt_by_series.get(report["series_uuid"], {})
        for r in report["muc_records"]:
            gt = gt_map.get(r["gt_id"])
            r["gt_subsets"] = metrics.assign_subsets(gt) if gt else []
            # Series-tag records so per-GT dedup in safety / actionable-error aggregation
            # doesn't collide across reports that reuse the same `gt_id` (e.g. both s1 and
            # s2 having a "g1" finding).
            r["series_uuid"] = report["series_uuid"]
        all_records.extend(report["muc_records"])
        all_u_pred.extend(report["unmatched_pred"])
        all_u_gt.extend(report["unmatched_gt"])

    muc_counts = metrics.effective_muc_counts(all_records, n_spu=len(all_u_pred), n_mis=len(all_u_gt))
    safety = metrics.compute_safety_summary(all_records, all_u_gt, all_u_pred)
    attribute_breakdown = metrics.compute_attribute_breakdown(all_records)
    actionable_errors_total = metrics.compute_actionable_errors(all_records, all_u_pred, all_u_gt)
    actionable_errors_per_report = actionable_errors_total / len(per_report) if per_report else 0.0
    # Opportunity-normalized twin of the headline: errors per actionable finding.
    # Report-count-independent, so it's the baseline the per-subset rates compare
    # against and is robust to differing finding density across runs.
    actionable_findings_total = metrics.compute_actionable_opportunities(all_records, all_u_pred, all_u_gt)
    actionable_errors_per_finding = (
        actionable_errors_total / actionable_findings_total if actionable_findings_total else 0.0
    )
    # Distinct-finding totals keep the partition clean under N:N matching.
    distinct_matched_preds, distinct_matched_gts = metrics.count_distinct_findings(all_records)

    # Token usage accumulated across every LLM stage in this process
    # (the full extract→match→score pipeline for a `run_all` invocation).
    summary = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "llm_judge": llm_judge,
            "fewshot": fewshot,
            "n_reports": len(per_report),
            "n_failed_reports": len(failures),
            "total_gt_findings": distinct_matched_gts + muc_counts["MIS"],
            "total_pred_findings": distinct_matched_preds + muc_counts["SPU"],
            "runtime": round(time.time() - (runtime_start_s if runtime_start_s is not None else start_time), 2),
            "token_usage": llm_clients.token_report(),
        },
        "actionable_errors_per_report": actionable_errors_per_report,
        "actionable_errors_total": actionable_errors_total,
        "actionable_errors_per_finding": actionable_errors_per_finding,
        "actionable_findings_total": actionable_findings_total,
        "clinical_safety_summary": safety,
        "muc_counts": muc_counts,
        "attribute_breakdown": attribute_breakdown,
        "subsets": _compute_subset_metrics(per_report),
    }

    io.save_json(summary, output_dir / constants.SUMMARY_FILE)

    summary_lines = [
        f"  Reports scored:                {len(per_report):6d}",
    ]
    if failures:
        summary_lines.append(f"  Reports failed:                {len(failures):6d}  (see logs above)")
    summary_lines.extend(
        [
            f"  MUC counts:                  COR={muc_counts['COR']}  INC={muc_counts['INC']}  "
            f"MIS={muc_counts['MIS']}  SPU={muc_counts['SPU']}",
            f"  Actionable errors per report:  {actionable_errors_per_report:.3f}  "
            f"(total {actionable_errors_total} across {len(per_report)} reports)",
            "  Clinical safety:",
            f"    • triage_recall:        {_fmt_recall(safety['triage_recall'])}  "
            f"({safety['triage_gt_total']} triage GT findings — critical+urgent)",
            f"    • triage_precision:     {_fmt_recall(safety['triage_precision'])}  "
            f"({safety['triage_pred_total']} triage pred findings)",
            f"    • actionable_recall:    {_fmt_recall(safety['actionable_recall'])}  "
            f"({safety['actionable_gt_total']} actionable GT findings — critical+urgent+notable)",
            f"    • actionable_precision: {_fmt_recall(safety['actionable_precision'])}  "
            f"({safety['actionable_pred_total']} actionable pred findings)",
            f"  Summary written to: {output_dir / constants.SUMMARY_FILE}",
            f"RadMatch score complete in {time.time() - start_time:.1f}s",
        ]
    )
    io.log_stage_summary("SCORING SUMMARY", summary_lines)
    return summary
