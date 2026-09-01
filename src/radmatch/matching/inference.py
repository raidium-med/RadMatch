"""Stage 2 entry points — per-pair matching and dataset-level orchestration."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from radmatch import constants, io
from radmatch.finding_extraction.extract_utils import validate_and_normalize_finding
from radmatch.llm_utils import llm_clients, prompts
from radmatch.matching.utils import (
    MATCHING_SCHEMA,
    build_matching_messages,
    canonical_order,
    normalize_match_scopes,
    validate_matching_output,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Per-pair data shapes
# ============================================================================


# Sized for reasoning models: the budget covers hidden reasoning tokens plus the
# answer, and a heavy reasoner can burn >8k thinking before returning anything.
_MAX_TOKENS_MATCHING: int = 32768
DEFAULT_MAX_RETRIES: int = 2


@dataclass
class MatchingContext:
    """Stable per-run config for `match_findings`. Built once by `match_dataset`."""

    client: llm_clients.Client
    fewshot: str | None = None
    max_validation_retries: int = DEFAULT_MAX_RETRIES


@dataclass
class _MatchAttempt:
    """Outcome of one Stage 2 LLM call: success | bad-json | invalid-output."""

    status: Literal["success", "invalid_json", "invalid_output"]
    parsed: dict | None = None
    errors: list[str] = field(default_factory=list)


def _attempt_match_call(
    pred_findings: list[dict],
    gt_findings: list[dict],
    correction_errors: list[str],
    input_pred_ids: set[str],
    input_gt_ids: set[str],
    ctx: MatchingContext,
    indication: str = "",
) -> _MatchAttempt:
    """One LLM call + parse + validation. Caller drives the retry loop."""
    messages = build_matching_messages(pred_findings, gt_findings, ctx.fewshot, correction_errors, indication)
    content = llm_clients.call_llm(
        ctx.client,
        messages=messages,
        response_format=MATCHING_SCHEMA,
        max_tokens=_MAX_TOKENS_MATCHING,
    )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return _MatchAttempt("invalid_json", errors=[f"Response was not valid JSON: {exc}"])
    errors = validate_matching_output(parsed, input_pred_ids, input_gt_ids)
    if errors:
        return _MatchAttempt("invalid_output", parsed=parsed, errors=errors)
    return _MatchAttempt("success", parsed=parsed)


def _trivial_match_result(input_pred_ids: set[str], input_gt_ids: set[str]) -> dict | None:
    """Short-circuit when at least one side is empty — no LLM call needed."""
    if not input_pred_ids and not input_gt_ids:
        return {"matches": [], "unmatched_pred": [], "unmatched_gt": [], "validation_fallback": False, "retries": 0}
    if not input_pred_ids:
        return {
            "matches": [],
            "unmatched_pred": [],
            "unmatched_gt": list(input_gt_ids),
            "validation_fallback": False,
            "retries": 0,
        }
    if not input_gt_ids:
        return {
            "matches": [],
            "unmatched_pred": list(input_pred_ids),
            "unmatched_gt": [],
            "validation_fallback": False,
            "retries": 0,
        }
    return None


def _fallback_match_result(
    last_parsed: dict,
    input_pred_ids: set[str],
    input_gt_ids: set[str],
    pred_id_order: list[str],
    retries: int,
) -> dict:
    """Salvage individually valid matches from the last bad response; orphan IDs → unmatched.

    The shape of `last_parsed` mirrors whatever the LLM returned on the final
    attempt — possibly malformed (non-dict top level, non-list `matches`,
    non-dict match entries). Skip anything that isn't a usable
    `{pred_id, gt_id, reasoning}` object rather than crashing on `.get()`.
    """
    accepted: list[dict] = []
    seen_pred: set[str] = set()
    seen_gt: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    raw_matches = last_parsed.get("matches", []) if isinstance(last_parsed, dict) else []
    if not isinstance(raw_matches, list):
        raw_matches = []
    # N:N matching — both pred and gt may repeat across rows. Only dedupe on the
    # exact (pred_id, gt_id) pair so a duplicated row from the LLM doesn't land twice.
    for m in raw_matches:
        if not isinstance(m, dict):
            continue
        pid = m.get("pred_id")
        gid = m.get("gt_id")
        if pid in input_pred_ids and gid in input_gt_ids and (pid, gid) not in seen_pairs:
            scope = m.get("match_scope")
            if scope not in constants.MATCH_SCOPE_VALUES:
                continue
            accepted.append({"pred_id": pid, "gt_id": gid, "reasoning": m.get("reasoning", ""), "match_scope": scope})
            seen_pred.add(pid)
            seen_gt.add(gid)
            seen_pairs.add((pid, gid))
    return {
        "matches": canonical_order(normalize_match_scopes(accepted), pred_id_order),
        "unmatched_pred": sorted(input_pred_ids - seen_pred),
        "unmatched_gt": sorted(input_gt_ids - seen_gt),
        "validation_fallback": True,
        "retries": retries,
    }


# ============================================================================
# Per-pair matching
# ============================================================================


def match_findings(
    pred_findings: list[dict],
    gt_findings: list[dict],
    series_uuid: str,
    ctx: MatchingContext,
    indication: str = "",
) -> dict:
    """One LLM call per report pair, returning a `MatchingOutput` dict.

    Retries with a correction prompt on validation failure; once the budget is spent,
    falls back to keeping the individually valid matches, orphaning the rest, and
    setting `validation_fallback=True`. `indication` adds clinical context.
    """
    input_pred_ids = {f["finding_id"] for f in pred_findings}
    input_gt_ids = {f["finding_id"] for f in gt_findings}
    trivial = _trivial_match_result(input_pred_ids, input_gt_ids)
    if trivial is not None:
        return trivial

    pred_id_order = [f["finding_id"] for f in pred_findings]

    correction_errors: list[str] = []
    last_parsed: dict = {}
    for attempt in range(ctx.max_validation_retries + 1):
        try:
            outcome = _attempt_match_call(
                pred_findings,
                gt_findings,
                correction_errors,
                input_pred_ids,
                input_gt_ids,
                ctx,
                indication,
            )
        except Exception:  # noqa: BLE001 — log + re-raise so the caller sees the original exception
            logger.error("[Report %s] Stage 2 matching call failed; re-raising", series_uuid)
            raise

        if outcome.status == "success":
            parsed = outcome.parsed or {}
            return {
                "matches": canonical_order(normalize_match_scopes(parsed.get("matches", [])), pred_id_order),
                "unmatched_pred": list(parsed.get("unmatched_pred", [])),
                "unmatched_gt": list(parsed.get("unmatched_gt", [])),
                "validation_fallback": False,
                "retries": attempt,
            }
        if outcome.parsed is not None:
            last_parsed = outcome.parsed
        logger.warning(
            "[Report %s] Stage 2 matching attempt %d/%d failed (%s): %s",
            series_uuid,
            attempt + 1,
            ctx.max_validation_retries + 1,
            outcome.status,
            outcome.errors,
        )
        correction_errors = outcome.errors

    logger.error(
        "[Report %s] Stage 2 matching: validation failed after %d attempts; falling back",
        series_uuid,
        ctx.max_validation_retries + 1,
    )
    return _fallback_match_result(last_parsed, input_pred_ids, input_gt_ids, pred_id_order, ctx.max_validation_retries)


# ============================================================================
# Dataset-level orchestrator
# ============================================================================


def _matching_cache_valid(
    path: Path, expected_config: dict[str, object], retry_degraded: bool = False
) -> bool:
    """Cached `matching/<series>.json` is valid iff it exists and its `matching_config`
    matches the current judge / fewshot / reasoning / prompt hash. Files from earlier
    versions (no stamp, or a different prompt hash) count as stale.

    With `retry_degraded`, a cached result that fell back is also treated as stale — a
    fallback keeps only the valid subset of matches, so re-asking is worth the cost."""
    if not path.exists():
        return False
    cached = io.load_json(path, raise_on_error=False)
    if not isinstance(cached, dict):
        return False
    if retry_degraded and cached.get("validation_fallback"):
        return False
    return cached.get("matching_config") == expected_config


def match_dataset(
    findings_gt_dir: Path,
    findings_pred_dir: Path,
    output_dir: Path,
    llm_judge: str,
    fewshot: str | None = None,
    workers: int = 15,
    reasoning: str = "none",
    client_factory=None,
    series_allowlist: set[str] | None = None,
    indications_dir: Path | None = None,
    max_match_retries: int = DEFAULT_MAX_RETRIES,
    retry_degraded: bool = False,
) -> None:
    """Match every series present in both findings dirs, writing
    `output_dir/matching/<series>.json`. Pairs with an existing output are skipped.

    `series_allowlist` restricts the run to the given stems, so `--limit` against a
    directory holding a larger prior run does not pick up stale files.
    `indications_dir` defaults to `output_dir/indications/` when present.
    `client_factory(model, max_tokens, reasoning) -> Client` overrides construction
    for testing.
    """
    if client_factory is None:
        llm_clients.assert_credentials_for(llm_judge)

    start_time = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    matching_dir = output_dir / constants.MATCHING_DIR
    matching_dir.mkdir(parents=True, exist_ok=True)

    indications_dir = io.resolve_indications_dir(indications_dir, output_dir)
    indications = io.load_indications(indications_dir)

    gt_files = {p.stem: p for p in findings_gt_dir.glob("*.json")}
    pred_files = {p.stem: p for p in findings_pred_dir.glob("*.json")}
    shared_set = set(gt_files) & set(pred_files)
    if series_allowlist is not None:
        shared_set &= series_allowlist
    shared = sorted(shared_set)

    # Stamp each `matching/<series>.json` with the producing config so a
    # subsequent run with a different judge / fewshot / reasoning invalidates
    # the cache instead of silently scoring stale alignments.
    matching_config = {
        "judge": llm_judge,
        "fewshot": fewshot,
        "reasoning": reasoning,
        "prompt_hash": prompts.prompt_fingerprint(prompts.PROMPT_MATCHING),
    }
    todo = [
        s
        for s in shared
        if not _matching_cache_valid(matching_dir / f"{s}.json", matching_config, retry_degraded)
    ]
    skipped = len(shared) - len(todo)

    io.log_stage_banner(
        "MATCHING (Stage 2)",
        [
            ("judge", llm_judge),
            ("findings_gt", findings_gt_dir),
            ("findings_pred", findings_pred_dir),
            ("output", matching_dir),
            ("fewshot", fewshot),
            ("workers", workers),
            ("reasoning", reasoning),
            ("retries", max_match_retries),
            ("indications", indications_dir),
        ],
    )
    logger.info("Reports found:     %6d  (gt ∩ pred series)", len(shared))
    logger.info("  • to process:    %6d", len(todo))
    logger.info("  • cached:        %6d", skipped)
    if not todo:
        logger.info("Nothing to do — all reports already matched. Done in %.1fs", time.time() - start_time)
        logger.info("=" * 90)
        return

    if client_factory is None:
        client_factory = llm_clients.build_client
    ctx = MatchingContext(
        client=client_factory(model=llm_judge, max_tokens=constants.MAX_TOKENS, reasoning=reasoning),
        fewshot=fewshot,
        max_validation_retries=max_match_retries,
    )

    stats = {"fallback": 0, "retries": 0, "matched_pairs": 0, "unmatched_gt": 0, "unmatched_pred": 0, "failed": 0}

    def _match_one(series_uuid: str) -> tuple[str, dict | None, str | None]:
        try:
            gt_findings = io.load_json(gt_files[series_uuid], raise_on_error=True)
            pred_findings = io.load_json(pred_files[series_uuid], raise_on_error=True)
            gt_norm = [validate_and_normalize_finding(f) for f in gt_findings]
            pred_norm = [validate_and_normalize_finding(f) for f in pred_findings]
            result = match_findings(pred_norm, gt_norm, series_uuid, ctx, indications.get(series_uuid, ""))
            io.save_json({**result, "matching_config": matching_config}, matching_dir / f"{series_uuid}.json")
            return series_uuid, result, None
        except Exception as exc:  # noqa: BLE001 — soft-fail per pair, surface in summary
            logger.error("[Report %s] Stage 2 failed: %s", series_uuid, exc)
            return series_uuid, None, str(exc)

    failures: list[dict] = []
    for series_uuid, result, error in io.process_pairs_in_parallel(
        todo, _match_one, workers=workers, desc="Matching", unit="pair"
    ):
        if result is None:
            stats["failed"] += 1
            failures.append({"series_uuid": series_uuid, "reason": error})
            continue
        stats["retries"] += result["retries"]
        stats["fallback"] += int(result["validation_fallback"])
        stats["matched_pairs"] += len(result["matches"])
        stats["unmatched_gt"] += len(result["unmatched_gt"])
        stats["unmatched_pred"] += len(result["unmatched_pred"])

    if failures:
        failed_path = output_dir / constants.FAILED_REPORTS_MATCHING_FILE
        io.save_json(failures, failed_path)
        logger.info("Saved %d failed reports to: %s", len(failures), failed_path)

    summary_lines = [
        f"  Reports processed:      {len(todo) - stats['failed']:6d}",
    ]
    if stats["failed"]:
        summary_lines.append(f"  Reports failed:         {stats['failed']:6d}  (see logs above)")
    summary_lines.extend(
        [
            f"  Matched findings:       {stats['matched_pairs']:6d}",
            f"  Unmatched (gt side):    {stats['unmatched_gt']:6d}",
            f"  Unmatched (pred side):  {stats['unmatched_pred']:6d}",
            f"  Validation retries:     {stats['retries']:6d}",
            f"  Validation fallbacks:   {stats['fallback']:6d}",
            f"RadMatch match complete in {time.time() - start_time:.1f}s",
        ]
    )
    io.log_stage_summary("MATCHING SUMMARY", summary_lines)
