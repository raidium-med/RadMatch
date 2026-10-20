"""Stage 3a — deterministic comparators over the structured fields of a matched pair.

`clinical_status` (inversion → INC downstream), `comparison` (cross-bucket → major)
and `measurement` (per-category thresholds). No LLM call; the free-text dimensions
are Stage 3b's job (`scoring.inference`).
"""

from __future__ import annotations

import re
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
    one-sided mention (one side None) → minor, except a pred that drops an
    ACTIVE gt comparison, which misleads about disease activity exactly as
    much as contradicting it → major.
    """
    if pred_comparison == gt_comparison:
        return None
    if pred_comparison is None or gt_comparison is None:
        dropped_active = pred_comparison is None and gt_comparison in constants.ACTIVE_COMPARISONS
        return _error(
            dimension="comparison",
            severity="major" if dropped_active else "minor",
            pred_value=pred_comparison,
            gt_value=gt_comparison,
            reasoning="pred drops an active gt comparison" if dropped_active else "one-sided comparison mention",
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


_SMALL_SIZE_WORDS = re.compile(r"\b(tiny|punctate|millimetric|micro-?nodul\w*|sub-?centimet\w*|infra-?centimet\w*)")
_SMALL_SIZE_BOUND_MM = 6.0  # Fleischner: below 6 mm a nodule needs no routine follow-up
_UPPER_BOUND = re.compile(r"(?:\bsub-?|<|≤|\bless than|\bunder|\bbelow|\bsmaller than)\s*(\d+(?:\.\d+)?)\s*(mm|cm)\b")


def _upper_bounds_mm(finding: dict) -> list[float]:
    """Sizes the finding text gives only as an upper bound ("sub-6 mm", "< 5 mm")."""
    text = str(finding.get("text") or "").lower()
    return [float(v) * (10.0 if u == "cm" else 1.0) for v, u in _UPPER_BOUND.findall(text)]


def _size_class_mm(finding: dict) -> float | None:
    """The size a finding states without a number: its smallest upper bound, or a small-size word (< 6 mm)."""
    bounds = _upper_bounds_mm(finding)
    if bounds:
        return min(bounds)
    text = str(finding.get("text") or "").lower()
    return _SMALL_SIZE_BOUND_MM if _SMALL_SIZE_WORDS.search(text) else None


def _omission_severity(
    category: str,
    size_given_elsewhere: bool = False,
    gt: dict | None = None,
    pred_size_class: float | None = None,
    cliffs: tuple[float, ...] | None = None,
) -> str:
    """A reference size the pred does not give at all is major, unless the pred gives a size class the reference
    value falls under ("tiny nodule" vs 4 mm) or the value is below the structure's first decision threshold (a
    4 mm nodule, a 7 mm node); any other omission is minor."""
    if category != "size" or size_given_elsewhere:
        return "minor"
    if gt is not None and cliffs and _size_unit_kind(gt) == "length" and _canonical_value(gt) < min(cliffs):
        return "minor"
    if gt is not None and pred_size_class is not None and _size_unit_kind(gt) == "length":
        return "minor" if _canonical_value(gt) < pred_size_class else "major"
    return "major"


# Size decision thresholds (mm) by structure, read from the finding texts; a value on a threshold falls below it.
_SIZE_CLIFFS_MM: tuple[tuple[re.Pattern, tuple[float, ...]], ...] = (
    (re.compile(r"(?<!lymph )\bnodul|\bnodule"), (5.95, 8.0)),  # lung nodule, Fleischner < 6 / 6-8 / > 8 mm
    (re.compile(r"\blymph|\bnodes?\b|adenopath"), (10.0,)),  # short axis > 10 mm is enlarged
    (re.compile(r"abdominal aort|infrarenal aort|\baaa\b"), (29.95, 54.95)),  # aneurysm >= 3 cm, repair >= 5.5 cm
    (re.compile(r"aort"), (39.95, 54.95)),  # thoracic aorta dilated >= 4 cm, surgery >= 5.5 cm
    (re.compile(r"\bsplen|\bspleen"), (130.0,)),  # splenomegaly > 13 cm
    (
        re.compile(r"common bile duct|\bcbd\b|common duct|choledoch"),
        (6.0,),
    ),  # dilated > 6 mm (> 10 mm, cholecystectomy)
    (re.compile(r"pancreatic duct|wirsung"), (3.0,)),  # dilated > 3 mm
)
_NON_LUNG_NODULE = re.compile(
    r"thyroid|liver|hepatic|renal|kidney|adrenal|breast|lymph|splen|pancrea|skin|subcutaneous"
)


def _size_cliffs(pred: dict, gt: dict) -> tuple[float, ...] | None:
    """The decision thresholds of the structure the two findings describe (the gt text first), if any."""
    for finding in (gt, pred):
        text = str(finding.get("text") or "").lower()
        for i, (pattern, cliffs) in enumerate(_SIZE_CLIFFS_MM):
            if not pattern.search(text) or (i == 0 and _NON_LUNG_NODULE.search(text)):
                continue
            if i == 5 and "cholecystectomy" in text:
                return (10.0,)
            return cliffs
    return None


def _compare_size_with_cliffs(pm: dict, gm: dict, cliffs: tuple[float, ...]) -> dict | None:
    """A size difference that crosses a decision threshold of the structure is major; within one class it is minor
    when large (> 20 % and >= 2 mm), else no error."""
    if _size_unit_kind(pm) != "length" or _size_unit_kind(gm) != "length":
        return _compare_size(pm, gm, "size")
    pv, gv = _canonical_value(pm), _canonical_value(gm)
    if _crosses_cliff(pv, gv, cliffs):
        return _error("measurement", "major", pred_value=pm, gt_value=gm, reasoning="size crosses a decision threshold")
    if _size_or_ratio_rel_diff_major(pm, gm, _SIZE_REL_DIFF_MAJOR) and abs(pv - gv) >= _SIZE_ABS_FLOOR_MM:
        return _error("measurement", "minor", pred_value=pm, gt_value=gm, reasoning="size differs within one class")
    return None


def _within_bound(value: dict, bound_side: dict, bounds: list[float]) -> bool:
    """`bound_side` is a size its finding gives only as an upper bound, and `value` falls under it."""
    if _size_unit_kind(value) != "length" or _size_unit_kind(bound_side) != "length":
        return False
    b = _canonical_value(bound_side)
    return any(abs(b - x) < 1e-6 for x in bounds) and _canonical_value(value) < b


def _align_categories(pred_measurements: Sequence[dict], gt_measurements: Sequence[dict]) -> list[dict]:
    """Pred measurements, each relabelled with the category of a gt measurement carrying the same value and unit:
    the two sides label categories independently, so a label disagreement on one quantity is not a difference."""
    out = []
    for m in pred_measurements:
        same = next(
            (g for g in gt_measurements if g.get("value") == m.get("value") and g.get("unit") == m.get("unit")), None
        )
        out.append({**m, "category": same.get("category", "other")} if same else m)
    return out


def classify_measurement_asymmetry(
    pred_measurements: Sequence[dict],
    gt_measurements: Sequence[dict],
    size_given_elsewhere: bool = False,
    pred_size_class: float | None = None,
    pred_bounds: Sequence[float] = (),
    gt_bounds: Sequence[float] = (),
    size_cliffs: tuple[float, ...] | None = None,
) -> list[dict]:
    """Per-category measurement comparison.

    An addition (pred-only) is minor. An omission (gt-only) is minor, except a size
    when the pred gives no size at all, which is major; a missing extra dimension
    stays minor, and so does a size another pred of the same match group gives
    (`size_given_elsewhere`), and a gt size under the size class the pred states without a number
    (`pred_size_class`, mm: "tiny", "sub-6 mm"). Same-category pairs are compared against the thresholds
    above, except a size one side gives only as an upper bound (`pred_bounds` / `gt_bounds`, mm) that the other
    side's value falls under; a pred measurement with the value and unit of a gt one takes its category.
    """
    if not pred_measurements and not gt_measurements:
        return []
    pred_measurements = _align_categories(pred_measurements, gt_measurements)

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
        return [
            _error(
                "measurement",
                _omission_severity(m.get("category", "other"), size_given_elsewhere, m, pred_size_class, size_cliffs),
                pred_value=None,
                gt_value=m,
                reasoning=f"pred omits a {m.get('category', 'other')} measurement gt records",
            )
            for m in gt_measurements
        ]

    pred_by_cat = _by_category(pred_measurements)
    gt_by_cat = _by_category(gt_measurements)
    shared_cats = set(pred_by_cat) & set(gt_by_cat)

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
                    _omission_severity(cat, size_given_elsewhere, m, pred_size_class, size_cliffs),
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
            if cat == "size" and (_within_bound(gm, pm, pred_bounds) or _within_bound(pm, gm, gt_bounds)):
                continue
            error = (
                _compare_size_with_cliffs(pm, gm, size_cliffs)
                if cat == "size" and size_cliffs
                else comparator(pm, gm, cat)
            )
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
                    "minor",
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


def _size_unit_kind(measurement: dict) -> str | None:
    """`length` / `volume` for a known unit, the unit itself for an unknown one, None when there is no unit."""
    unit = measurement.get("unit")
    if not isinstance(unit, str) or not unit:
        return None
    return constants.MEASUREMENT_SIZE_UNIT_KIND.get(unit.lower(), unit.lower())


def _compare_size(pm: dict, gm: dict, _cat: str) -> dict | None:
    pk, gk = _size_unit_kind(pm), _size_unit_kind(gm)
    if pk and gk and pk != gk:
        return _error(
            "measurement", "minor", pred_value=pm, gt_value=gm, reasoning="sizes given in units that cannot be compared"
        )
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


_CYST_ORGAN = re.compile(r"\b(renal|kidneys?|hepatic|liver|splenic|spleen|cortical|parapelvic)\b")
_COMPLEX_CYST = re.compile(
    r"\b(complex|septat\w*|enhanc\w*|solid|mural|nodul\w*|thick\w*|hyperdens\w*|hemorrhag\w*|calcif\w*"
    r"|bosniak (?:iif|2f|iii|3|iv|4))"
)
_NEGATION = re.compile(r"\b(no|non|without)[- ](?:\w+[- ]){0,2}$")


def _is_simple_cyst(finding: dict) -> bool:
    """A renal, hepatic or splenic cyst with no complex feature (a negated one, "non-enhancing", does not count)."""
    text = str(finding.get("text") or "").lower()
    if not re.search(r"\bcysts?\b", text) or not _CYST_ORGAN.search(text):
        return False
    return all(_NEGATION.search(text[: m.start()]) for m in _COMPLEX_CYST.finditer(text))


def _normalized_text(finding: dict) -> str:
    return re.sub(r"\W+", " ", str(finding.get("text") or "").lower()).strip()


_NEGATIONS = {"no", "not", "without", "absent", "negative", "free", "none", "resolved"}
_FILLER = set("the a an of in is are and with to at on evidence discrete seen noted".split())


def _near_identical(pred: dict, gt: dict) -> bool:
    """The same sentence up to filler words (negations kept): >= 80% shared words. Such a pair cannot invert status;
    a disagreeing status label is extraction noise."""
    a = set(_normalized_text(pred).split()) - _FILLER
    b = set(_normalized_text(gt).split()) - _FILLER
    return bool(a and b) and a & _NEGATIONS == b & _NEGATIONS and len(a & b) / len(a | b) >= 0.8


def compute_structured_errors(pred: dict, gt: dict, size_given_elsewhere: bool = False) -> list[dict]:
    """Aggregate Stage 3a errors across status, comparison, measurement. `size_given_elsewhere`: another pred
    matched to the same gt gives a size, so this pred omitting one is not an omission of the group. Two findings
    with the same text cannot invert status: a label disagreement on one sentence is extraction noise."""
    errors: list[dict] = []

    same_text = _near_identical(pred, gt)
    status_err = classify_status_conflict(
        pred.get("clinical_status", ""),
        gt.get("clinical_status", ""),
    )
    if status_err is not None and not same_text:
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
        size_given_elsewhere=size_given_elsewhere,
        pred_size_class=_size_class_mm(pred),
        pred_bounds=_upper_bounds_mm(pred),
        gt_bounds=_upper_bounds_mm(gt),
        size_cliffs=_size_cliffs(pred, gt),
    )
    if _is_simple_cyst(pred) and _is_simple_cyst(gt):  # no follow-up at any size (ACR incidental-findings papers)
        measurement_errs = [{**e, "severity": "minor"} for e in measurement_errs]
    errors.extend(measurement_errs)

    return errors
