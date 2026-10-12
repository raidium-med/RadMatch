"""Stage 2 + Stage 3 integration — pipeline behaviour on synthetic pairs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from radmatch.finding_extraction.extract_utils import validate_and_normalize_finding
from radmatch.finding_extraction.inference import _stamp_findings_dir
from radmatch.matching import inference as matching_inference
from radmatch.matching.inference import MatchingContext, match_dataset, match_findings
from radmatch.scoring import inference
from radmatch.scoring.pipeline import (
    ScoringContext,
    _fingerprint_matched_findings,
    _stage3b_config,
    score_dataset,
    score_pair,
)

if TYPE_CHECKING:
    from pathlib import Path


def _match(p: str, g: str) -> dict:
    return {"pred_id": p, "gt_id": g, "reasoning": "same"}


def _write(path: Path, findings: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(findings), encoding="utf-8")


def _run_pair(findings_gt, findings_pred, series_uuid, client, output_dir=None):
    """Test helper: chain Stage 2 + Stage 3 for one pair."""
    gt_norm = [validate_and_normalize_finding(f) for f in findings_gt]
    pred_norm = [validate_and_normalize_finding(f) for f in findings_pred]
    matching_output = match_findings(pred_norm, gt_norm, series_uuid, MatchingContext(client=client))
    return score_pair(
        matching_output=matching_output,
        findings_gt=findings_gt,
        findings_pred=findings_pred,
        series_uuid=series_uuid,
        ctx=ScoringContext(client=client, output_dir=output_dir),
    )


def _run_dataset(gt_dir, pred_dir, out_dir, client):
    match_dataset(
        findings_gt_dir=gt_dir,
        findings_pred_dir=pred_dir,
        output_dir=out_dir,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )
    return score_dataset(
        findings_gt_dir=gt_dir,
        findings_pred_dir=pred_dir,
        matching_dir=out_dir / "matching",
        output_dir=out_dir,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )


# ============================================================================
# Per-pair behaviour (MUC categories + INC skip)
# ============================================================================


def test_two_cor_pairs(fake_client, ok, make_finding):
    gt = [make_finding("g1", clinical_significance="critical"), make_finding("g2")]
    pred = [make_finding("p1", clinical_significance="critical"), make_finding("p2")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1"), _match("p2", "g2")], "unmatched_pred": [], "unmatched_gt": []}),
        ok({"errors_per_match": [[], []]}),
    )
    out = _run_pair(gt, pred, "s_cor", client)
    assert [r["muc_category"] for r in out["muc_records"]] == ["COR", "COR"]


def test_inc_pair_still_runs_stage_3b(fake_client, ok, make_finding):
    """INC pairs are evaluated by Stage 3b so the recorded errors are available
    downstream for diagnostics. The Stage 3a status-inversion classification
    is what makes the pair INC."""
    gt = [make_finding("g1", clinical_status="abnormal", clinical_significance="critical", text="Pneumothorax")]
    pred = [make_finding("p1", clinical_status="normal", clinical_significance="critical", text="No pneumothorax")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        ok({"errors_per_match": [[{"dimension": "location", "severity": "minor", "reasoning": "x"}]]}),
    )

    out = _run_pair(gt, pred, "s_inc", client)
    record = out["muc_records"][0]
    assert record["muc_category"] == "INC"
    assert len(client.calls) == 2  # Stage 2 match + Stage 3b attribute errors
    assert any(e["dimension"] == "location" for e in record["text_errors"])


def test_par_with_major_error_internally_PAR(fake_client, ok, make_finding):
    """Internal classification is PAR until the summary reclassifies it."""
    gt = [make_finding("g1", clinical_significance="critical", text="left nodule")]
    pred = [make_finding("p1", clinical_significance="critical", text="right nodule")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        ok({"errors_per_match": [[{"dimension": "location", "severity": "major", "reasoning": "L vs R"}]]}),
    )
    out = _run_pair(gt, pred, "s_par", client)
    assert out["muc_records"][0]["muc_category"] == "PAR"
    # Major attribute error → reclassifies to INC in the effective taxonomy
    from radmatch.scoring import metrics as _m

    assert _m.reclassify_to_effective_category(out["muc_records"][0]) == "INC"


def test_par_with_only_minor_errors_keeps_PAR(fake_client, ok, make_finding):
    """A PAR with no major attribute errors keeps the PAR label in the output."""
    gt = [make_finding("g1", clinical_significance="critical", text="lesion")]
    pred = [make_finding("p1", clinical_significance="critical", text="lesion")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        ok({"errors_per_match": [[{"dimension": "location", "severity": "minor", "reasoning": "imprecise"}]]}),
    )
    out = _run_pair(gt, pred, "s_par_minor", client)
    assert out["muc_records"][0]["muc_category"] == "PAR"
    from radmatch.scoring import metrics as _m

    assert _m.reclassify_to_effective_category(out["muc_records"][0]) == "PAR"


def test_unmatched_findings_go_to_spu_and_mis(fake_client, ok, make_finding):
    gt = [make_finding("g1", clinical_significance="critical")]
    pred = [make_finding("p1", clinical_significance="notable")]
    client = fake_client(ok({"matches": [], "unmatched_pred": ["p1"], "unmatched_gt": ["g1"]}))
    out = _run_pair(gt, pred, "s", client)
    assert out["muc_records"] == []
    assert [f["finding_id"] for f in out["unmatched_pred"]] == ["p1"]
    assert [f["finding_id"] for f in out["unmatched_gt"]] == ["g1"]


# ============================================================================
# Dataset-level — 5-pair coverage of all MUC categories
# ============================================================================


def test_dataset_five_pairs_one_per_muc_category(tmp_path, fake_client, ok, make_finding):
    """Verifies the dataset aggregator's MUC counts and safety recall numerators."""
    gt_dir = tmp_path / "findings_gt"
    pred_dir = tmp_path / "findings_pred"
    out_dir = tmp_path / "out"

    _write(gt_dir / "s1.json", [make_finding("g1", clinical_significance="urgent")])
    _write(pred_dir / "s1.json", [make_finding("p1", clinical_significance="urgent")])
    _write(gt_dir / "s2.json", [make_finding("g1", clinical_significance="critical", text="left lobe pneumonia")])
    _write(pred_dir / "s2.json", [make_finding("p1", clinical_significance="critical", text="right lobe pneumonia")])
    _write(
        gt_dir / "s3.json",
        [make_finding("g1", clinical_status="abnormal", clinical_significance="critical", text="Pneumothorax")],
    )
    _write(
        pred_dir / "s3.json",
        [make_finding("p1", clinical_status="normal", clinical_significance="critical", text="No pneumothorax")],
    )
    _write(gt_dir / "s4.json", [make_finding("g1", clinical_significance="notable")])
    _write(pred_dir / "s4.json", [])
    _write(gt_dir / "s5.json", [])
    _write(pred_dir / "s5.json", [make_finding("p1", clinical_significance="routine")])

    # Sorted-series order:
    # match_dataset → s1, s2, s3 matching calls (s4/s5 trivial-branch, no LLM call)
    # score_dataset → s1, s2, s3 attr calls (s3 INC still gets Stage 3b; s4/s5 no matches)
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),  # s1
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),  # s2
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),  # s3
        ok({"errors_per_match": [[]]}),  # s1 attr
        ok({"errors_per_match": [[{"dimension": "location", "severity": "major", "reasoning": "..."}]]}),  # s2 attr
        ok({"errors_per_match": [[]]}),  # s3 attr (INC pair — recorded for diagnostics)
    )

    summary = _run_dataset(gt_dir, pred_dir, out_dir, client)

    # PAR (s2, major location error on critical GT) reclassifies to INC.
    # Effective counts: 1 COR (s1), 0 PAR, 2 INC (s2 reclassified + s3 original),
    # 1 MIS (s4), 1 SPU (s5).
    assert summary["muc_counts"] == {"COR": 1, "PAR": 0, "INC": 2, "MIS": 1, "SPU": 1}
    tiers = summary["tiers"]
    assert set(tiers) == {"actionable", "triage", "critical"}
    # Triage pool (critical+urgent) GT here: s1 (urgent, COR) + s2 (critical, reclassified INC)
    # + s3 (critical, INC) = 3. Hits (effective COR or PAR) = 1 (s1) → recall = 1/3.
    assert tiers["triage"]["recall"] == pytest.approx(1 / 3)
    # Actionable errors: s2 reclassified INC (critical) + s3 INC (critical) + s4 MIS (notable) = 3,
    # all on the reference side (s5 SPU is routine, dropped): aER = aFN + aFP = 3 + 0.
    actionable = tiers["actionable"]
    assert (actionable["errors_total"], actionable["fn_total"], actionable["fp_total"]) == (3, 3, 0)
    assert (actionable["fn_mis_total"], actionable["fn_inc_total"]) == (1, 2)
    assert actionable["errors_per_report"] == pytest.approx(3 / 5)
    assert actionable["fn_per_report"] + actionable["fp_per_report"] == pytest.approx(3 / 5)
    # Triage drops the notable MIS: tER = tFN = 2.
    assert (tiers["triage"]["errors_total"], tiers["triage"]["fn_total"]) == (2, 2)
    assert "actionable_errors_per_report" not in summary
    assert "clinical_safety_summary" not in summary
    assert (out_dir / "metrics_summary.json").exists()


