"""Minimal smoke tests for the dashboard data layer.

These exercise the parts that don't require Streamlit's runtime — data loading,
index building, and per-pair match indexing. Page rendering is verified by
launching the dashboard against a populated results directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from radmatch.dashboard.build_dashboard_data import _flatten, build_report_index
from radmatch.dashboard.common.shared import PerPairMatchInfo, build_match_index


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def fake_per_report_metrics() -> dict:
    return {
        "metadata": {"series_uuid": "s1", "total_gt_findings": 4, "total_pred_findings": 3},
        "muc_counts": {"COR": 2, "PAR": 0, "INC": 1, "MIS": 1, "SPU": 0},
        "actionable_errors_total": 2,
        "clinical_safety_summary": {
            "triage_recall": 0.5,
            "actionable_recall": 0.7,
            "triage_precision": 0.6,
            "actionable_precision": 0.8,
            "triage_gt_total": 2,
            "actionable_gt_total": 5,
            "triage_pred_total": 3,
            "actionable_pred_total": 4,
            "triage_mis_count": 1,
            "triage_inc_count": 0,
            "actionable_mis_count": 1,
            "actionable_inc_count": 0,
        },
        "attribute_breakdown": {},
    }


def test_flatten_extracts_dashboard_columns(fake_per_report_metrics):
    row = _flatten(fake_per_report_metrics)
    assert row["actionable_errors"] == 2
    assert row["triage_recall"] == 0.5
    assert row["actionable_recall"] == 0.7
    assert row["triage_precision"] == 0.6
    assert row["actionable_precision"] == 0.8
    assert row["muc_cor"] == 2
    assert row["muc_inc"] == 1


def test_build_report_index_writes_one_row_per_series(tmp_path, fake_per_report_metrics):
    radmatch_dir = tmp_path / "radmatch_results"
    for series in ("s1", "s2"):
        _write(radmatch_dir / "per_report_metrics" / f"{series}.json", fake_per_report_metrics)
        # GT findings drive the per-finding attribute columns.
        _write(
            radmatch_dir / "findings_gt" / f"{series}.json",
            [
                {
                    "finding_id": f"{series}_001",
                    "clinical_status": "abnormal",
                    "comparison": "worsening",
                    "measurements": [{"value": 5, "unit": "mm", "category": "size"}],
                },
                {
                    "finding_id": f"{series}_002",
                    "clinical_status": "normal",
                    "comparison": None,
                    "measurements": [],
                },
            ],
        )

    df = build_report_index(radmatch_dir)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert set(df["report_id"]) == {"s1", "s2"}
    assert {"actionable_errors", "muc_cor", "triage_recall", "actionable_recall"}.issubset(df.columns)
    assert {"clinical_significances", "measurement_types", "comparisons"}.issubset(df.columns)
    assert df.loc[df["report_id"] == "s1", "measurement_types"].iloc[0] == ["size"]


def test_build_report_index_captures_match_scopes(tmp_path, fake_per_report_metrics):
    """The Match Scope filter reads `match_scopes` (list of distinct scopes
    seen in the report's matching/<series>.json)."""
    radmatch_dir = tmp_path / "radmatch_results"
    _write(radmatch_dir / "per_report_metrics" / "s1.json", fake_per_report_metrics)
    _write(radmatch_dir / "findings_gt" / "s1.json", [])
    _write(
        radmatch_dir / "matching" / "s1.json",
        {
            "matches": [
                {"pred_id": "p1", "gt_id": "g1", "reasoning": "", "match_scope": "direct"},
                {"pred_id": "p2", "gt_id": "g2", "reasoning": "", "match_scope": "aggregate"},
                {"pred_id": "p3", "gt_id": "g3", "reasoning": "", "match_scope": "direct"},
            ],
            "unmatched_pred": [],
            "unmatched_gt": [],
        },
    )

    df = build_report_index(radmatch_dir)
    assert df.loc[df["report_id"] == "s1", "match_scopes"].iloc[0] == ["aggregate", "direct"]


def test_build_report_index_match_scopes_empty_when_no_matching_file(tmp_path, fake_per_report_metrics):
    """Reports without a matching JSON (or with no matches) get an empty list."""
    radmatch_dir = tmp_path / "radmatch_results"
    _write(radmatch_dir / "per_report_metrics" / "s1.json", fake_per_report_metrics)
    _write(radmatch_dir / "findings_gt" / "s1.json", [])

    df = build_report_index(radmatch_dir)
    assert list(df.loc[df["report_id"] == "s1", "match_scopes"].iloc[0]) == []


def test_build_match_index_reclassifies_PAR_with_major_to_INC():
    matching = {
        "matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": "same"}],
        "unmatched_pred": ["p2"],
        "unmatched_gt": ["g2"],
    }
    attr_errors = {
        "muc_records": [
            {
                "pred_id": "p1",
                "gt_id": "g1",
                "muc_category": "PAR",
                "structured_errors": [],
                "text_errors": [{"dimension": "location", "severity": "major"}],
            }
        ],
        "structured_errors_per_pair": [[]],
        "text_errors_per_pair": [[{"dimension": "location", "severity": "major"}]],
    }
    gt_idx, pred_idx = build_match_index(matching, attr_errors)
    # PAR with major → INC in the effective taxonomy
    assert gt_idx["g1"].category == "INC"
    assert gt_idx["g1"].counterparts[0].counterpart_id == "p1"
    assert pred_idx["p1"].category == "INC"
    assert pred_idx["p1"].counterparts[0].text_errors[0]["dimension"] == "location"
    assert gt_idx["g2"].category == "MIS"
    assert pred_idx["p2"].category == "SPU"


