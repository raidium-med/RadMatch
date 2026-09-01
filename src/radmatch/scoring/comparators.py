"""Stage 3a — deterministic comparators over the structured fields of a matched pair.

`clinical_status` (inversion → INC downstream), `comparison` (cross-bucket → major)
and `measurement` (per-category thresholds). No LLM call; the free-text dimensions
are Stage 3b's job (`scoring.inference`).
"""

from __future__ import annotations

from itertools import permutations
from typing import Callable, Sequence

from radmatch import constants

# Modality-agnostic. Anatomy-specific cliffs (spleen 130 mm, AAA 55 mm, Fleischner
# bands) need covariates the measurement lacks, so they are left to the LLM path.
_SIZE_REL_DIFF_MAJOR: float = 0.2  # rel-diff above which `size` diff is `major`
_ATTENUATION_ABS_DIFF_MAJOR: float = 20.0  # abs HU diff above which `attenuation` diff is `major`
_RATIO_REL_DIFF_MAJOR: float = 0.3  # rel-diff above which `ratio` diff is `major`

# Floor (mm) on a relative-difference flag, at inter-observer reproducibility.
# Without it, 2 mm → 3 mm (+50%) would count as major.
_SIZE_ABS_FLOOR_MM: float = 2.0

# Tissue-characterization cliffs (HU): macroscopic fat (< -10), lipid-rich adrenal
# adenoma (<= 10), simple fluid (<= 20). Landing on opposite sides is major whatever
# the magnitude, catching sub-20-HU crossings the flat threshold misses.
# These are NON-CONTRAST cut-offs and the pipeline carries no acquisition phase, so
# they over-call on a contrast phase — the safe direction.
_ATTENUATION_CLIFFS_HU: tuple[float, ...] = (-10.0, 10.0, 20.0)


def _error(
    dimension: str,
    severity: str,
    pred_value: object | None,
    gt_value: object | None,
    reasoning: str,
    *,
    triggers_inc: bool = False,
) -> dict:
    err = {
        "dimension": dimension,
        "severity": severity,
        "pred_value": pred_value,
        "gt_value": gt_value,
        "reasoning": reasoning,
    }
    if triggers_inc:
        err["triggers_inc"] = True
    return err


# ============================================================================
# clinical_status
# ============================================================================


def classify_status_conflict(pred_status: str, gt_status: str) -> dict | None:
    """Status inversion is always `major` and triggers INC downstream."""
    if pred_status == gt_status:
        return None
    return _error(
        dimension="clinical_status",
        severity="major",
        pred_value=pred_status,
        gt_value=gt_status,
        reasoning=f"clinical_status differs: pred={pred_status!r} vs gt={gt_status!r}",
        triggers_inc=True,
    )


# ============================================================================
# comparison
# ============================================================================


def classify_comparison_conflict(
    pred_comparison: str | None,
    gt_comparison: str | None,
) -> dict | None:
    """Bucket-based comparison conflict severity.

    BENIGN={stable, improving, resolved}, ACTIVE={worsening, new}.
    Cross-bucket → major; same-bucket → minor; identical → no error;
    one-sided mention (one side None) → minor.
    """
    if pred_comparison == gt_comparison:
        return None
    if pred_comparison is None or gt_comparison is None:
        return _error(
            dimension="comparison",
            severity="minor",
            pred_value=pred_comparison,
            gt_value=gt_comparison,
            reasoning="one-sided comparison mention",
        )
    pred_active = pred_comparison in constants.ACTIVE_COMPARISONS
    gt_active = gt_comparison in constants.ACTIVE_COMPARISONS
    severity = "major" if pred_active != gt_active else "minor"
    reasoning = (
        f"comparison crosses activity bucket: pred={pred_comparison!r}, gt={gt_comparison!r}"
        if severity == "major"
        else f"comparison within same activity bucket: pred={pred_comparison!r}, gt={gt_comparison!r}"
    )
    return _error(
        dimension="comparison",
        severity=severity,
        pred_value=pred_comparison,
        gt_value=gt_comparison,
        reasoning=reasoning,
    )


# ============================================================================
# measurement
# ============================================================================


