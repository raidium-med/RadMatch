"""Stage 3c — MUC classification, PAR reclassification, per-tier errors (FN / FP) and safety recall / precision."""

from __future__ import annotations

import pytest

from radmatch import constants
from radmatch.scoring import metrics


def _err(severity: str, dimension: str = "location") -> dict:
    return {"dimension": dimension, "severity": severity}


def _status_err() -> dict:
    return {"dimension": "clinical_status", "severity": "major", "triggers_inc": True}


_RECORD_COUNTER = [0]


def _muc_record(
    category: str,
    gt_sig: str = "notable",
    pred_sig: str | None = None,
    gt_id: str | None = None,
    pred_id: str | None = None,
) -> dict:
    """Build a synthetic MUC record. By default each call generates fresh
    `gt_id` + `pred_id` so per-GT aggregations treat records as 1:1; pass
    explicit ids to simulate multi-bind cases."""
    if gt_id is None:
        _RECORD_COUNTER[0] += 1
        gt_id = f"g_{_RECORD_COUNTER[0]}"
    if pred_id is None:
        _RECORD_COUNTER[0] += 1
        pred_id = f"p_{_RECORD_COUNTER[0]}"
    return {
        "pred_id": pred_id,
        "gt_id": gt_id,
        "muc_category": category,
        "structured_errors": [],
        "text_errors": [],
        "inc_triggered": category == "INC",
        "gt_significance": gt_sig,
        "pred_significance": pred_sig or gt_sig,
    }


def _unmatched(sig: str) -> dict:
    return {"finding_id": "f", "clinical_significance": sig}


_ACTIONABLE = constants.ACTIONABLE_SIGNIFICANCE_TIERS
_TRIAGE = constants.TRIAGE_SIGNIFICANCE_TIERS


def _errors(records, unmatched_pred=(), unmatched_gt=(), pool=_ACTIONABLE) -> metrics.TierErrors:
    return metrics.compute_tier_errors(
        records, unmatched_pred=list(unmatched_pred), unmatched_gt=list(unmatched_gt), significance_pool=pool
    )


def _tier(records, unmatched_pred=(), unmatched_gt=(), pool=_ACTIONABLE) -> dict:
    return metrics.compute_tier_metrics(
        records, unmatched_pred=list(unmatched_pred), unmatched_gt=list(unmatched_gt), significance_pool=pool
    )


def _opportunities(records, unmatched_pred=(), unmatched_gt=(), pool=_ACTIONABLE) -> int:
    return metrics.compute_tier_opportunities(
        records, unmatched_pred=list(unmatched_pred), unmatched_gt=list(unmatched_gt), significance_pool=pool
    )


# ============================================================================
# classify_muc — INC > PAR > COR precedence
# ============================================================================


@pytest.mark.parametrize(
    "structured, text, expected, expect_inc",
    [
        pytest.param([], [], "COR", False, id="no-errors-COR"),
        pytest.param([], [_err("major")], "PAR", False, id="text-error-PAR"),
        pytest.param([_err("major", "comparison")], [], "PAR", False, id="comparison-error-PAR"),
        pytest.param([_status_err()], [_err("major")], "INC", True, id="status-overrides-to-INC"),
    ],
)
def test_classify_muc(structured, text, expected, expect_inc):
    category, inc = metrics.classify_muc(structured_errors=structured, text_errors=text)
    assert category == expected
    assert inc is expect_inc


# ============================================================================
# reclassify_to_effective_category — PAR → COR (no major) or INC (any major)
# ============================================================================


def _record_with_errors(category: str, structured=None, text=None, gt_sig: str = "notable") -> dict:
    r = _muc_record(category, gt_sig=gt_sig)
    r["structured_errors"] = structured or []
    r["text_errors"] = text or []
    return r


