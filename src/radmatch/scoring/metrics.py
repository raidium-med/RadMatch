"""Stage 3c — MUC classification, PAR reclassification, error counts, safety recalls.

Pure functions over the Stages 3a/3b outputs, called by `scoring.pipeline`.

Matched pairs are tagged COR (no errors), PAR (some errors) or INC (status
inverted). `reclassify_to_effective_category` then promotes any PAR holding a major
error to INC, and the five surviving categories (COR/PAR/INC/MIS/SPU) are what the
output reports. Errors are then counted per significance tier (actionable, triage, critical) and
split by side: FN on the reference, FP on the prediction. See README.md for the metric
definitions.
"""

from __future__ import annotations

from typing import Sequence, TypedDict

from radmatch import constants

# ============================================================================
# Per-pair classification + PAR reclassification
# ============================================================================


def classify_muc(
    structured_errors: Sequence[dict],
    text_errors: Sequence[dict],
) -> tuple[str, bool]:
    """Return (muc_category, triggers_inc) for a matched pair.

    INC iff any structured error has `dimension == "clinical_status"` and
    `triggers_inc=True` (status inversion). INC overrides PAR/COR.
    Otherwise: any error → PAR; no errors → COR.
    """
    inc_triggered = any(e.get("dimension") == "clinical_status" and e.get("triggers_inc") for e in structured_errors)
    if inc_triggered:
        return "INC", True
    if structured_errors or text_errors:
        return "PAR", False
    return "COR", False


def reclassify_to_effective_category(record: dict) -> str:
    """Map the internal MUC category to one of {COR, PAR, INC} for the output.

    - PAR with any structured/text error of severity "major"            → INC
    - PAR with **any** `certainty` error AND `gt_significance=="critical"` → INC
      (a hedge on a critical finding — e.g. "possibly hemorrhage vs calcification"
      vs GT "acute hemorrhage" — is clinically a near-miss; PAR-credit would
      reward the model for hedging on safety-tier findings)
    - PAR with only minor non-certainty errors                          → PAR
      (kept distinct from a zero-error COR so the per-pair view preserves
      the "matched but imprecise" case)
    - COR / INC                                                          → unchanged
    """
    cat = record["muc_category"]
    if cat != "PAR":
        return cat
    errors = list(record.get("structured_errors", [])) + list(record.get("text_errors", []))
    if any(e.get("severity") == "major" for e in errors):
        return "INC"
    if record.get("gt_significance") == "critical" and any(e.get("dimension") == "certainty" for e in errors):
        return "INC"
    return "PAR"


def build_muc_record(
    match: dict,
    pred_finding: dict,
    gt_finding: dict,
    structured_errors: list[dict],
    text_errors: list[dict],
) -> dict:
    """Assemble a MatchRecord.

    `measurement` and `comparison` are judged on both sides — deterministically
    (Stage 3a flags) and by the LLM (Stage 3b grades the ones that matter). A
    deterministic error on a dimension suppresses the pair's LLM verdicts on it
    to avoid double-counting, *unless* the LLM graded it `major` and the
    deterministic side did not.
    """
    for dim in ("measurement", "comparison"):
        structured = [e for e in structured_errors if e.get("dimension") == dim]
        if structured:
            deterministic_major = any(e.get("severity") == "major" for e in structured)
            text_errors = [
                e
                for e in text_errors
                if e.get("dimension") != dim or (e.get("severity") == "major" and not deterministic_major)
            ]
    category, inc_triggered = classify_muc(structured_errors, text_errors)
    return {
        "pred_id": match["pred_id"],
        "gt_id": match["gt_id"],
        "muc_category": category,
        "structured_errors": list(structured_errors),
        "text_errors": list(text_errors),
        "inc_triggered": inc_triggered,
        "gt_significance": gt_finding["clinical_significance"],
        "pred_significance": pred_finding["clinical_significance"],
    }


# ============================================================================
# Effective MUC counts + actionable errors
# ============================================================================


