"""Stage 3c — MUC classification, PAR reclassification, error counts, safety recalls.

Pure functions over the Stages 3a/3b outputs, called by `scoring.pipeline`.

Matched pairs are tagged COR (no errors), PAR (some errors) or INC (status
inverted). `reclassify_to_effective_category` then promotes any PAR holding a major
error to INC, and the five surviving categories (COR/PAR/INC/MIS/SPU) are what the
output reports. See README.md for the metric definitions.
"""

from __future__ import annotations

from typing import Literal, Sequence, TypedDict

from radmatch import constants


class MatchRecord(TypedDict):
    """A scored matched pair, assembled in Stage 3c.

    `structured_errors` and `text_errors` are kept as ``list[dict]`` rather
    than ``list[AttributeError]`` to avoid cross-module type imports
    (the per-error shape is documented inline in `scoring.comparators` and
    `scoring.inference`).

    `muc_category` is the *internal* category (COR / PAR / INC). The output
    summaries reclassify PAR via `reclassify_to_effective_category`.
    """

    pred_id: str
    gt_id: str
    muc_category: Literal["COR", "PAR", "INC"]
    structured_errors: list[dict]
    text_errors: list[dict]
    inc_triggered: bool
    gt_significance: Literal["critical", "urgent", "notable", "routine"]
    pred_significance: Literal["critical", "urgent", "notable", "routine"]


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

    `measurement` is judged on both sides — deterministically (Stage 3a) and,
    for clinical-boundary crossings the thresholds miss, by the LLM (Stage 3b).
    To avoid double-counting, *any* deterministic measurement error (value diff,
    omission, addition, or category mismatch) suppresses *all* of the pair's LLM
    measurement verdicts. This is deliberately coarse: it can drop a genuine LLM
    boundary catch when an unrelated deterministic measurement error also fired,
    but that pair is already flagged on `measurement`, so the category outcome is
    unchanged. The LLM verdict only survives when Stage 3a was silent on
    measurement — the gap it exists to fill.
    """
    if any(e.get("dimension") == "measurement" for e in structured_errors):
        text_errors = [e for e in text_errors if e.get("dimension") != "measurement"]
    category, inc_triggered = classify_muc(structured_errors, text_errors)
    return {
        "pred_id": match["pred_id"],
        "gt_id": match["gt_id"],
        "muc_category": category,
        "structured_errors": list(structured_errors),
        "text_errors": list(text_errors),
        "inc_triggered": inc_triggered,
        "gt_significance": gt_finding.get("clinical_significance", constants.DEFAULT_CLINICAL_SIGNIFICANCE),
        "pred_significance": pred_finding.get("clinical_significance", constants.DEFAULT_CLINICAL_SIGNIFICANCE),
        "match_scope": match["match_scope"],
    }


# ============================================================================
# Effective MUC counts + actionable errors
# ============================================================================


def _aggregate_per_finding_categories(records: Sequence[dict], key_fn) -> dict[tuple[str, str], str]:
    """Map each distinct finding (keyed by `key_fn`) to its aggregate effective
    category — `_best_category` across all the matches the finding participates in.

    Mirrors `_per_gt_safety_outcomes`'s "any credited match rescues the GT"
    semantic at the category level: a finding correctly identified by at least
    one match shows up as COR/PAR even if other matches were INC. A finding
    matched only via INC (or only via uncredited-generic on an actionable tier)
    shows up as INC.
    """
    actionable = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    per_finding: dict[tuple[str, str], dict[str, object]] = {}
    for r in records:
        cat = reclassify_to_effective_category(r)
        bucket = per_finding.setdefault(
            key_fn(r),
            {"any_credited_cor": False, "any_credited_par": False},
        )
        if cat == "INC":
            continue
        credited = is_credited_match(
            category=cat,
            match_scope=r["match_scope"],
            gt_actionable=r.get("gt_significance") in actionable,
        )
        if credited:
            if cat == "COR":
                bucket["any_credited_cor"] = True
            elif cat == "PAR":
                bucket["any_credited_par"] = True

    def _resolve(bucket: dict[str, object]) -> str:
        if bucket["any_credited_cor"]:
            return "COR"
        if bucket["any_credited_par"]:
            return "PAR"
        return "INC"  # all matches are INC or uncredited generic

    return {key: _resolve(bucket) for key, bucket in per_finding.items()}


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
    gt_categories = _aggregate_per_finding_categories(records, key_fn=_gt_key)
    counts = {cat: 0 for cat in constants.MUC_CATEGORIES}
    for cat in gt_categories.values():
        counts[cat] += 1
    counts["MIS"] = n_mis
    counts["SPU"] = n_spu
    return counts


def compute_actionable_errors(
    records: Sequence[dict],
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
) -> int:
    """Count of errors involving findings in the actionable pool
    (`{critical, urgent, notable}`).

    INC contribution is per unique GT (`all_inc`): a GT counts as 1 error
    iff every matched record fails to credit it AND the GT (or any
    matched pred) is in the actionable pool. MIS / SPU stay per-orphan.
    """
    actionable = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    per_gt = _per_gt_safety_outcomes(records)
    total = sum(
        1
        for b in per_gt.values()
        if b["all_inc"] and (b["gt_sig"] in actionable or any(s in actionable for s in b["pred_sigs"]))
    )
    total += sum(1 for f in unmatched_pred if f.get("clinical_significance") in actionable)
    total += sum(1 for f in unmatched_gt if f.get("clinical_significance") in actionable)
    return total


def compute_actionable_opportunities(
    records: Sequence[dict],
    unmatched_pred: Sequence[dict],
    unmatched_gt: Sequence[dict],
) -> int:
    """Count of distinct actionable findings "at stake" — the denominator for a
    prevalence-independent error *rate*.

    An actionable error (see `compute_actionable_errors`) is an INC on an
    actionable matched pair, an actionable MIS, or an actionable SPU. Each maps
    to exactly one distinct finding, so the matching opportunity pool is:

        distinct actionable matched GT findings + actionable MIS gts + actionable SPU preds

    A matched pair counts as actionable on the same condition the numerator uses
    — the GT *or* any matched pred is actionable — so a routine GT matched to an
    actionable pred (a false-positive INC the numerator counts) has a matching
    opportunity here. Keeping the two definitions in lock-step guarantees
    numerator ≤ denominator, so the resulting `actionable_errors_per_finding`
    rate stays in [0, 1].

    Dividing `compute_actionable_errors` by this count yields the fraction of
    actionable findings that ended in an error — comparable across subsets
    regardless of how common each finding type is (unlike a per-report average,
    which a rare subset deflates purely by prevalence).
    """
    actionable = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    per_gt = _per_gt_safety_outcomes(records)
    distinct_actionable_gt = sum(
        1 for b in per_gt.values() if b["gt_sig"] in actionable or any(s in actionable for s in b["pred_sigs"])
    )
    distinct_actionable_gt += sum(1 for f in unmatched_gt if f.get("clinical_significance") in actionable)
    actionable_spu = sum(1 for f in unmatched_pred if f.get("clinical_significance") in actionable)
    return distinct_actionable_gt + actionable_spu


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
# Safety recalls
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


def is_credited_match(*, category: str, match_scope: str | None, gt_actionable: bool) -> bool:
    """Whether a match record credits its GT for recall + actionable-error rescue.

    A record credits iff it reclassifies to COR/PAR AND (scope ∈
    {direct, aggregate} OR GT is non-actionable). A critical GT covered
    only by `generic` boilerplate gets no credit; routine GTs accept
    any scope.
    """
    if category == "INC":
        return False
    if match_scope in constants.MATCH_SCOPE_CREDITED:
        return True
    return not gt_actionable


def _per_gt_safety_outcomes(records: Sequence[dict]) -> dict[tuple[str, str], dict[str, object]]:
    """Aggregate matched records per unique GT; a credited record flips
    both `is_hit` and `all_inc=False` for the GT's bucket."""
    per_gt: dict[tuple[str, str], dict[str, object]] = {}
    actionable = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    for r in records:
        bucket = per_gt.setdefault(
            _gt_key(r),
            {"is_hit": False, "all_inc": True, "gt_sig": r.get("gt_significance"), "pred_sigs": []},
        )
        bucket["pred_sigs"].append(r.get("pred_significance"))
        if is_credited_match(
            category=reclassify_to_effective_category(r),
            match_scope=r["match_scope"],
            gt_actionable=r.get("gt_significance") in actionable,
        ):
            bucket["all_inc"] = False
            bucket["is_hit"] = True
    return per_gt