@pytest.mark.parametrize(
    "record, expected",
    [
        pytest.param(_record_with_errors("COR"), "COR", id="COR-passes-through"),
        pytest.param(_record_with_errors("INC"), "INC", id="INC-passes-through"),
        pytest.param(_record_with_errors("PAR", text=[_err("minor")]), "PAR", id="PAR-only-minor-stays-PAR"),
        pytest.param(_record_with_errors("PAR", text=[_err("major")]), "INC", id="PAR-with-major-becomes-INC"),
        pytest.param(
            _record_with_errors("PAR", text=[_err("major"), _err("minor", "severity")]),
            "INC",
            id="PAR-mixed-with-major-becomes-INC",
        ),
        pytest.param(
            _record_with_errors("PAR", structured=[_err("major", "comparison")]),
            "INC",
            id="PAR-with-structured-major-becomes-INC",
        ),
        pytest.param(
            _record_with_errors("PAR", text=[_err("major"), _err("major", "severity")]),
            "INC",
            id="PAR-with-multiple-majors-still-one-INC",
        ),
    ],
)
def test_reclassify_to_effective_category(record, expected):
    assert metrics.reclassify_to_effective_category(record) == expected


# ============================================================================
# build_muc_record — measurement dedup (deterministic wins over LLM)
# ============================================================================


def _meas(severity: str) -> dict:
    return {"dimension": "measurement", "severity": severity}


def test_build_muc_record_drops_llm_measurement_when_deterministic_fired():
    """Stage 3a already flagged a measurement error → the LLM's measurement
    verdict is dropped so the pair is not double-counted; other text errors stay."""
    finding = {"clinical_significance": "notable"}
    rec = metrics.build_muc_record(
        match={"pred_id": "p1", "gt_id": "g1"},
        pred_finding=finding,
        gt_finding=finding,
        structured_errors=[_meas("major")],
        text_errors=[_meas("major"), _err("minor", "location")],
    )
    assert rec["structured_errors"] == [_meas("major")]
    assert rec["text_errors"] == [_err("minor", "location")]


def test_build_muc_record_keeps_llm_measurement_when_deterministic_silent():
    """Stage 3a found no measurement error → the LLM boundary-crossing verdict is
    retained (the gap it fills) and drives the PAR→INC reclassification."""
    finding = {"clinical_significance": "notable"}
    rec = metrics.build_muc_record(
        match={"pred_id": "p1", "gt_id": "g1"},
        pred_finding=finding,
        gt_finding=finding,
        structured_errors=[],
        text_errors=[_meas("major")],
    )
    assert rec["text_errors"] == [_meas("major")]
    assert metrics.reclassify_to_effective_category(rec) == "INC"


# ============================================================================
# effective_muc_counts — 5-key dict (COR, PAR, INC, MIS, SPU)
# ============================================================================


def test_effective_muc_counts_keys_are_five_categories():
    counts = metrics.effective_muc_counts([], n_spu=0, n_mis=0)
    assert set(counts.keys()) == {"COR", "PAR", "INC", "MIS", "SPU"}


def test_effective_muc_counts_splits_PAR_by_severity():
    records = [
        _record_with_errors("PAR", text=[_err("minor")]),  # → PAR (minor only, keeps PAR)
        _record_with_errors("PAR", text=[_err("major")]),  # → INC (any major reclassifies)
        _record_with_errors("COR"),  # → COR
        _record_with_errors("INC"),  # → INC
    ]
    counts = metrics.effective_muc_counts(records, n_spu=3, n_mis=2)
    assert counts == {"COR": 1, "PAR": 1, "INC": 2, "MIS": 2, "SPU": 3}


def test_effective_muc_counts_dedupes_under_NN_per_gt():
    """Under N:N, a single GT bound by multiple matches counts once, not N times.
    A GT correctly identified by ≥1 credited match shows as COR; matched-but-
    no-credit shows as INC."""
    records = [
        # GT g1: bound by 3 preds, 2 COR + 1 INC → best-of-credited = COR → 1 GT
        _muc_record("COR", gt_id="g1", pred_id="p1"),
        _muc_record("COR", gt_id="g1", pred_id="p2"),
        _muc_record("INC", gt_id="g1", pred_id="p3"),
        # GT g2: bound by 2 preds, both INC → INC → 1 GT
        _muc_record("INC", gt_id="g2", pred_id="p4"),
        _muc_record("INC", gt_id="g2", pred_id="p5"),
    ]
    counts = metrics.effective_muc_counts(records, n_spu=0, n_mis=0)
    assert counts == {"COR": 1, "PAR": 0, "INC": 1, "MIS": 0, "SPU": 0}


# ============================================================================
# compute_tier_errors — count on the actionable tier
# ============================================================================


