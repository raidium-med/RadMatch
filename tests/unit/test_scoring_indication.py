"""Stage 3b indication handling — prompt injection + cache fingerprint."""

from __future__ import annotations

from radmatch.scoring import inference, pipeline


def test_detect_attribute_errors_includes_indication(fake_client, ok, make_finding):
    """The indication string should land in the Stage 3b user payload when set."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    matches = [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}]
    client = fake_client(ok({"errors_per_match": [[]]}))
    inference.detect_attribute_errors(
        matches=matches,
        findings_pred={"p1": pred[0]},
        findings_gt={"g1": gt[0]},
        structured_errors_per_pair=[[]],
        series_uuid="s1",
        client=client,
        indication="Trauma — r/o pneumothorax",
    )
    user_msg = client.calls[0]["messages"][-1]["content"]
    assert '"indication": "Trauma — r/o pneumothorax"' in user_msg


def test_detect_attribute_errors_accepts_measurement_dimension(fake_client, ok, make_finding):
    """The LLM may emit a clinical-boundary `measurement` error; it must not be dropped."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    matches = [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}]
    meas_err = {"dimension": "measurement", "severity": "major", "reasoning": "13.0 cm normal vs 13.5 cm splenomegaly"}
    client = fake_client(ok({"errors_per_match": [[meas_err]]}))
    out, _degraded = inference.detect_attribute_errors(
        matches=matches,
        findings_pred={"p1": pred[0]},
        findings_gt={"g1": gt[0]},
        structured_errors_per_pair=[[]],
        series_uuid="s1",
        client=client,
    )
    assert out[0] == [meas_err]


def test_detect_attribute_errors_drops_all_on_length_mismatch(fake_client, ok, make_finding):
    """A per-match array whose length != number of matches is untrustworthy —
    positional realignment would mis-attribute errors — so after retries all text
    errors for the report are dropped (pairs still score via Stage 3a)."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    matches = [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}]
    # 2 error-lists returned for 1 match → length mismatch on every attempt.
    bad = ok(
        {
            "errors_per_match": [
                [{"dimension": "location", "severity": "major", "reasoning": "x"}],
                [{"dimension": "severity", "severity": "minor", "reasoning": "y"}],
            ]
        }
    )
    client = fake_client(bad, bad)  # malformed on both the initial call and the retry
    out, degraded = inference.detect_attribute_errors(
        matches=matches,
        findings_pred={"p1": pred[0]},
        findings_gt={"g1": gt[0]},
        structured_errors_per_pair=[[]],
        series_uuid="s1",
        client=client,
        max_retries=1,
    )
    assert out == [[]]
    assert degraded is True, "the caller needs to know these empty errors are not a clean result"
    assert len(client.calls) == 2  # initial + 1 retry, per max_retries


def test_detect_attribute_errors_retries_malformed_then_recovers(fake_client, ok, make_finding):
    """A malformed Stage 3b response is retried; a well-formed retry is used
    instead of degrading the report to empty text errors."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    matches = [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}]
    loc_err = {"dimension": "location", "severity": "major", "reasoning": "left vs right"}
    bad = ok({"errors_per_match": [[], []]})  # 2 lists for 1 match → malformed
    good = ok({"errors_per_match": [[loc_err]]})
    client = fake_client(bad, good)
    out, _degraded = inference.detect_attribute_errors(
        matches=matches,
        findings_pred={"p1": pred[0]},
        findings_gt={"g1": gt[0]},
        structured_errors_per_pair=[[]],
        series_uuid="s1",
        client=client,
    )
    assert out[0] == [loc_err]
    assert len(client.calls) == 2  # recovered on the retry


def test_detect_attribute_errors_omits_empty_indication(fake_client, ok, make_finding):
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    matches = [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}]
    client = fake_client(ok({"errors_per_match": [[]]}))
    inference.detect_attribute_errors(
        matches=matches,
        findings_pred={"p1": pred[0]},
        findings_gt={"g1": gt[0]},
        structured_errors_per_pair=[[]],
        series_uuid="s1",
        client=client,
    )
    assert '"indication"' not in client.calls[0]["messages"][-1]["content"]


def test_fingerprint_changes_with_indication(make_finding):
    """Adding / changing indication must change the Stage 3b cache fingerprint
    so cached attribute_errors built without indication context are invalidated."""
    pred_by_id = {"p1": make_finding("p1", text="lesion")}
    gt_by_id = {"g1": make_finding("g1", text="lesion")}
    matches = [{"pred_id": "p1", "gt_id": "g1"}]
    fp_empty = pipeline._fingerprint_matched_findings(matches, pred_by_id, gt_by_id, indication="")
    fp_a = pipeline._fingerprint_matched_findings(matches, pred_by_id, gt_by_id, indication="Trauma")
    fp_b = pipeline._fingerprint_matched_findings(matches, pred_by_id, gt_by_id, indication="Follow-up")
    assert fp_empty != fp_a
    assert fp_a != fp_b


def test_fingerprint_stable_for_same_indication(make_finding):
    pred_by_id = {"p1": make_finding("p1", text="lesion")}
    gt_by_id = {"g1": make_finding("g1", text="lesion")}
    matches = [{"pred_id": "p1", "gt_id": "g1"}]
    fp1 = pipeline._fingerprint_matched_findings(matches, pred_by_id, gt_by_id, indication="Trauma")
    fp2 = pipeline._fingerprint_matched_findings(matches, pred_by_id, gt_by_id, indication="Trauma")
    assert fp1 == fp2