def effective_muc_counts(
    records: Sequence[dict],
    n_spu: int,
    n_mis: int,
) -> dict[str, int]:
    """Per-distinct-finding counts under the {COR, PAR, INC, MIS, SPU} taxonomy.

    The summary reports the aggregate outcome PER FINDING (not per match
    edge): a GT correctly identified by ≥1 credited match counts as one COR,
    even under N:N where it participates in multiple match rows. Matched
    findings split across GT and Pred views; we count COR/PAR/INC on the GT
    side and rely on `n_spu` / `n_mis` for the orphans. This keeps
    `COR + PAR + INC + MIS == total_gt_findings` reconcilable.
    """
    per_gt: dict[tuple[str, str], set[str]] = {}
    for r in records:
        per_gt.setdefault(_gt_key(r), set()).add(reclassify_to_effective_category(r))
    counts = {cat: 0 for cat in constants.MUC_CATEGORIES}
    for cats in per_gt.values():
        counts[next((cat for cat in ("COR", "PAR") if cat in cats), "INC")] += 1
    counts["MIS"] = n_mis
    counts["SPU"] = n_spu
    return counts


def is_unsupported_claim(finding: dict) -> bool:
    """Whether an unmatched predicted finding (`SPU`) is an error. The reference's silence is read as
    absence: it refutes an unreported abnormality but agrees with an unreported normal statement."""
    return finding.get("clinical_status") != "normal"


class TierErrors(TypedDict):
    """Errors on one significance tier, split by side and source:
    `total == fn + fp`, `fn == fn_mis + fn_inc`, `fp == fp_spu + fp_inc`."""

    total: int
    fn: int
    fn_mis: int
    fn_inc: int
    fp: int
    fp_spu: int
    fp_inc: int


def compute_tier_errors(
    records: Sequence[dict],
    *,
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
    significance_pool: Sequence[str],
) -> TierErrors:
    """Errors involving findings in `significance_pool`, split by side.

    An error is an INC on a matched GT whose GT (or any matched pred) is in the
    pool, a MIS in the pool, or a SPU in the pool asserting an abnormality
    (`is_unsupported_claim`). INC counts once per unique GT (`all_inc`: every
    matched record fails to credit it); MIS / SPU per orphan.

    - ``fn`` (reference side): GT findings in the pool not credited, i.e. MIS +
      INC on a GT in the pool. Equals ``gt_total - recall_hits``.
    - ``fp`` (prediction side): such SPU in the pool + INC on a GT outside the pool
      with a matched pred in the pool (e.g. an abnormality where the GT is normal)
      + a pred in the pool contradicted by every GT it matches while each of those GTs
      is credited by another pred (`_contradicted_preds`).

    The side is relative to the pool: a notable GT contradicted by an urgent pred
    is an actionable FN but a triage FP.
    """
    pool = set(significance_pool)
    inc_gts = [b for b in _per_gt_safety_outcomes(records).values() if b["all_inc"]]
    fn_mis = sum(1 for f in unmatched_gt if f.get("clinical_significance") in pool)
    fn_inc = sum(1 for b in inc_gts if b["gt_sig"] in pool)
    fp_spu = sum(1 for f in unmatched_pred if f.get("clinical_significance") in pool and is_unsupported_claim(f))
    fp_inc = sum(1 for b in inc_gts if b["gt_sig"] not in pool and any(s in pool for s in b["pred_sigs"]))
    fp_inc += sum(1 for sig in _contradicted_preds(records) if sig in pool)
    fn, fp = fn_mis + fn_inc, fp_spu + fp_inc
    return {
        "total": fn + fp,
        "fn": fn,
        "fn_mis": fn_mis,
        "fn_inc": fn_inc,
        "fp": fp,
        "fp_spu": fp_spu,
        "fp_inc": fp_inc,
    }


def compute_tier_opportunities(
    records: Sequence[dict],
    *,
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
    significance_pool: Sequence[str],
) -> int:
    """Distinct findings of `significance_pool` at stake, the denominator of `errors_per_finding`.

    Matched GT findings whose GT or any matched pred is in the pool (the condition
    `compute_tier_errors` uses, so errors never exceed findings), plus the MIS GTs,
    the SPU preds asserting an abnormality and the contradicted preds in the pool.
    """
    pool = set(significance_pool)
    per_gt = _per_gt_safety_outcomes(records)
    distinct_gt = sum(1 for b in per_gt.values() if b["gt_sig"] in pool or any(s in pool for s in b["pred_sigs"]))
    distinct_gt += sum(1 for f in unmatched_gt if f.get("clinical_significance") in pool)
    spu = sum(1 for f in unmatched_pred if f.get("clinical_significance") in pool and is_unsupported_claim(f))
    contradicted = sum(1 for sig in _contradicted_preds(records) if sig in pool)
    return distinct_gt + spu + contradicted


# ============================================================================
# Subset assignment
# ============================================================================