def test_actionable_errors_zero_for_clean_run():
    records = [_record_with_errors("COR", gt_sig="critical")]
    assert _errors(records)["total"] == 0


def test_actionable_errors_routine_findings_dropped():
    records = [_record_with_errors("INC", gt_sig="routine")]
    unmatched_pred = [_unmatched("routine")]
    unmatched_gt = [_unmatched("routine")]
    assert _errors(records, unmatched_pred, unmatched_gt)["total"] == 0


def test_actionable_errors_counts_INC_plus_MIS_plus_SPU():
    records = [
        _record_with_errors("INC", gt_sig="critical"),  # +1
        _record_with_errors("COR", gt_sig="urgent"),  # +0 (clean)
        _record_with_errors("PAR", text=[_err("major")], gt_sig="notable"),  # PAR-major → INC → +1
        _record_with_errors("PAR", text=[_err("minor")], gt_sig="notable"),  # PAR-minor → COR → +0
    ]
    unmatched_pred = [_unmatched("urgent")]  # +1
    unmatched_gt = [_unmatched("notable"), _unmatched("routine")]  # +1, routine dropped
    assert _errors(records, unmatched_pred, unmatched_gt)["total"] == 4


def test_actionable_errors_uses_gt_side_for_INC_significance():
    """INC takes GT's significance — the truth wins regardless of how pred tiered itself."""
    records = [_record_with_errors("INC", gt_sig="critical")]
    # Pred says routine, but GT is critical → counts
    records[0]["pred_significance"] = "routine"
    assert _errors(records)["total"] == 1


def test_actionable_errors_uses_pred_side_for_SPU_significance():
    """SPU has no GT counterpart — pred's significance decides."""
    unmatched_pred = [_unmatched("critical")]  # +1
    assert _errors([], unmatched_pred)["total"] == 1
    unmatched_pred = [_unmatched("routine")]  # routine → 0
    assert _errors([], unmatched_pred)["total"] == 0


# ============================================================================
# Safety recalls
# ============================================================================


@pytest.mark.parametrize(
    "categories_on_critical, par_minor_count, par_major_count, unmatched_critical_gt, expected",
    [
        # 3 COR + 1 INC + 1 MIS (critical) → 3/5
        pytest.param(["COR", "COR", "COR", "INC"], 0, 0, 1, 3 / 5, id="3-COR-1-INC-1-MIS"),
        pytest.param(["COR", "COR", "INC"], 0, 0, 0, 2 / 3, id="INC-counts-as-miss"),
        # PAR-no-major → COR → counted as hit
        pytest.param(["COR"], 1, 0, 0, 1.0, id="PAR-minor-counts-as-hit"),
        # PAR-with-major → INC → counted as miss
        pytest.param(["COR"], 0, 1, 0, 0.5, id="PAR-major-counts-as-miss"),
    ],
)
def test_safety_recall_on_critical_pool(
    categories_on_critical, par_minor_count, par_major_count, unmatched_critical_gt, expected
):
    records = [_muc_record(c, gt_sig="critical") for c in categories_on_critical]
    records.extend(_record_with_errors("PAR", text=[_err("minor")], gt_sig="critical") for _ in range(par_minor_count))
    records.extend(_record_with_errors("PAR", text=[_err("major")], gt_sig="critical") for _ in range(par_major_count))
    unmatched = [_unmatched("critical")] * unmatched_critical_gt
    result = _tier(records, unmatched_gt=unmatched, pool=("critical",))["recall"]
    assert result == pytest.approx(expected, rel=1e-6)


def test_safety_recall_vacuous_when_no_gt_in_pool():
    """An empty significance pool yields recall = None (undefined, not "perfect")."""
    records = [_muc_record("COR", gt_sig="notable")]
    assert _tier(records, pool=("critical",))["recall"] is None


# ============================================================================
# Multi-bind safety credit
# ============================================================================


def test_actionable_errors_per_gt_all_inc():
    """Per-GT `all_inc`: a pred bound to 3 actionable GTs all as INC
    contributes 3 errors (3 distinct GTs failed, each its own bucket)."""
    records = [
        _muc_record("INC", gt_sig="critical", pred_id="p_umbrella"),
        _muc_record("INC", gt_sig="urgent", pred_id="p_umbrella"),
        _muc_record("INC", gt_sig="notable", pred_id="p_umbrella"),
    ]
    assert _errors(records)["total"] == 3