# ============================================================================
# Adversarial gaming check — a template predictor must NOT score well
# ============================================================================


def test_template_predictor_fails_safety_gate(tmp_path, fake_client, ok, make_finding):
    """A predictor that emits only routine normals must score badly on critical recall."""
    gt_dir = tmp_path / "findings_gt"
    pred_dir = tmp_path / "findings_pred"
    out_dir = tmp_path / "out"

    for i in range(5):
        _write(
            gt_dir / f"s{i}.json",
            [
                make_finding(f"g{i}_crit", clinical_significance="critical", text="Pneumothorax"),
                make_finding(f"g{i}_rout", clinical_status="normal", clinical_significance="routine"),
            ],
        )
        _write(
            pred_dir / f"s{i}.json",
            [
                make_finding(
                    f"p{i}_norm", clinical_status="normal", clinical_significance="routine", comparison="stable"
                ),
                make_finding(f"p{i}_anat", clinical_status="normal", clinical_significance="routine"),
            ],
        )

    client = fake_client(
        *[
            ok(
                {
                    "matches": [],
                    "unmatched_pred": [f"p{i}_norm", f"p{i}_anat"],
                    "unmatched_gt": [f"g{i}_crit", f"g{i}_rout"],
                }
            )
            for i in range(5)
        ]
    )

    summary = _run_dataset(gt_dir, pred_dir, out_dir, client)
    # 5 reports × (1 critical MIS + 0 actionable SPU since pred is routine) = 5 actionable errors
    # Routine pred SPUs don't count; routine GT MISes don't count. Critical GT MIS counts.
    assert summary["tiers"]["actionable"]["errors_per_report"] >= 1.0
    assert summary["tiers"]["triage"]["recall"] < 0.2