def _by_category(measurements: Sequence[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for m in measurements:
        cat = m.get("category", "other")
        out.setdefault(cat, []).append(m)
    return out


def _canonical_value(measurement: dict) -> float:
    """Value rescaled to the per-category base unit (mm for size, HU for attenuation, …).

    Falls back to the raw value when the unit is missing or unknown to
    `constants.MEASUREMENT_UNIT_CONVERSION` — preserves current behaviour for
    out-of-table units while making known-unit pairs comparable.
    """
    value = float(measurement.get("value", 0))
    unit = measurement.get("unit")
    if isinstance(unit, str):
        factor = constants.MEASUREMENT_UNIT_CONVERSION.get(unit.lower())
        if factor is not None:
            return value * factor
    return value


def _size_or_ratio_rel_diff_major(pred: dict, gt: dict, threshold: float) -> bool:
    pv = _canonical_value(pred)
    gv = _canonical_value(gt)
    if gv == 0:
        return pv != 0
    return abs(pv - gv) / abs(gv) > threshold


def _crosses_cliff(pv: float, gv: float, boundaries: tuple[float, ...]) -> bool:
    """True when pred and GT fall on opposite sides of any diagnostic boundary.
    A value sitting exactly on a boundary is treated as the lower (normal) side."""
    return any((pv <= b) != (gv <= b) for b in boundaries)


def classify_measurement_asymmetry(
    pred_measurements: Sequence[dict],
    gt_measurements: Sequence[dict],
) -> list[dict]:
    """Per-category measurement comparison.

    An addition (pred-only) is minor, an omission (gt-only) or category mismatch is
    major; same-category pairs are compared against the thresholds above.
    """
    if not pred_measurements and not gt_measurements:
        return []

    if not gt_measurements:
        # Pred added measurements gt did not record → minor each
        return [
            _error(
                "measurement",
                "minor",
                pred_value=m,
                gt_value=None,
                reasoning=f"pred added a {m.get('category', 'other')} measurement gt omits",
            )
            for m in pred_measurements
        ]

    if not pred_measurements:
        # Pred omits measurements gt recorded → major each
        return [
            _error(
                "measurement",
                "major",
                pred_value=None,
                gt_value=m,
                reasoning=f"pred omits a {m.get('category', 'other')} measurement gt records",
            )
            for m in gt_measurements
        ]

    pred_by_cat = _by_category(pred_measurements)
    gt_by_cat = _by_category(gt_measurements)
    shared_cats = set(pred_by_cat) & set(gt_by_cat)

    # If there is no category overlap, emit a single category-mismatch
    # error rather than separate "added" + "omitted" entries.
    if not shared_cats:
        return [
            _error(
                "measurement",
                "major",
                pred_value=sorted(pred_by_cat.keys()),
                gt_value=sorted(gt_by_cat.keys()),
                reasoning="measurement categories differ between pred and gt",
            )
        ]

    errors: list[dict] = []

    # For categories present on only one side, emit per-category asymmetry errors.
    for cat in set(pred_by_cat) - shared_cats:
        for m in pred_by_cat[cat]:
            errors.append(
                _error(
                    "measurement",
                    "minor",
                    pred_value=m,
                    gt_value=None,
                    reasoning=f"pred added a {cat} measurement gt omits",
                )
            )
    for cat in set(gt_by_cat) - shared_cats:
        for m in gt_by_cat[cat]:
            errors.append(
                _error(
                    "measurement",
                    "major",
                    pred_value=None,
                    gt_value=m,
                    reasoning=f"pred omits a {cat} measurement gt records",
                )
            )

    # Pair by minimum total distance, not by list order: extraction may emit
    # "3.8 x 3.0 cm" one side and "3.0 x 3.8 cm" the other, where a naive `zip`
    # flags both axes as major. Brute force is fine — lists hold 1-3 items.
    for cat in shared_cats:
        pairs, extras_pred, extras_gt = _best_measurement_pairing(pred_by_cat[cat], gt_by_cat[cat])
        comparator = _MEASUREMENT_COMPARATORS.get(cat, _compare_other)
        for pm, gm in pairs:
            error = comparator(pm, gm, cat)
            if error is not None:
                errors.append(error)
        for pm in extras_pred:
            errors.append(
                _error(
                    "measurement",
                    "minor",
                    pred_value=pm,
                    gt_value=None,
                    reasoning=f"pred added an extra {cat} measurement gt omits",
                )
            )
        for gm in extras_gt:
            errors.append(
                _error(
                    "measurement",
                    "major",
                    pred_value=None,
                    gt_value=gm,
                    reasoning=f"pred omits an extra {cat} measurement gt records",
                )
            )

    return errors


def _best_measurement_pairing(
    pred_ms: Sequence[dict],
    gt_ms: Sequence[dict],
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Optimal min-distance assignment between two same-category measurement lists.

    Brute-forces all ways to align `min(len(pred), len(gt))` items between the
    two lists, picking the alignment that minimizes total canonical-value
    distance. The unmatched items on the longer side become "extras". For the
    typical n ≤ 5 measurements per category in radiology this is microseconds.
    """
    pred_list = list(pred_ms)
    gt_list = list(gt_ms)
    if not pred_list or not gt_list:
        return [], pred_list, gt_list

    if len(pred_list) <= len(gt_list):
        smaller, larger = pred_list, gt_list
        small_is_pred = True
    else:
        smaller, larger = gt_list, pred_list
        small_is_pred = False

    n_small = len(smaller)
    small_vals = [_canonical_value(m) for m in smaller]
    large_vals = [_canonical_value(m) for m in larger]
    best_cost = float("inf")
    # `best_indices` is guaranteed set by the loop: the empty-input guard above
    # ensures n_small ≥ 1, so permutations() yields at least one tuple, and any
    # finite cost beats the float('inf') sentinel on the first iteration.
    best_indices: tuple[int, ...] = ()
    for indices in permutations(range(len(larger)), n_small):
        cost = sum(abs(small_vals[i] - large_vals[indices[i]]) for i in range(n_small))
        if cost < best_cost:
            best_cost = cost
            best_indices = indices

    used = set(best_indices)
    extras_large = [larger[j] for j in range(len(larger)) if j not in used]
    if small_is_pred:
        pairs = [(smaller[i], larger[best_indices[i]]) for i in range(n_small)]
        return pairs, [], extras_large
    pairs = [(larger[best_indices[i]], smaller[i]) for i in range(n_small)]
    return pairs, extras_large, []


# ============================================================================
# Per-category measurement comparators (dispatched from classify_measurement_asymmetry)
# ============================================================================


def _compare_size(pm: dict, gm: dict, _cat: str) -> dict | None:
    if _size_or_ratio_rel_diff_major(pm, gm, _SIZE_REL_DIFF_MAJOR) and (
        abs(_canonical_value(pm) - _canonical_value(gm)) >= _SIZE_ABS_FLOOR_MM
    ):
        return _error(
            "measurement", "major", pred_value=pm, gt_value=gm, reasoning="size relative difference > 20% (≥2mm)"
        )
    return None


def _compare_ratio(pm: dict, gm: dict, _cat: str) -> dict | None:
    if _size_or_ratio_rel_diff_major(pm, gm, _RATIO_REL_DIFF_MAJOR):
        return _error("measurement", "major", pred_value=pm, gt_value=gm, reasoning="ratio relative difference > 30%")
    return None


def _compare_count(pm: dict, gm: dict, _cat: str) -> dict | None:
    if pm.get("value") != gm.get("value"):
        return _error("measurement", "major", pred_value=pm, gt_value=gm, reasoning="count value differs")
    return None


def _compare_attenuation(pm: dict, gm: dict, _cat: str) -> dict | None:
    pv = _canonical_value(pm)
    gv = _canonical_value(gm)
    if _crosses_cliff(pv, gv, _ATTENUATION_CLIFFS_HU):
        return _error(
            "measurement",
            "major",
            pred_value=pm,
            gt_value=gm,
            reasoning="attenuation crosses a tissue-characterization boundary (HU)",
        )
    if abs(pv - gv) > _ATTENUATION_ABS_DIFF_MAJOR:
        return _error("measurement", "major", pred_value=pm, gt_value=gm, reasoning="attenuation abs-diff > 20 HU")
    return None


def _compare_other(pm: dict, gm: dict, cat: str) -> dict | None:
    if pm.get("value") != gm.get("value"):
        return _error("measurement", "minor", pred_value=pm, gt_value=gm, reasoning=f"{cat} measurement value differs")
    return None


_MEASUREMENT_COMPARATORS: dict[str, Callable[[dict, dict, str], "dict | None"]] = {
    "size": _compare_size,
    "ratio": _compare_ratio,
    "count": _compare_count,
    "attenuation": _compare_attenuation,
}


# ============================================================================
# Stage 3a entry point
# ============================================================================


def compute_structured_errors(pred: dict, gt: dict) -> list[dict]:
    """Aggregate Stage 3a errors across status, comparison, measurement."""
    errors: list[dict] = []

    status_err = classify_status_conflict(
        pred.get("clinical_status", ""),
        gt.get("clinical_status", ""),
    )
    if status_err is not None:
        errors.append(status_err)

    comparison_err = classify_comparison_conflict(
        pred.get("comparison"),
        gt.get("comparison"),
    )
    if comparison_err is not None:
        errors.append(comparison_err)

    measurement_errs = classify_measurement_asymmetry(
        pred.get("measurements", []),
        gt.get("measurements", []),
    )
    errors.extend(measurement_errs)

    return errors