def test_actionable_opportunities_aligns_with_errors_pred_side_actionable():
    """A routine GT matched (INC) to an actionable pred is a false-positive the
    numerator counts via `pred_sigs`. The opportunity denominator must count it
    too (on the same GT-or-pred condition) so the per-finding rate stays ≤ 1 and
    never divides by zero on the matched-only case."""
    records = [_muc_record("INC", gt_sig="routine", pred_sig="critical")]
    errors = _errors(records)["total"]
    opportunities = _opportunities(records)
    assert errors == 1
    assert opportunities == 1


def test_actionable_opportunities_ge_errors_across_muc_mix():
    """Opportunities ⊇ errors for every category, so numerator ≤ denominator."""
    records = [
        _muc_record("COR", gt_sig="critical"),  # actionable opportunity, no error
        _muc_record("INC", gt_sig="urgent"),  # actionable opportunity + error
        _muc_record("INC", gt_sig="routine", pred_sig="notable"),  # pred-side actionable: opp + error
        _muc_record("COR", gt_sig="routine"),  # non-actionable: neither
    ]
    unmatched_pred = [_unmatched("critical")]  # SPU: opp + error
    unmatched_gt = [_unmatched("notable")]  # MIS: opp + error
    errors = _errors(records, unmatched_pred, unmatched_gt)["total"]
    opportunities = _opportunities(records, unmatched_pred, unmatched_gt)
    assert errors <= opportunities
    assert (errors, opportunities) == (4, 5)


def test_actionable_errors_self_contradiction_not_counted():
    """Per-GT `all_inc`: a GT correctly identified by ANY pred (mixed COR +
    INC) contributes 0 errors — once the finding is recovered, the redundant
    wrong claim is noise, not patient-relevant harm. Aligns with recall's
    per-GT semantic."""
    records = [
        _muc_record("COR", gt_sig="critical", gt_id="g_x", pred_id="p_correct"),
        _muc_record("INC", gt_sig="critical", gt_id="g_x", pred_id="p_wrong"),
    ]
    assert _errors(records)["total"] == 0


def test_par_with_certainty_on_critical_gt_reclassifies_to_inc():
    """A hedge on a critical-tier finding — e.g. pred "possibly hemorrhage vs
    calcification" vs GT "acute hemorrhage" — registers as a minor certainty
    error. Without this rule the pair would stay PAR (effective COR) and
    silently credit safety recall on the critical finding. Routing it to INC
    keeps the safety floor honest."""
    rec = _record_with_errors("PAR", text=[_err("minor", dimension="certainty")], gt_sig="critical")
    assert metrics.reclassify_to_effective_category(rec) == "INC"


def test_par_with_certainty_on_urgent_gt_stays_par():
    """Escalation is critical-tier only — urgent / notable / routine still
    follow the standard PAR-with-minor → PAR rule. (Conservative scope; can
    be widened to the full actionable pool later if needed.)"""
    rec = _record_with_errors("PAR", text=[_err("minor", dimension="certainty")], gt_sig="urgent")
    assert metrics.reclassify_to_effective_category(rec) == "PAR"


def test_par_with_non_certainty_minor_on_critical_gt_stays_par():
    """The escalation rule is specific to `certainty` errors — a minor
    severity or location error on a critical GT still counts as PAR."""
    rec = _record_with_errors("PAR", text=[_err("minor", dimension="severity")], gt_sig="critical")
    assert metrics.reclassify_to_effective_category(rec) == "PAR"


def test_actionable_recall_excludes_routine():
    records = [
        _muc_record("COR", gt_sig="critical"),
        _muc_record("COR", gt_sig="urgent"),
        _record_with_errors("PAR", text=[_err("minor")], gt_sig="notable"),  # → COR → hit
    ]
    unmatched = [_unmatched("urgent"), _unmatched("routine")]  # routine ignored
    result = _tier(records, unmatched_gt=unmatched)["recall"]
    # 3 hits (COR + COR + PAR-no-major) / 4 (3 matched actionable + 1 unmatched urgent)
    assert result == pytest.approx(0.75)


# ============================================================================
# assign_subsets
# ============================================================================