# ============================================================================
# Failure tolerance + resume
# ============================================================================


def test_stage_3b_failure_surfaces(fake_client, ok, make_finding):
    """A Stage 3b LLM failure must surface so the report is recorded as failed. Degrading to
    empty text errors is indistinguishable from a clean pair and is cached as such."""
    gt = [make_finding("g1", clinical_significance="critical", text="left nodule")]
    pred = [make_finding("p1", clinical_significance="critical", text="right nodule")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        RuntimeError("Stage 3b LLM call failed"),
    )
    with pytest.raises(RuntimeError):
        _run_pair(gt, pred, "s", client)


@pytest.mark.parametrize(
    "malformed_payload",
    [
        pytest.param("[]", id="top-level-list"),
        pytest.param('{"errors_per_match": "not-a-list"}', id="errors_per_match-string"),
        pytest.param('{"errors_per_match": {"oops": []}}', id="errors_per_match-object"),
    ],
)
def test_stage_3b_malformed_shape_surfaces(malformed_payload, fake_client, ok, make_finding):
    """Valid JSON of the wrong shape is unusable; after retries it must raise rather than
    silently score the report as having no attribute errors."""
    gt = [make_finding("g1", clinical_significance="critical", text="nodule")]
    pred = [make_finding("p1", clinical_significance="critical", text="nodule")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        *[malformed_payload] * (inference.DEFAULT_MAX_RETRIES + 1),
    )
    with pytest.raises(ValueError):
        _run_pair(gt, pred, "s", client)


def test_stage_3b_valid_shape_with_unusable_entries_normalises_to_empty(fake_client, ok, make_finding):
    """A correctly-shaped payload whose entries are not error objects is not a parse failure:
    the entries are dropped by normalisation and the pair scores via Stage 3a."""
    gt = [make_finding("g1", clinical_significance="critical", text="nodule")]
    pred = [make_finding("p1", clinical_significance="critical", text="nodule")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        '{"errors_per_match": ["not-a-list-of-lists"]}',
    )
    out = _run_pair(gt, pred, "s", client)
    assert out["muc_records"][0]["muc_category"] == "COR"
    assert out["muc_records"][0]["text_errors"] == []


