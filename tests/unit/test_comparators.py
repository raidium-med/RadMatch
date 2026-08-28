"""Stage 3a — deterministic comparators (status, comparison, measurement)."""

from __future__ import annotations

import pytest

from radmatch.scoring import comparators


def _m(value, unit, category):
    return {"value": value, "unit": unit, "category": category}


# ============================================================================
# classify_status_conflict
# ============================================================================


@pytest.mark.parametrize(
    "pred, gt, expect_inc",
    [
        pytest.param("normal", "abnormal", True, id="pred-normal-gt-abnormal"),
        pytest.param("abnormal", "normal", True, id="pred-abnormal-gt-normal"),
        pytest.param("abnormal", "abnormal", False, id="same-abnormal"),
        pytest.param("normal", "normal", False, id="same-normal"),
    ],
)
def test_status_conflict(pred, gt, expect_inc):
    err = comparators.classify_status_conflict(pred, gt)
    if expect_inc:
        assert err["dimension"] == "clinical_status"
        assert err["severity"] == "major"
        assert err["triggers_inc"] is True
    else:
        assert err is None


# ============================================================================
# classify_comparison_conflict
# ============================================================================


@pytest.mark.parametrize(
    "pred, gt, expected_severity",
    [
        pytest.param("worsening", "improving", "major", id="cross-bucket-active-vs-benign"),
        pytest.param("stable", "worsening", "major", id="cross-bucket-benign-vs-active"),
        pytest.param("stable", "improving", "minor", id="same-bucket-benign"),
        pytest.param("worsening", "new", "minor", id="same-bucket-active"),
        pytest.param(None, "stable", "minor", id="pred-none-gt-mention"),
        pytest.param("stable", None, "minor", id="gt-none-pred-mention"),
    ],
)
def test_comparison_conflict(pred, gt, expected_severity):
    err = comparators.classify_comparison_conflict(pred, gt)
    assert err["severity"] == expected_severity


@pytest.mark.parametrize("value", ["stable", None])
def test_comparison_no_conflict(value):
    assert comparators.classify_comparison_conflict(value, value) is None


# ============================================================================
# classify_measurement_asymmetry
# ============================================================================


@pytest.mark.parametrize(
    "pred_m, gt_m, expected_count, expected_severity",
    [
        pytest.param([], [], 0, None, id="both-empty"),
        pytest.param([_m(10, "mm", "size")], [_m(10.5, "mm", "size")], 0, None, id="size-within-20pct-threshold"),
        pytest.param([_m(7, "mm", "size")], [_m(9, "mm", "size")], 1, "major", id="size-above-20pct-threshold"),
        # Tiny structures: +50% relative but only 1mm absolute — below the 2mm
        # reproducibility floor, so no error (was a false positive before).
        pytest.param([_m(2, "mm", "size")], [_m(3, "mm", "size")], 0, None, id="size-tiny-below-abs-floor"),
        pytest.param([_m(2, "mm", "size")], [_m(5, "mm", "size")], 1, "major", id="size-tiny-above-abs-floor"),
        pytest.param([_m(7, "mm", "size")], [], 1, "minor", id="pred-has-gt-omits"),
        pytest.param([], [_m(7, "mm", "size")], 1, "major", id="gt-has-pred-omits"),
        pytest.param([_m(2, None, "count")], [_m(3, None, "count")], 1, "major", id="count-different"),
        pytest.param([_m(3, None, "count")], [_m(3, None, "count")], 0, None, id="count-same"),
        pytest.param(
            [_m(20, "hu", "attenuation")],
            [_m(50, "hu", "attenuation")],
            1,
            "major",
            id="attenuation-above-20hu",
        ),
        # Both clearly soft-tissue (> 20 HU), 15 HU apart, no cliff between → no error.
        pytest.param(
            [_m(30, "hu", "attenuation")],
            [_m(45, "hu", "attenuation")],
            0,
            None,
            id="attenuation-within-threshold-no-cliff",
        ),
        # Sub-20-HU crossings the flat rule used to miss: 8↔18 crosses the 10-HU
        # adenoma cut-off, 18↔22 crosses the 20-HU simple-fluid cut-off.
        pytest.param(
            [_m(8, "hu", "attenuation")],
            [_m(18, "hu", "attenuation")],
            1,
            "major",
            id="attenuation-crosses-10hu-cliff",
        ),
        pytest.param(
            [_m(18, "hu", "attenuation")],
            [_m(22, "hu", "attenuation")],
            1,
            "major",
            id="attenuation-crosses-20hu-cliff",
        ),
        pytest.param([_m(7, "mm", "size")], [_m(7, None, "count")], 1, "major", id="category-mismatch"),
    ],
)
def test_measurement_asymmetry(pred_m, gt_m, expected_count, expected_severity):
    errs = comparators.classify_measurement_asymmetry(pred_m, gt_m)
    assert len(errs) == expected_count
    if expected_count:
        assert errs[0]["severity"] == expected_severity
        assert errs[0]["dimension"] == "measurement"