def _f(status: str, *, measurements=None, comparison=None) -> dict:
    return {
        "clinical_status": status,
        "comparison": comparison,
        "measurements": measurements or [],
    }


@pytest.mark.parametrize(
    "finding, expected",
    [
        # Regular findings (no measurement / comparison) land in the *-regular status subset.
        pytest.param(_f("normal"), {"normal-regular"}, id="normal-regular"),
        pytest.param(_f("abnormal"), {"abnormal-regular"}, id="abnormal-regular"),
        # A measurement/comparison attribute excludes the finding from the *-regular subset.
        pytest.param(_f("abnormal", measurements=[{}]), {"measurement"}, id="abnormal-with-measurement-excluded"),
        pytest.param(
            _f("abnormal", measurements=[{}], comparison="stable"),
            {"measurement", "comparison"},
            id="measurement-and-comparison-excludes-regular",
        ),
        pytest.param(_f("normal", measurements=[{}]), {"measurement"}, id="normal-with-measurement-excluded"),
        pytest.param(_f("abnormal", comparison="stable"), {"comparison"}, id="abnormal-with-comparison-excluded"),
    ],
)
def test_assign_subsets(finding, expected):
    assert set(metrics.assign_subsets(finding)) == expected


# ============================================================================
# compute_tier_metrics — recall / precision with their counts
# ============================================================================


def test_tier_metrics_recalls_with_denominators():
    records = [
        _muc_record("COR", gt_sig="critical"),
        _record_with_errors("PAR", text=[_err("minor")], gt_sig="urgent"),  # PAR-minor → COR → hit
        _muc_record("INC", gt_sig="critical"),
    ]
    unmatched = [_unmatched("notable")]
    triage = _tier(records, unmatched_gt=unmatched, pool=_TRIAGE)
    actionable = _tier(records, unmatched_gt=unmatched)
    # Triage pool (critical+urgent) GT → 3 matched records on the pool
    assert triage["gt_total"] == 3
    # Actionable pool: 3 matched + 1 unmatched notable
    assert actionable["gt_total"] == 4
    # Triage hits = 2 effective COR (COR-critical + PAR-minor → COR)
    assert triage["recall_hits"] == 2
    assert triage["recall"] == pytest.approx(2 / 3)
    assert actionable["recall_hits"] == 2
    assert actionable["recall"] == pytest.approx(2 / 4)
    assert (triage["fn_inc_total"], triage["fn_mis_total"]) == (1, 0)


def test_tier_metrics_PAR_with_major_counts_as_miss():
    """A critical finding matched but with a major attribute error is a recall miss and a FN."""
    records = [_record_with_errors("PAR", text=[_err("major")], gt_sig="critical")]
    triage = _tier(records, pool=_TRIAGE)
    assert (triage["gt_total"], triage["recall_hits"]) == (1, 0)
    assert triage["recall"] == pytest.approx(0.0)
    assert (triage["fn_total"], triage["fn_inc_total"]) == (1, 1)


def test_tier_metrics_precision_credits_unique_preds_and_penalises_spu():
    """Precision denominator = matched preds in pool + SPU in pool; numerator = credited preds."""
    records = [
        _muc_record("COR", gt_sig="critical", pred_sig="critical"),
        _muc_record("INC", gt_sig="urgent", pred_sig="urgent"),
        _muc_record("COR", gt_sig="notable", pred_sig="notable"),
    ]
    unmatched_pred = [_unmatched("critical")]  # SPU on actionable pool
    triage = _tier(records, unmatched_pred=unmatched_pred, pool=_TRIAGE)
    actionable = _tier(records, unmatched_pred=unmatched_pred)
    # Triage preds: 1 COR-critical + 1 INC-urgent + 1 SPU-critical = 3 total, 1 credited
    assert (triage["pred_total"], triage["precision_hits"]) == (3, 1)
    assert triage["precision"] == pytest.approx(1 / 3)
    # Actionable preds: triage + 1 COR-notable = 4 total, 2 credited
    assert (actionable["pred_total"], actionable["precision_hits"]) == (4, 2)
    assert actionable["precision"] == pytest.approx(2 / 4)