def test_match_dataset_skips_series_with_cached_output(tmp_path, fake_client, make_finding):
    """A pre-existing matching/<series>.json is reused; no LLM call is issued for it."""
    gt_dir = tmp_path / "findings_gt"
    pred_dir = tmp_path / "findings_pred"
    out_dir = tmp_path / "out"
    _write(gt_dir / "s1.json", [make_finding("g1")])
    _write(pred_dir / "s1.json", [make_finding("p1")])
    cached = {
        "matches": [_match("p1", "g1")],
        "unmatched_pred": [],
        "unmatched_gt": [],
        "validation_fallback": False,
        "retries": 0,
        "matching_config": matching_inference._matching_config("fake", None, "none"),
        "findings_fingerprint": matching_inference._findings_fingerprint(
            [validate_and_normalize_finding(make_finding("g1"))],
            [validate_and_normalize_finding(make_finding("p1"))],
            "",
        ),
    }
    _write(out_dir / "matching" / "s1.json", cached)

    client = fake_client()  # empty script — would fail if called
    match_dataset(
        findings_gt_dir=gt_dir,
        findings_pred_dir=pred_dir,
        output_dir=out_dir,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )
    assert client.calls == []  # no LLM call issued; cache was reused


@pytest.mark.parametrize("stale", ["config", "findings"])
def test_match_dataset_invalidates_stale_cache(stale, tmp_path, fake_client, ok, make_finding):
    """A cached matching/<series>.json built under another config, or from other findings
    under the same IDs, is re-matched rather than silently reused."""
    gt_dir = tmp_path / "findings_gt"
    pred_dir = tmp_path / "findings_pred"
    out_dir = tmp_path / "out"
    _write(gt_dir / "s1.json", [make_finding("g1", text="left nodule")])
    _write(pred_dir / "s1.json", [make_finding("p1")])
    stale_record = {
        "matches": [_match("p1", "g1")],
        "unmatched_pred": [],
        "unmatched_gt": [],
        "validation_fallback": False,
        "retries": 0,
        "matching_config": {"judge": "old-model", "fewshot": "old-bundle", "reasoning": "none"},
    }
    if stale == "findings":
        other = [validate_and_normalize_finding(make_finding("g1", text="right nodule"))]
        stale_record["matching_config"] = matching_inference._matching_config("fake", None, "none")
        stale_record["findings_fingerprint"] = matching_inference._findings_fingerprint(
            other, [validate_and_normalize_finding(make_finding("p1"))], ""
        )
    _write(out_dir / "matching" / "s1.json", stale_record)

    client = fake_client(ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}))
    match_dataset(
        findings_gt_dir=gt_dir,
        findings_pred_dir=pred_dir,
        output_dir=out_dir,
        llm_judge="fake",
        workers=1,
        client_factory=lambda *_a, **_kw: client,
    )
    assert len(client.calls) == 1
    written = json.loads((out_dir / "matching" / "s1.json").read_text())
    assert written["matching_config"]["judge"] == "fake"


def test_stamp_findings_dir_discards_findings_from_another_config(tmp_path):
    findings_dir = tmp_path / "findings_pred"
    _write(findings_dir / "s1.json", [])
    _write(tmp_path / "findings_pred_config.json", {"extractor": "old"})
    _stamp_findings_dir(findings_dir, {"extractor": "new"})
    assert not any(findings_dir.glob("*.json"))
    assert json.loads((tmp_path / "findings_pred_config.json").read_text()) == {"extractor": "new"}