def _per_pred_safety_outcomes(records: Sequence[dict]) -> dict[tuple[str, str], dict[str, object]]:
    """Pred-side mirror of `_per_gt_safety_outcomes`: aggregate matched records
    per unique pred so a pred matched to ≥1 credited GT counts as one hit."""
    per_pred: dict[tuple[str, str], dict[str, object]] = {}
    actionable = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    for r in records:
        bucket = per_pred.setdefault(
            _pred_key(r),
            {"is_hit": False, "pred_sig": r.get("pred_significance")},
        )
        if is_credited_match(
            category=reclassify_to_effective_category(r),
            match_scope=r["match_scope"],
            gt_actionable=r.get("gt_significance") in actionable,
        ):
            bucket["is_hit"] = True
    return per_pred


def _recall_from_per_gt(
    per_gt: dict[tuple[str, str], dict[str, object]],
    unmatched_gt: Sequence[dict],
    pool: set[str],
) -> float | None:
    """Recall from a prebuilt `per_gt`. Returns None on empty denominator."""
    numerator = sum(1 for b in per_gt.values() if b["gt_sig"] in pool and b["is_hit"])
    denominator = sum(1 for b in per_gt.values() if b["gt_sig"] in pool)
    denominator += sum(1 for f in unmatched_gt if f.get("clinical_significance") in pool)
    return numerator / denominator if denominator else None


