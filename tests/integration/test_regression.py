"""Snapshot regression — frozen pipeline output on synthetic input.

Five hand-written series exercise every MUC category (COR / PAR / INC /
MIS / SPU) and every clinical-significance tier. A scripted
`FakeLLMClient` drives matching + attribute-error calls deterministically.
The full `metrics_summary.json` is compared byte-for-byte against
`expected_summary.json` (with timestamp/elapsed_s stripped and floats
rounded). Any change in the pipeline output — intentional or accidental
— fires this test.

To accept an intentional change:
    RADMATCH_REGEN_SNAPSHOT=1 uv run pytest tests/integration/test_regression.py

Then review the diff to `tests/snapshots/expected_summary.json` in the PR.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from radmatch.matching.inference import match_dataset
from radmatch.scoring.pipeline import score_dataset
from tests.fakes.fake_llm_client import FakeLLMClient

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots"
EXPECTED_PATH = SNAPSHOTS / "expected_summary.json"

# Non-deterministic fields stripped before comparison.
_NONDETERMINISTIC_FIELDS = ("timestamp", "runtime", "token_usage")


def _normalize(summary: dict, places: int = 6) -> dict:
    """Strip non-deterministic metadata fields and round floats."""

    def _round(obj):
        if isinstance(obj, float):
            return round(obj, places)
        if isinstance(obj, dict):
            return {k: _round(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_round(x) for x in obj]
        return obj

    summary = dict(summary)
    metadata = dict(summary.get("metadata", {}))
    for field in _NONDETERMINISTIC_FIELDS:
        metadata.pop(field, None)
    summary["metadata"] = metadata
    return _round(summary)


def test_metrics_summary_matches_snapshot(tmp_path):
    # Copy the immutable input fixtures into a writable working directory.
    work = tmp_path
    shutil.copytree(SNAPSHOTS / "findings_gt", work / "findings_gt")
    shutil.copytree(SNAPSHOTS / "findings_pred", work / "findings_pred")

    scripted = json.loads((SNAPSHOTS / "fake_replies.json").read_text())
    client = FakeLLMClient(script=[json.dumps(reply) for reply in scripted])

    match_dataset(
        findings_gt_dir=work / "findings_gt",
        findings_pred_dir=work / "findings_pred",
        output_dir=work,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )
    summary = score_dataset(
        findings_gt_dir=work / "findings_gt",
        findings_pred_dir=work / "findings_pred",
        matching_dir=work / "matching",
        output_dir=work,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )

    produced = _normalize(summary)

    if os.environ.get("RADMATCH_REGEN_SNAPSHOT") == "1":
        EXPECTED_PATH.write_text(json.dumps(produced, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return

    expected = json.loads(EXPECTED_PATH.read_text())
    assert produced == expected, (
        "metrics_summary.json drifted from the snapshot.\n"
        f"To accept: RADMATCH_REGEN_SNAPSHOT=1 uv run pytest {Path(__file__).name}"
    )