def test_score_pair_reuses_cached_text_errors(tmp_path, fake_client, make_finding):
    """A pre-existing attribute_errors/<series>.json is reused for Stage 3b; no LLM call issued."""
    gt = [make_finding("g1", text="left nodule")]
    pred = [make_finding("p1", text="right nodule")]
    out_dir = tmp_path
    matches = [_match("p1", "g1")]
    # Judge/reasoning come from the fake client; fewshot is the ScoringContext default.
    fingerprint = _fingerprint_matched_findings(
        matches,
        {f["finding_id"]: f for f in pred},
        {f["finding_id"]: f for f in gt},
        stage3b_config=_stage3b_config("fake", "none", None),
    )
    cached = {
        "matches": matches,
        "findings_fingerprint": fingerprint,
        "structured_errors_per_pair": [[]],
        "text_errors_per_pair": [[{"dimension": "location", "severity": "major", "reasoning": "cached"}]],
        "muc_records": [],
    }
    _write(out_dir / "attribute_errors" / "s.json", cached)

    matching_output = {"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}
    client = fake_client()  # empty — must not be called
    result = score_pair(
        matching_output=matching_output,
        findings_gt=gt,
        findings_pred=pred,
        series_uuid="s",
        ctx=ScoringContext(client=client, output_dir=out_dir),
    )
    assert client.calls == []
    assert result["muc_records"][0]["text_errors"][0]["reasoning"] == "cached"


def test_score_pair_writes_per_report_metrics(tmp_path, fake_client, ok, make_finding):
    """A per_report_metrics/<series>.json with effective muc_counts + per-tier errors
    is written alongside attribute_errors."""
    gt = [make_finding("g1", clinical_significance="critical", text="left nodule")]
    pred = [make_finding("p1", clinical_significance="critical", text="right nodule")]
    client = fake_client(
        ok({"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}),
        ok({"errors_per_match": [[{"dimension": "location", "severity": "major", "reasoning": "L vs R"}]]}),
    )
    _run_pair(gt, pred, "s1", client, output_dir=tmp_path)
    per_report = json.loads((tmp_path / "per_report_metrics" / "s1.json").read_text())
    assert per_report["metadata"]["series_uuid"] == "s1"
    # Per-pair totals: 1 matched pair (gt + pred) → both sides report 1.
    assert per_report["metadata"]["total_gt_findings"] == 1
    assert per_report["metadata"]["total_pred_findings"] == 1
    # PAR-with-major reclassifies to INC; output has 5 keys including PAR (=0 here).
    assert per_report["muc_counts"] == {"COR": 0, "PAR": 0, "INC": 1, "MIS": 0, "SPU": 0}
    triage = per_report["tiers"]["triage"]
    assert per_report["tiers"]["actionable"]["errors_total"] == 1
    assert (triage["gt_total"], triage["fn_inc_total"]) == (1, 1)
    assert triage["recall"] == 0.0  # major attr error → miss
    # New per-pair fields: attribute_breakdown is included (dataset-symmetric).
    assert "attribute_breakdown" in per_report


def test_score_pair_invalidates_cache_when_matches_differ(tmp_path, fake_client, ok, make_finding):
    """If cached matches don't align with the current ones, Stage 3b is re-run from scratch."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    out_dir = tmp_path
    stale = {
        "matches": [_match("p_OLD", "g_OLD")],  # different pair → cache invalid
        "structured_errors_per_pair": [[]],
        "text_errors_per_pair": [[{"dimension": "location", "severity": "minor", "reasoning": "stale"}]],
        "muc_records": [],
    }
    _write(out_dir / "attribute_errors" / "s.json", stale)

    matching_output = {"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}
    client = fake_client(ok({"errors_per_match": [[]]}))
    result = score_pair(
        matching_output=matching_output,
        findings_gt=gt,
        findings_pred=pred,
        series_uuid="s",
        ctx=ScoringContext(client=client, output_dir=out_dir),
    )
    assert len(client.calls) == 1  # cache invalidated → LLM called
    assert result["muc_records"][0]["text_errors"] == []


def test_score_pair_invalidates_cache_when_finding_text_differs(tmp_path, fake_client, ok, make_finding):
    """Same matches + same finding_ids, but the on-disk finding text differs from the
    findings passed to `score_pair`: cache must invalidate so Stage 3b runs against
    the live finding text rather than reusing labels keyed off stale wording.
    """
    gt = [make_finding("g1", text="left lower lobe nodule")]
    pred = [make_finding("p1", text="right lower lobe nodule")]
    out_dir = tmp_path
    stale_pred = [make_finding("p1", text="OLD pred text — different from current")]
    stale_gt = [make_finding("g1", text="OLD gt text — different from current")]
    stale_fingerprint = _fingerprint_matched_findings(
        [_match("p1", "g1")],
        {f["finding_id"]: f for f in stale_pred},
        {f["finding_id"]: f for f in stale_gt},
    )
    stale = {
        "matches": [_match("p1", "g1")],
        "findings_fingerprint": stale_fingerprint,
        "structured_errors_per_pair": [[]],
        "text_errors_per_pair": [[{"dimension": "location", "severity": "minor", "reasoning": "stale"}]],
        "muc_records": [],
    }
    _write(out_dir / "attribute_errors" / "s.json", stale)

    matching_output = {"matches": [_match("p1", "g1")], "unmatched_pred": [], "unmatched_gt": []}
    client = fake_client(ok({"errors_per_match": [[]]}))
    result = score_pair(
        matching_output=matching_output,
        findings_gt=gt,
        findings_pred=pred,
        series_uuid="s",
        ctx=ScoringContext(client=client, output_dir=out_dir),
    )
    assert len(client.calls) == 1  # fingerprint mismatch → LLM called
    assert result["muc_records"][0]["text_errors"] == []