def test_build_match_index_keeps_PAR_when_only_minor_errors():
    matching = {
        "matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": "same"}],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    attr_errors = {
        "muc_records": [
            {
                "pred_id": "p1",
                "gt_id": "g1",
                "muc_category": "PAR",
                "structured_errors": [],
                "text_errors": [{"dimension": "location", "severity": "minor"}],
            }
        ],
        "structured_errors_per_pair": [[]],
        "text_errors_per_pair": [[{"dimension": "location", "severity": "minor"}]],
    }
    gt_idx, _ = build_match_index(matching, attr_errors)
    # PAR with only minor errors stays PAR in the effective taxonomy.
    assert gt_idx["g1"].category == "PAR"


def test_build_match_index_captures_match_scope():
    """`match_scope` from Stage 2 matching flows into the per-counterpart info.
    Unmatched findings have an empty counterparts list."""
    matching = {
        "matches": [
            {"pred_id": "p1", "gt_id": "g1", "reasoning": "", "match_scope": "direct"},
            {"pred_id": "p2", "gt_id": "g2", "reasoning": "", "match_scope": "direct"},
        ],
        "unmatched_pred": ["p3"],
        "unmatched_gt": ["g3"],
    }
    gt_idx, pred_idx = build_match_index(matching, None)
    assert gt_idx["g1"].counterparts[0].match_scope == "direct"
    assert pred_idx["p1"].counterparts[0].match_scope == "direct"
    assert gt_idx["g3"].counterparts == []
    assert pred_idx["p3"].counterparts == []


def test_build_match_index_aggregates_multi_bind_counterparts():
    """Under 1:N matching the pred has multiple counterparts; the card
    category becomes the best-of-pair-categories (COR > PAR > INC)."""
    matching = {
        "matches": [
            {"pred_id": "p1", "gt_id": "g1", "reasoning": "", "match_scope": "aggregate"},
            {"pred_id": "p1", "gt_id": "g2", "reasoning": "", "match_scope": "aggregate"},
            {"pred_id": "p1", "gt_id": "g3", "reasoning": "", "match_scope": "aggregate"},
        ],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    attr = {
        "muc_records": [
            {"pred_id": "p1", "gt_id": "g1", "muc_category": "COR", "structured_errors": [], "text_errors": []},
            {
                "pred_id": "p1",
                "gt_id": "g2",
                "muc_category": "PAR",
                "structured_errors": [],
                "text_errors": [{"dimension": "location", "severity": "major"}],
            },
            {"pred_id": "p1", "gt_id": "g3", "muc_category": "COR", "structured_errors": [], "text_errors": []},
        ],
        "structured_errors_per_pair": [[], [], []],
        "text_errors_per_pair": [[], [{"dimension": "location", "severity": "major"}], []],
    }
    gt_idx, pred_idx = build_match_index(matching, attr)
    assert len(pred_idx["p1"].counterparts) == 3
    assert {c.counterpart_id for c in pred_idx["p1"].counterparts} == {"g1", "g2", "g3"}
    # Best-of: COR beats the INC (reclassified from PAR+major); card shows COR.
    assert pred_idx["p1"].category == "COR"
    # Each GT keeps its own per-pair category.
    assert gt_idx["g1"].category == "COR"
    assert gt_idx["g2"].category == "INC"
    assert gt_idx["g3"].category == "COR"


def test_build_match_index_handles_empty_matching():
    gt_idx, pred_idx = build_match_index({}, None)
    assert gt_idx == {}
    assert pred_idx == {}


def test_per_pair_match_info_default_for_unmatched_gt():
    info = PerPairMatchInfo("MIS", [])
    assert info.category == "MIS"
    assert info.counterparts == []