@pytest.mark.parametrize(
    "pred_m, gt_m, id_",
    [
        pytest.param([_m(1, "cm", "size")], [_m(10, "mm", "size")], "size-cm-vs-mm"),
        pytest.param([_m(0.1, "m", "size")], [_m(100, "mm", "size")], "size-m-vs-mm"),
        pytest.param([_m(1, "inch", "size")], [_m(25.4, "mm", "size")], "size-inch-vs-mm"),
    ],
)
def test_measurement_asymmetry_normalises_size_units(pred_m, gt_m, id_):
    """Clinically identical size measurements expressed in different units must NOT
    produce a major error — the comparator converts to a canonical base (mm) first."""
    assert comparators.classify_measurement_asymmetry(pred_m, gt_m) == []


@pytest.mark.parametrize(
    "pv, gv, expected",
    [
        pytest.param(8.0, 18.0, True, id="straddles-10"),
        pytest.param(18.0, 22.0, True, id="straddles-20"),
        pytest.param(30.0, 45.0, False, id="same-side-above-all"),
        pytest.param(12.0, 12.0, False, id="equal-never-crosses"),
        pytest.param(10.0, 9.0, False, id="boundary-value-counts-as-lower-side"),
        pytest.param(10.0, 11.0, True, id="boundary-vs-above-crosses"),
    ],
)
def test_crosses_cliff(pv, gv, expected):
    assert comparators._crosses_cliff(pv, gv, (-10.0, 10.0, 20.0)) is expected


def test_measurement_asymmetry_normalises_attenuation_units():
    """Attenuation comparators should treat `hu` and `hounsfield` as equivalent."""
    assert (
        comparators.classify_measurement_asymmetry(
            [_m(50, "hu", "attenuation")],
            [_m(55, "hounsfield", "attenuation")],
        )
        == []
    )


def test_measurement_asymmetry_compares_every_pair_in_shared_category():
    """Multi-dimensional lesions ('3.8 x 3.0 cm') emit two size measurements per side;
    every pair must be compared, not just [0]."""
    pred = [_m(3.8, "cm", "size"), _m(1.0, "cm", "size")]  # second dim wrong
    gt = [_m(3.8, "cm", "size"), _m(3.0, "cm", "size")]
    errs = comparators.classify_measurement_asymmetry(pred, gt)
    assert len(errs) == 1
    assert errs[0]["severity"] == "major"
    assert errs[0]["dimension"] == "measurement"


def test_measurement_asymmetry_handles_extra_measurement_on_pred_side():
    """Pred adding a third size dimension that GT omits → minor error per extra."""
    pred = [_m(3.8, "cm", "size"), _m(3.0, "cm", "size"), _m(2.1, "cm", "size")]
    gt = [_m(3.8, "cm", "size"), _m(3.0, "cm", "size")]
    errs = comparators.classify_measurement_asymmetry(pred, gt)
    assert len(errs) == 1
    assert errs[0]["severity"] == "minor"


def test_measurement_asymmetry_handles_extra_measurement_on_gt_side():
    """Pred dropping a size dimension GT records → major error per missing."""
    pred = [_m(3.8, "cm", "size")]
    gt = [_m(3.8, "cm", "size"), _m(3.0, "cm", "size")]
    errs = comparators.classify_measurement_asymmetry(pred, gt)
    assert len(errs) == 1
    assert errs[0]["severity"] == "major"


# ============================================================================
# compute_structured_errors — aggregates all three dimensions
# ============================================================================


def test_compute_structured_errors_aggregates_all_dimensions():
    pred = {"clinical_status": "normal", "comparison": "stable", "measurements": []}
    gt = {
        "clinical_status": "abnormal",
        "comparison": "worsening",
        "measurements": [_m(7, "mm", "size")],
    }
    dims = {e["dimension"] for e in comparators.compute_structured_errors(pred, gt)}
    assert dims == {"clinical_status", "comparison", "measurement"}


def test_compute_structured_errors_identical_pair_is_empty():
    f = {
        "clinical_status": "abnormal",
        "comparison": "stable",
        "measurements": [_m(7, "mm", "size")],
    }
    assert comparators.compute_structured_errors(f, f) == []
