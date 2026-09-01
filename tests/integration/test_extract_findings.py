"""Stage 1 integration — finding extraction workflow on disk."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from radmatch import constants, io
from radmatch.finding_extraction import extract_findings

if TYPE_CHECKING:
    from pathlib import Path


def _report(path: Path, series: str, content: str) -> None:
    (path / f"{series}.txt").write_text(content, encoding="utf-8")


def _mock_response(findings: list[dict]) -> str:
    # Stage 1 expects a json_schema-shaped object root with a `findings` key.
    return json.dumps({"findings": findings})


@pytest.fixture
def workdir(tmp_path):
    """Standard workspace for Stage 1 integration: reports_gt/, reports_pred/, output/."""
    (tmp_path / "reports_gt").mkdir()
    (tmp_path / "reports_pred").mkdir()
    return {
        "gt": tmp_path / "reports_gt",
        "pred": tmp_path / "reports_pred",
        "out": tmp_path / "output",
        "results": tmp_path / "output" / constants.RESULTS_DIR,
    }


@pytest.fixture
def mock_client():
    """A MagicMock that emits a single canned finding."""
    sample = [{"text": "Pneumonia in RLL", "clinical_status": "abnormal", "comparison": None, "measurements": []}]
    client = MagicMock()
    client.complete.return_value = _mock_response(sample)
    return client


def test_basic_extraction_writes_findings_per_series(workdir, mock_client):
    _report(workdir["gt"], "s_001", "Pneumonia in RLL.")
    _report(workdir["pred"], "s_001", "Pneumonia in RLL.")

    extract_findings(
        reports_gt_dir=workdir["gt"],
        reports_pred_dir=workdir["pred"],
        output_dir=workdir["out"],
        llm_extractor="test-model",
        workers=1,
        client_factory=lambda **_kw: mock_client,
    )

    gt_findings = io.load_json(workdir["results"] / constants.FINDINGS_GT_DIR / "s_001.json")
    assert gt_findings[0]["finding_id"] == "s_001_001"
    assert gt_findings[0]["clinical_status"] == "abnormal"


def test_extraction_resumes_existing_findings(workdir, mock_client):
    """Existing findings on disk are not overwritten; missing ones are extracted."""
    _report(workdir["gt"], "s1", "r1")
    _report(workdir["pred"], "s1", "r1")
    _report(workdir["gt"], "s2", "r2")
    _report(workdir["pred"], "s2", "r2")

    gt_dir = workdir["results"] / constants.FINDINGS_GT_DIR
    pred_dir = workdir["results"] / constants.FINDINGS_PRED_DIR
    gt_dir.mkdir(parents=True)
    pred_dir.mkdir(parents=True)
    existing = [{"finding_id": "s1_001", "text": "Existing", "clinical_status": "abnormal", "measurements": []}]
    io.save_json(existing, gt_dir / "s1.json")
    io.save_json(existing, pred_dir / "s1.json")

    extract_findings(
        reports_gt_dir=workdir["gt"],
        reports_pred_dir=workdir["pred"],
        output_dir=workdir["out"],
        llm_extractor="test-model",
        workers=1,
        client_factory=lambda **_kw: mock_client,
    )

    assert io.load_json(gt_dir / "s1.json")[0]["text"] == "Existing"
    assert (gt_dir / "s2.json").exists()
    # Only the 2 missing reports (s2 gt + s2 pred) hit the LLM
    assert mock_client.complete.call_count == 2


def test_extraction_accepts_existing_findings_gt_dir(workdir, tmp_path, mock_client):
    """`findings_gt_dir` (pre-extracted) is an alternative to `reports_gt_dir`."""
    _report(workdir["pred"], "s1", "pred report")
    existing_gt = tmp_path / "findings_gt_source"
    existing_gt.mkdir()
    gt_payload = [{"finding_id": "s1_001", "text": "GT finding", "clinical_status": "abnormal", "measurements": []}]
    io.save_json(gt_payload, existing_gt / "s1.json")

    extract_findings(
        reports_gt_dir=None,
        reports_pred_dir=workdir["pred"],
        output_dir=workdir["out"],
        llm_extractor="test-model",
        workers=1,
        findings_gt_dir=existing_gt,
        client_factory=lambda **_kw: mock_client,
    )

    gt_dir = workdir["results"] / constants.FINDINGS_GT_DIR
    assert io.load_json(gt_dir / "s1.json")[0]["text"] == "GT finding"


def test_extraction_records_failed_reports(workdir):
    """LLM failure for one report is logged; others succeed."""
    _report(workdir["gt"], "s1", "r1")
    _report(workdir["pred"], "s1", "r1")
    _report(workdir["gt"], "s2", "r2")
    _report(workdir["pred"], "s2", "r2")

    successful = _mock_response([{"text": "F", "clinical_status": "abnormal", "comparison": None, "measurements": []}])

    call_count = 0

    def side_effect(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM API error")
        return successful

    failing_client = MagicMock()
    failing_client.complete.side_effect = side_effect
    extract_findings(
        reports_gt_dir=workdir["gt"],
        reports_pred_dir=workdir["pred"],
        output_dir=workdir["out"],
        llm_extractor="test-model",
        workers=1,
        client_factory=lambda **_kw: failing_client,
    )

    failed = io.load_json(workdir["results"] / constants.FAILED_REPORTS_FILE)
    assert len(failed) > 0


def test_extraction_requires_gt_source(workdir):
    with pytest.raises(ValueError):
        extract_findings(
            reports_gt_dir=None,
            reports_pred_dir=workdir["pred"],
            output_dir=workdir["out"],
            llm_extractor="test-model",
            findings_gt_dir=None,
        )