def assign_subsets(finding: dict) -> list[str]:
    """Return the subsets this finding belongs to.

    - `measurement` if `measurements` is non-empty
    - `comparison` if `comparison` is not None
    - `abnormal-regular` if `clinical_status == "abnormal"` AND the finding is
      "regular" — i.e. it carries neither a measurement nor a comparison
    - `normal-regular` if `clinical_status == "normal"` AND the finding is regular

    The status subsets deliberately exclude measurement/comparison findings so
    they don't double-count against the `measurement` / `comparison` subsets;
    `*-regular` isolates the plain descriptive findings.
    """
    subsets: list[str] = []
    has_measurement = bool(finding.get("measurements"))
    has_comparison = finding.get("comparison") is not None
    if has_measurement:
        subsets.append("measurement")
    if has_comparison:
        subsets.append("comparison")
    is_regular = not has_measurement and not has_comparison
    if is_regular:
        if finding.get("clinical_status") == "abnormal":
            subsets.append("abnormal-regular")
        elif finding.get("clinical_status") == "normal":
            subsets.append("normal-regular")
    return subsets


# ============================================================================
# Per-tier errors and safety recall / precision
# ============================================================================


def _gt_key(record: dict) -> tuple[str, str]:
    """Composite `(series_uuid, gt_id)` key for per-GT aggregation.

    `series_uuid` is the empty string on per-report records (one report's
    worth) — degrades to gt_id alone, which is unique within a single report.
    The dataset orchestrator stamps `series_uuid` on every record before
    aggregation so cross-report collisions on the same `gt_id` label don't
    collapse distinct findings into one bucket.
    """
    return record.get("series_uuid", ""), record["gt_id"]


def _pred_key(record: dict) -> tuple[str, str]:
    """Composite `(series_uuid, pred_id)` key — symmetric to `_gt_key`."""
    return record.get("series_uuid", ""), record["pred_id"]


def count_distinct_findings(records: Sequence[dict]) -> tuple[int, int]:
    """Distinct `(pred, gt)` finding counts across a record list.

    Used to build clean partition totals (`total_pred_findings`,
    `total_gt_findings`) under N:N matching, where one finding can appear
    in several `(pred, gt)` match rows. Composite keys make this safe for
    both per-report and dataset-level aggregation.
    """
    return (
        len({_pred_key(r) for r in records}),
        len({_gt_key(r) for r in records}),
    )


def _per_gt_safety_outcomes(records: Sequence[dict]) -> dict[tuple[str, str], dict[str, object]]:
    """Aggregate matched records per unique GT; a credited (non-INC) record
    flips both `is_hit` and `all_inc=False` for the GT's bucket."""
    per_gt: dict[tuple[str, str], dict[str, object]] = {}
    for r in records:
        bucket = per_gt.setdefault(
            _gt_key(r),
            {"is_hit": False, "all_inc": True, "gt_sig": r.get("gt_significance"), "pred_sigs": []},
        )
        bucket["pred_sigs"].append(r.get("pred_significance"))
        if reclassify_to_effective_category(r) != "INC":
            bucket["all_inc"] = False
            bucket["is_hit"] = True
    return per_gt


def _per_pred_safety_outcomes(records: Sequence[dict]) -> dict[tuple[str, str], dict[str, object]]:
    """Pred-side mirror of `_per_gt_safety_outcomes`: aggregate matched records
    per unique pred so a pred matched to ≥1 credited GT counts as one hit."""
    per_pred: dict[tuple[str, str], dict[str, object]] = {}
    for r in records:
        bucket = per_pred.setdefault(
            _pred_key(r),
            {"is_hit": False, "pred_sig": r.get("pred_significance")},
        )
        if reclassify_to_effective_category(r) != "INC":
            bucket["is_hit"] = True
    return per_pred


def _contradicted_preds(records: Sequence[dict]) -> list[str | None]:
    """Significance of each pred that all its matches contradict (INC) while every GT it matches is credited by
    another pred, so the credit does not absorb the contradiction (an invented dissection beside a correct
    "no dissection"). A pred touching an all-INC GT is already counted through that GT."""
    inc_gts = {k for k, b in _per_gt_safety_outcomes(records).items() if b["all_inc"]}
    per_pred: dict[tuple[str, str], dict[str, object]] = {}
    for r in records:
        bucket = per_pred.setdefault(_pred_key(r), {"all_inc": True, "masked": True, "sig": r.get("pred_significance")})
        if reclassify_to_effective_category(r) != "INC":
            bucket["all_inc"] = False
        if _gt_key(r) in inc_gts:
            bucket["masked"] = False
    return [b["sig"] for b in per_pred.values() if b["all_inc"] and b["masked"]]