def test_tier_metrics_precision_vacuous_when_no_pred_in_pool():
    """No actionable preds (matched or SPU) → precision = None (not 1.0)."""
    records = [_muc_record("COR", gt_sig="routine", pred_sig="routine")]
    for pool in (_TRIAGE, _ACTIONABLE):
        tier = _tier(records, pool=pool)
        assert tier["pred_total"] == 0
        assert tier["precision"] is None


# ============================================================================
# FN / FP split
# ============================================================================


def _mixed_case() -> tuple[list[dict], list[dict], list[dict]]:
    records = [
        _muc_record("COR", gt_sig="critical"),
        _muc_record("INC", gt_sig="critical"),
        _record_with_errors("PAR", text=[_err("major")], gt_sig="urgent"),  # → INC
        _muc_record("INC", gt_sig="routine", pred_sig="critical"),
        _muc_record("INC", gt_sig="notable", pred_sig="urgent"),
        _muc_record("COR", gt_sig="urgent", gt_id="g_shared", pred_id="p_ok"),
        _muc_record("INC", gt_sig="urgent", gt_id="g_shared", pred_id="p_wrong"),  # credited by p_ok
        _muc_record("INC", gt_sig="routine", pred_sig="notable", gt_id="g_r2", pred_id="p_umbrella"),
        _muc_record("INC", gt_sig="routine", pred_sig="notable", gt_id="g_r3", pred_id="p_umbrella"),
    ]
    unmatched_pred = [_unmatched("critical"), _unmatched("notable"), _unmatched("routine")]
    unmatched_gt = [_unmatched("urgent"), _unmatched("notable"), _unmatched("routine")]
    return records, unmatched_pred, unmatched_gt


@pytest.mark.parametrize("tier", list(constants.ERROR_TIERS))
def test_tier_split_identities(tier):
    """errors == FN + FP, FN == MIS + INC on the tier's GT == gt_total - recall_hits,
    FP == SPU + INC claimed by the tier on a GT outside it; errors <= findings at stake."""
    records, unmatched_pred, unmatched_gt = _mixed_case()
    t = _tier(records, unmatched_pred, unmatched_gt, pool=constants.ERROR_TIERS[tier])
    assert t["errors_total"] == t["fn_total"] + t["fp_total"]
    assert t["fn_total"] == t["fn_mis_total"] + t["fn_inc_total"] == t["gt_total"] - t["recall_hits"]
    assert t["fp_total"] == t["fp_spu_total"] + t["fp_inc_total"]
    assert t["errors_total"] <= t["findings_total"]


@pytest.mark.parametrize(
    "records, expected",
    [
        pytest.param([_muc_record("INC", gt_sig="routine", pred_sig="critical")], (0, 1), id="claim-on-routine-GT"),
        pytest.param([_muc_record("INC", gt_sig="critical", pred_sig="urgent")], (1, 0), id="both-actionable-once"),
        pytest.param([_muc_record("INC", gt_sig="urgent", pred_sig="routine")], (1, 0), id="routine-claim-on-GT"),
        pytest.param(
            [
                _muc_record("INC", gt_sig="routine", pred_sig="notable", pred_id="p_u"),
                _muc_record("INC", gt_sig="routine", pred_sig="notable", pred_id="p_u"),
            ],
            (0, 2),
            id="one-claim-on-two-GTs-counts-per-GT",
        ),
    ],
)
def test_actionable_fn_fp_edge_cases(records, expected):
    errors = _errors(records)
    assert (errors["fn"], errors["fp"]) == expected


def test_fn_fp_side_is_relative_to_tier():
    """A notable GT contradicted by an urgent claim is an actionable FN but a triage FP."""
    records = [_muc_record("INC", gt_sig="notable", pred_sig="urgent")]
    actionable, triage = _errors(records), _errors(records, pool=_TRIAGE)
    assert (actionable["fn"], actionable["fp"]) == (1, 0)
    assert (triage["fn"], triage["fp"]) == (0, 1)


def test_orphans_split_by_side():
    """MIS in the tier is a FN, SPU in the tier a FP; routine orphans are neither."""
    unmatched_pred = [_unmatched("critical"), _unmatched("routine")]
    errors = _errors([], unmatched_pred, [_unmatched("notable"), _unmatched("routine")])
    assert errors == {"total": 2, "fn": 1, "fn_mis": 1, "fn_inc": 0, "fp": 1, "fp_spu": 1, "fp_inc": 0}
