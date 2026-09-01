"""Stage 1 — extraction utilities + finding validation/normalization."""

from __future__ import annotations

import pytest

from radmatch import constants, io
from radmatch.finding_extraction import extract_utils

# ============================================================================
# create_output_directories
# ============================================================================


def test_create_output_directories(tmp_path):
    gt_dir, pred_dir = extract_utils.create_output_directories(tmp_path / "output")
    assert gt_dir.exists() and gt_dir.name == constants.FINDINGS_GT_DIR
    assert pred_dir.exists() and pred_dir.name == constants.FINDINGS_PRED_DIR


def test_create_output_directories_idempotent(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / constants.FINDINGS_GT_DIR).mkdir(parents=True)
    extract_utils.create_output_directories(output_dir)
    assert (output_dir / constants.FINDINGS_PRED_DIR).exists()


# ============================================================================
# extract_findings_list — normalisation + ID generation
# ============================================================================


def test_extract_findings_list_assigns_sequential_ids():
    raw = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    out = extract_utils.extract_findings_list(raw, "abc")
    assert [f["finding_id"] for f in out] == ["abc_001", "abc_002", "abc_003"]


@pytest.mark.parametrize(
    "raw_status, expected",
    [
        pytest.param("abnormal", "abnormal", id="valid-abnormal"),
        pytest.param("normal", "normal", id="valid-normal"),
        pytest.param("kinda_weird", constants.DEFAULT_CLINICAL_STATUS, id="invalid-coerced"),
        pytest.param(None, constants.DEFAULT_CLINICAL_STATUS, id="missing-default"),
    ],
)
def test_extract_findings_list_normalises_status(raw_status, expected):
    raw = [{"text": "x"} if raw_status is None else {"text": "x", "clinical_status": raw_status}]
    out = extract_utils.extract_findings_list(raw, "s")
    assert out[0]["clinical_status"] == expected


@pytest.mark.parametrize(
    "raw_comp, expected",
    [
        pytest.param("improving", "improving", id="valid"),
        pytest.param("invalid_value", None, id="invalid-coerced-none"),
        pytest.param(None, None, id="missing-stays-none"),
    ],
)
def test_extract_findings_list_normalises_comparison(raw_comp, expected):
    raw = [{"text": "x"} if raw_comp is None else {"text": "x", "comparison": raw_comp}]
    out = extract_utils.extract_findings_list(raw, "s")
    assert out[0]["comparison"] == expected


def test_extract_findings_list_normalises_measurements():
    raw = [
        {"text": "ok", "measurements": [{"value": "5", "category": "size"}, {"value": "1", "category": "bogus"}]},
        {"text": "wrong-type", "measurements": "not_a_list"},
    ]
    out = extract_utils.extract_findings_list(raw, "s")
    assert out[0]["measurements"][1]["category"] == constants.DEFAULT_MEASUREMENT_CATEGORY
    assert out[1]["measurements"] == []


def test_extract_findings_list_skips_non_dict_items():
    raw = [{"text": "ok"}, "garbage", None, 42, {"text": "also ok"}]
    out = extract_utils.extract_findings_list(raw, "s")
    assert [f["text"] for f in out] == ["ok", "also ok"]


def test_extract_findings_list_raises_on_non_list():
    with pytest.raises(ValueError):
        extract_utils.extract_findings_list({"not": "a list"}, "s")


# ============================================================================
# validate_and_normalize_finding
# ============================================================================


def _base_finding(**overrides) -> dict:
    finding = {
        "finding_id": "x_1",
        "text": "Test finding.",
        "clinical_status": "abnormal",
        "clinical_significance": "urgent",
        "comparison": None,
        "measurements": [],
    }
    finding.update(overrides)
    return finding


def test_validate_passes_through_valid_finding():
    out = extract_utils.validate_and_normalize_finding(_base_finding())
    assert out["clinical_significance"] == "urgent"
    assert out["clinical_status"] == "abnormal"


@pytest.mark.parametrize(
    "field, bad_value, default_const",
    [
        pytest.param("clinical_significance", "super_critical", constants.DEFAULT_CLINICAL_SIGNIFICANCE, id="sig"),
        pytest.param("clinical_status", "kinda_weird", constants.DEFAULT_CLINICAL_STATUS, id="status"),
    ],
)
def test_validate_invalid_enum_coerces_to_default_with_warning(field, bad_value, default_const, caplog):
    finding = _base_finding(**{field: bad_value})
    with caplog.at_level("WARNING", logger="radmatch.finding_extraction.extract_utils"):
        out = extract_utils.validate_and_normalize_finding(finding)
    assert out[field] == default_const
    assert any(bad_value in rec.message for rec in caplog.records)


def test_validate_invalid_comparison_coerces_to_none():
    out = extract_utils.validate_and_normalize_finding(_base_finding(comparison="kinda_better"))
    assert out["comparison"] is None


def test_validate_does_not_mutate_input():
    original = _base_finding()
    del original["clinical_significance"]
    snapshot = dict(original)
    extract_utils.validate_and_normalize_finding(original)
    assert original == snapshot


def test_validate_preserves_status_significance_orthogonality():
    """Normal + critical is a valid combination (rule-out scenario)."""
    finding = _base_finding(clinical_status="normal", clinical_significance="critical")
    out = extract_utils.validate_and_normalize_finding(finding)
    assert out["clinical_status"] == "normal"
    assert out["clinical_significance"] == "critical"


# ============================================================================
# copy_findings_from_directory
# ============================================================================


def test_copy_findings_skips_existing_and_returns_count(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    payload = [{"finding_id": "x_1", "text": "f", "clinical_status": "abnormal", "measurements": []}]
    io.save_json(payload, source / "a.json")
    io.save_json(payload, source / "b.json")
    io.save_json(payload, target / "a.json")  # already in target → skipped

    copied = extract_utils.copy_findings_from_directory(source, target)
    assert copied == 1
    assert (target / "b.json").exists()


def test_copy_findings_missing_source_returns_zero(tmp_path):
    assert extract_utils.copy_findings_from_directory(tmp_path / "nope", tmp_path / "t") == 0