def compute_tier_metrics(
    records: Sequence[dict],
    *,
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
    significance_pool: Sequence[str],
) -> dict:
    """One `tiers.<name>` output block on `significance_pool`: errors split by side
    and source, errors per finding, and safety recall / precision with their counts.

    Recall hits are per unique GT and precision hits per unique pred (so N:N doesn't
    double-count); PAR-with-major reclassifies to INC and counts as a miss.
    Recall / precision are None on an empty pool (undefined, not "perfect").
    ``fn_total == gt_total - recall_hits``.
    """
    pool = set(significance_pool)
    errors = compute_tier_errors(
        records, unmatched_pred=unmatched_pred, unmatched_gt=unmatched_gt, significance_pool=pool
    )
    findings_total = compute_tier_opportunities(
        records, unmatched_pred=unmatched_pred, unmatched_gt=unmatched_gt, significance_pool=pool
    )
    per_gt = _per_gt_safety_outcomes(records)
    per_pred = _per_pred_safety_outcomes(records)
    gt_total = sum(1 for b in per_gt.values() if b["gt_sig"] in pool)
    gt_total += sum(1 for f in unmatched_gt if f.get("clinical_significance") in pool)
    pred_total = sum(1 for b in per_pred.values() if b["pred_sig"] in pool)
    pred_total += sum(1 for f in unmatched_pred if f.get("clinical_significance") in pool and is_unsupported_claim(f))
    recall_hits = sum(1 for b in per_gt.values() if b["gt_sig"] in pool and b["is_hit"])
    precision_hits = sum(1 for b in per_pred.values() if b["pred_sig"] in pool and b["is_hit"])
    return {
        "significance": list(significance_pool),
        "errors_total": errors["total"],
        "fn_total": errors["fn"],
        "fp_total": errors["fp"],
        "fn_mis_total": errors["fn_mis"],
        "fn_inc_total": errors["fn_inc"],
        "fp_spu_total": errors["fp_spu"],
        "fp_inc_total": errors["fp_inc"],
        "findings_total": findings_total,
        "errors_per_finding": errors["total"] / findings_total if findings_total else 0.0,
        "recall": recall_hits / gt_total if gt_total else None,
        "recall_hits": recall_hits,
        "gt_total": gt_total,
        "precision": precision_hits / pred_total if pred_total else None,
        "precision_hits": precision_hits,
        "pred_total": pred_total,
    }


# ============================================================================
# Attribute-dimension breakdown (diagnostic)
# ============================================================================


def compute_attribute_breakdown(records: Sequence[dict]) -> dict[str, dict[str, float]]:
    """Per-dimension clean / minor / major tally + share across matched records.

    Every matched pair (COR + PAR + INC internally) is evaluated on every
    attribute dimension by Stage 3a + 3b, so the `evaluated` denominator is
    uniform across all dimensions: `clean + minor + major == evaluated`.

    At most one classification per (record, dimension): a record with both a
    major and a minor on the same dimension counts as major.

    This is diagnostic data — it is not used by the per-tier errors (aER, ...)
    metric. Exposed on the dataset summary so the dashboard can render the
    "where did the attribute errors land" view.
    """
    breakdown: dict[str, dict[str, float]] = {}
    for dim in constants.ATTRIBUTE_DIMENSIONS_ALL:
        counts: dict[str, float] = {"clean": 0, "minor": 0, "major": 0}
        for r in records:
            errs = [e for e in list(r["structured_errors"]) + list(r["text_errors"]) if e.get("dimension") == dim]
            if any(e.get("severity") == "major" for e in errs):
                counts["major"] += 1
            elif any(e.get("severity") == "minor" for e in errs):
                counts["minor"] += 1
            else:
                counts["clean"] += 1
        evaluated = counts["clean"] + counts["minor"] + counts["major"]
        counts["evaluated"] = evaluated
        # 0.0 shares when nothing was evaluated; the integer counts make it obvious.
        denom = evaluated or 1
        for sev in ("clean", "minor", "major"):
            counts[f"{sev}_pct"] = counts[sev] / denom
        breakdown[dim] = counts
    return breakdown