def _precision_from_per_pred(
    per_pred: dict[tuple[str, str], dict[str, object]],
    unmatched_pred: Sequence[dict],
    pool: set[str],
) -> float | None:
    """Precision from a prebuilt `per_pred`. Returns None on empty denominator.

    Numerator   = unique matched preds in pool with ≥1 credited match.
    Denominator = unique matched preds in pool + unmatched preds (SPU) in pool.
    """
    numerator = sum(1 for b in per_pred.values() if b["pred_sig"] in pool and b["is_hit"])
    denominator = sum(1 for b in per_pred.values() if b["pred_sig"] in pool)
    denominator += sum(1 for f in unmatched_pred if f.get("clinical_significance") in pool)
    return numerator / denominator if denominator else None


def compute_safety_recall(
    records: Sequence[dict],
    unmatched_gt: Sequence[dict],
    significance_pool: Sequence[str],
) -> float | None:
    """Recall restricted to GT findings in `significance_pool`.

    Numerator   = unique matched GTs on the pool with any effective COR/PAR.
    Denominator = unique matched GTs on the pool + unmatched GTs on the pool.
    Returns ``None`` when the denominator is empty (undefined, not "perfect" —
    treating empty as 1.0 silently inflates downstream consumers).
    """
    return _recall_from_per_gt(_per_gt_safety_outcomes(records), unmatched_gt, set(significance_pool))


def compute_safety_summary(
    records: Sequence[dict],
    unmatched_gt: Sequence[dict],
    unmatched_pred: Sequence[dict],
) -> dict:
    """Triage + actionable safety recall + precision plus numerator / denominator counts.

    Pools: triage = critical+urgent; actionable = critical+urgent+notable.
    Recall hits are per-unique-GT, precision hits per-unique-pred (so N:N
    doesn't double-count). PAR-with-major reclassifies to INC and counts as a
    miss; vacuous pool → metric = None.
    """
    triage_pool = set(constants.TRIAGE_SIGNIFICANCE_TIERS)
    actionable_pool = set(constants.ACTIONABLE_SIGNIFICANCE_TIERS)
    per_gt = _per_gt_safety_outcomes(records)
    per_pred = _per_pred_safety_outcomes(records)

    def _gt_count(pool: set[str], predicate) -> int:
        return sum(1 for b in per_gt.values() if b["gt_sig"] in pool and predicate(b))

    def _pred_hit_count(pool: set[str]) -> int:
        return sum(1 for b in per_pred.values() if b["pred_sig"] in pool and b["is_hit"])

    def _pred_total(pool: set[str]) -> int:
        return sum(1 for b in per_pred.values() if b["pred_sig"] in pool) + sum(
            1 for f in unmatched_pred if f.get("clinical_significance") in pool
        )

    return {
        "triage_recall": _recall_from_per_gt(per_gt, unmatched_gt, triage_pool),
        "actionable_recall": _recall_from_per_gt(per_gt, unmatched_gt, actionable_pool),
        "triage_precision": _precision_from_per_pred(per_pred, unmatched_pred, triage_pool),
        "actionable_precision": _precision_from_per_pred(per_pred, unmatched_pred, actionable_pool),
        "triage_hit_count": _gt_count(triage_pool, lambda b: b["is_hit"]),
        "actionable_hit_count": _gt_count(actionable_pool, lambda b: b["is_hit"]),
        "triage_gt_total": _gt_count(triage_pool, lambda _: True)
        + sum(1 for f in unmatched_gt if f.get("clinical_significance") in triage_pool),
        "actionable_gt_total": _gt_count(actionable_pool, lambda _: True)
        + sum(1 for f in unmatched_gt if f.get("clinical_significance") in actionable_pool),
        "triage_pred_hit_count": _pred_hit_count(triage_pool),
        "actionable_pred_hit_count": _pred_hit_count(actionable_pool),
        "triage_pred_total": _pred_total(triage_pool),
        "actionable_pred_total": _pred_total(actionable_pool),
        "triage_mis_count": sum(1 for f in unmatched_gt if f.get("clinical_significance") in triage_pool),
        "triage_inc_count": _gt_count(triage_pool, lambda b: b["all_inc"]),
        "actionable_mis_count": sum(1 for f in unmatched_gt if f.get("clinical_significance") in actionable_pool),
        "actionable_inc_count": _gt_count(actionable_pool, lambda b: b["all_inc"]),
    }


# ============================================================================
# Attribute-dimension breakdown (diagnostic)
# ============================================================================


def compute_attribute_breakdown(records: Sequence[dict]) -> dict[str, dict[str, float]]:
    """Per-dimension clean / minor / major tally + share across matched records.

    Every matched pair (COR + PAR + INC internally) is evaluated on every
    attribute dimension by Stage 3a + 3b, so the `evaluated` denominator is
    uniform across all seven dimensions: `clean + minor + major == evaluated`.

    At most one classification per (record, dimension): a record with both a
    major and a minor on the same dimension counts as major.

    This is diagnostic data — it is not used by the headline `actionable_errors`
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
