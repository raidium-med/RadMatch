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
from importlib.metadata import version
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


# Fields whose value changes should invalidate the Stage 3b cache. Mirrors the
# inputs Stage 3b actually consumes (text + structured attributes referenced by
# comparators). Keep in sync with `inference.detect_attribute_errors`.
_FINGERPRINTED_FIELDS: tuple[str, ...] = ("text", "clinical_status", "comparison", "measurements")


def _stage3b_config(judge: str | None, reasoning: str | None, fewshot: str | None) -> dict[str, object]:
    """The judge config folded into the Stage 3b cache fingerprint."""
    return {
        "judge": judge,
        "reasoning": reasoning,
        "fewshot": fewshot,
        "prompt_hash": prompts.prompt_fingerprint(prompts.PROMPT_ATTRIBUTE_ERRORS),
        "schema_hash": io.fingerprint(inference._ATTRIBUTE_ERRORS_SCHEMA),
        "chunk_size": inference._STAGE3B_CHUNK_SIZE,
    }


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
) -> list[list[dict]] | None:
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
    return text_errors


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
        "tiers": _tiers_block(muc_records, unmatched_pred, unmatched_gt),
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
    stage3b_config = _stage3b_config(
        getattr(ctx.client, "model", None), getattr(ctx.client, "reasoning", None), ctx.fewshot
    )
    findings_fingerprint = _fingerprint_matched_findings(
        matches, pred_by_id, gt_by_id, indication, stage3b_config=stage3b_config
    )
    # Stage 3b — resume from cache when the on-disk matches AND the matched-finding payloads still align.
    text_per_pair = _load_cached_text_errors(ctx.output_dir, series_uuid, matches, findings_fingerprint)
    if text_per_pair is None:
        text_per_pair = inference.detect_attribute_errors(
            matches=matches,
            findings_pred=pred_by_id,
            findings_gt=gt_by_id,
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


def _fmt_rate(value: float | None) -> str:
    """Format a recall / precision for the SCORING SUMMARY.

    They are ``None`` on an empty pool; the formatter must not apply ``:.3f`` to
    that (would raise ``TypeError`` after the summary JSON is already on disk).
    """
    return f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"


# Acronym prefix per error tier: aER = aFN + aFP, aRec, aPrec; tER, ... ; cER, ...
_TIER_PREFIX = {"actionable": "a", "triage": "t", "critical": "c"}


def _tier_table_lines(tiers: dict[str, dict]) -> list[str]:
    """One aligned row per tier for the SCORING SUMMARY, then a two-line legend."""
    lines = [f"  {'tier':<16}{'ER':>7}{'FN':>8}{'FP':>8}{'errors/finding':>17}   {'Rec':<21}Prec"]
    for name, t in tiers.items():
        recall = f"{_fmt_rate(t['recall'])} ({t['recall_hits']}/{t['gt_total']})"
        precision = f"{_fmt_rate(t['precision'])} ({t['precision_hits']}/{t['pred_total']})"
        lines.append(
            f"  {f'{name} ({_TIER_PREFIX[name]})':<16}{t['errors_per_report']:>7.3f}{t['fn_per_report']:>8.3f}"
            f"{t['fp_per_report']:>8.3f}{t['errors_per_finding']:>17.3f}   {recall:<21}{precision}"
        )
    tier_defs = ", ".join(f"{_TIER_PREFIX[n]} = {'+'.join(t['significance'])}" for n, t in tiers.items())
    lines += [
        f"  {tier_defs}. ER = FN + FP: errors per report (aER = aFN + aFP, ...).",
        "  FN: reference findings of the tier missed or contradicted. FP: claims of the tier the reference lacks.",
    ]
    return lines


# ============================================================================
# Dataset-level aggregation helpers
# ============================================================================


def _tiers_block(
    records: Sequence[dict],
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
    n_reports: int | None = None,
) -> dict[str, dict]:
    """The `tiers` output block: `compute_tier_metrics` for each of `constants.ERROR_TIERS`,
    plus `errors` / `fn` / `fp` per report when `n_reports` is given (dataset level).
    """
    tiers = {}
    for name, pool in constants.ERROR_TIERS.items():
        tier = metrics.compute_tier_metrics(
            records, unmatched_pred=unmatched_pred, unmatched_gt=unmatched_gt, significance_pool=pool
        )
        if n_reports is not None:
            per_report = {
                f"{k}_per_report": tier[f"{k}_total"] / n_reports if n_reports else 0.0 for k in ("errors", "fn", "fp")
            }
            tier = {"significance": tier.pop("significance"), **per_report, **tier}
        tiers[name] = tier
    return tiers


def _bucket_metrics(records: Sequence[dict], unmatched_pred: Sequence[dict], unmatched_gt: Sequence[dict]) -> dict:
    """MUC counts + per-tier metrics for one subset of records.

    `errors_per_finding` normalises by the subset's tier-finding pool, not by report
    count — a per-report average understates a rare subset purely by prevalence, so
    it would not compare across subsets.
    """
    return {
        "muc_counts": metrics.effective_muc_counts(records, n_spu=len(unmatched_pred), n_mis=len(unmatched_gt)),
        "tiers": _tiers_block(records, unmatched_pred, unmatched_gt),
    }


def _compute_subset_metrics(per_report: list[dict]) -> dict[str, dict]:
    """Compute effective MUC counts + per-tier metrics on each subset.

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
) -> dict:
    """Score every series with a matching output, aggregate, write
    `metrics_summary.json`. A failing pair is logged and counted, not fatal.

    `series_allowlist` restricts the run to the given stems, so `--limit` against a
    directory holding a larger prior run does not silently aggregate stale files.
    `indications_dir` defaults to `output_dir/indications/` when present.
    `client_factory(model, reasoning) -> Client` overrides construction
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
    logger.info("  • Stage 3b on disk: %6d  (reused only if still valid)", cached_reports)

    if client_factory is None:
        client_factory = llm_clients.build_client
    ctx = ScoringContext(
        client=client_factory(model=llm_judge, reasoning=reasoning),
        fewshot=fewshot,
        output_dir=output_dir,
        max_score_retries=max_score_retries,
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
    attribute_breakdown = metrics.compute_attribute_breakdown(all_records)
    # Per tier: errors per report (headline aER / tER) split into FN + FP, and the
    # opportunity-normalized errors per finding, which is report-count-independent so
    # it's the baseline the per-subset rates compare against.
    tiers = _tiers_block(all_records, all_u_pred, all_u_gt, n_reports=len(per_report))
    # Distinct-finding totals keep the partition clean under N:N matching.
    distinct_matched_preds, distinct_matched_gts = metrics.count_distinct_findings(all_records)

    # Token usage + USD cost accumulated across every LLM stage in this process
    # (the full extract→match→score pipeline for a `run_all` invocation).
    token = llm_clients.token_report()
    summary = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "radmatch_version": version("radmatch"),
            "llm_judge": llm_judge,
            "fewshot": fewshot,
            "n_reports": len(per_report),
            "n_failed_reports": len(failures),
            "total_gt_findings": distinct_matched_gts + muc_counts["MIS"],
            "total_pred_findings": distinct_matched_preds + muc_counts["SPU"],
            "runtime": round(time.time() - (runtime_start_s if runtime_start_s is not None else start_time), 2),
            "token_usage": token["token_usage"],
            "token_cost": token["token_cost"],
        },
        "tiers": tiers,
        "muc_counts": muc_counts,
        "attribute_breakdown": attribute_breakdown,
        "subsets": _compute_subset_metrics(per_report),
    }

    io.save_json(summary, output_dir / constants.SUMMARY_FILE)

    failed = f", {len(failures)} failed (see logs above)" if failures else ""
    summary_lines = [
        f"  Reports     {len(per_report)} scored{failed}",
        f"  Findings    {summary['metadata']['total_gt_findings']} GT, "
        f"{summary['metadata']['total_pred_findings']} pred",
        "  MUC counts  " + "  ".join(f"{c} {muc_counts[c]}" for c in constants.MUC_CATEGORIES),
        "",
        *_tier_table_lines(tiers),
        "",
        f"  Summary written to: {output_dir / constants.SUMMARY_FILE}",
        f"RadMatch score complete in {time.time() - start_time:.1f}s",
    ]
    io.log_stage_summary("SCORING SUMMARY", summary_lines)
    return summary
