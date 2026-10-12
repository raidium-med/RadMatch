"""The dashboard pages execute without raising, against a minimal results directory.

Streamlit pages are scripts, not modules: they only run when the app runs, so an
`ImportError` or a bad key path in one is invisible to ordinary import-based tests and to
an HTTP status check (the page body runs over a websocket, so the shell still returns
200). `AppTest` executes the script for real and surfaces any exception.

This is what guards the packaged layout — the pages live inside `radmatch.dashboard`, and
their imports have to resolve from site-packages, not from a working directory that
happens to have `common/` next to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="dashboard extra not installed")

from streamlit.testing.v1 import AppTest  # noqa: E402

import radmatch.dashboard as dashboard_pkg  # noqa: E402
from radmatch.dashboard.build_dashboard_data import build_report_index  # noqa: E402

DASHBOARD_DIR = Path(dashboard_pkg.__file__).parent
PAGE_SCRIPTS = [
    DASHBOARD_DIR / "Home.py",
    DASHBOARD_DIR / "pages" / "1-Results_Explorer.py",
    DASHBOARD_DIR / "pages" / "2-Performance_Summary.py",
]


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _tier_block(errors=0, fn=0, recall=1.0, precision=1.0, gt_total=1, pred_total=1, n_reports=None) -> dict:
    """A `tiers.<name>` block; MIS-only FN and SPU-only FP keep the sub-splits consistent."""
    block = {
        "significance": ["critical"],
        "errors_total": errors,
        "fn_total": fn,
        "fp_total": errors - fn,
        "fn_mis_total": fn,
        "fn_inc_total": 0,
        "fp_spu_total": errors - fn,
        "fp_inc_total": 0,
        "findings_total": max(errors, gt_total),
        "errors_per_finding": errors / max(errors, gt_total),
        "recall": recall,
        "recall_hits": round(recall * gt_total),
        "gt_total": gt_total,
        "precision": precision,
        "precision_hits": round(precision * pred_total),
        "pred_total": pred_total,
    }
    if n_reports:
        per_report = {f"{k}_per_report": block[f"{k}_total"] / n_reports for k in ("errors", "fn", "fp")}
        block = {**per_report, **block}
    return block


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    """A one-report results directory in the layout the dashboard expects."""
    root = tmp_path / "run"
    radmatch_dir = root / "radmatch_results"

    gt = [
        {
            "finding_id": "gt_001",
            "text": "Small left pleural effusion.",
            "clinical_status": "abnormal",
            "clinical_significance": "urgent",
            "comparison": None,
            "measurements": [],
        }
    ]
    pred = [
        {
            "finding_id": "pred_001",
            "text": "Small effusion on the left.",
            "clinical_status": "abnormal",
            "clinical_significance": "urgent",
            "comparison": None,
            "measurements": [],
        }
    ]
    _write(radmatch_dir / "findings_gt" / "s1.json", gt)
    _write(radmatch_dir / "findings_pred" / "s1.json", pred)
    _write(
        radmatch_dir / "matching" / "s1.json",
        {
            "matches": [{"pred_id": "pred_001", "gt_id": "gt_001", "reasoning": "same finding"}],
            "unmatched_pred": [],
            "unmatched_gt": [],
        },
    )
    _write(
        radmatch_dir / "attribute_errors" / "s1.json",
        {
            "matches": [{"pred_id": "pred_001", "gt_id": "gt_001"}],
            "structured_errors_per_pair": [[]],
            "text_errors_per_pair": [[]],
            "muc_records": [{"pred_id": "pred_001", "gt_id": "gt_001", "category": "COR", "errors": []}],
        },
    )
    _write(
        radmatch_dir / "per_report_metrics" / "s1.json",
        {
            "metadata": {"series_uuid": "s1", "total_gt_findings": 1, "total_pred_findings": 1},
            "muc_counts": {"COR": 1, "PAR": 0, "INC": 0, "MIS": 0, "SPU": 0},
            "tiers": {tier: _tier_block() for tier in ("actionable", "triage", "critical")},
            "attribute_breakdown": {},
        },
    )
    _write(
        radmatch_dir / "metrics_summary.json",
        {
            "metadata": {"n_reports": 1, "total_gt_findings": 1, "total_pred_findings": 1},
            "tiers": {tier: _tier_block(n_reports=1) for tier in ("actionable", "triage", "critical")},
            "muc_counts": {"COR": 1, "PAR": 0, "INC": 0, "MIS": 0, "SPU": 0},
            "attribute_breakdown": {},
            "subsets": {},
        },
    )
    build_report_index(radmatch_dir)
    return root


@pytest.mark.parametrize("script", PAGE_SCRIPTS, ids=lambda p: p.name)
def test_page_runs_without_exception(script: Path, results_dir: Path) -> None:
    app = AppTest.from_file(str(script), default_timeout=120)
    app.query_params["results_dir"] = str(results_dir)
    app.run()

    assert not app.exception, [str(e.value) for e in app.exception]
    assert app.markdown, f"{script.name} rendered nothing"
