"""Stage 2 — batched matching: validation, retry, fallback, canonical order."""

from __future__ import annotations

from radmatch.matching import inference, utils

# ============================================================================
# match_findings — happy path + retry + fallback
# ============================================================================


def _matches_ok(*pairs) -> dict:
    return {
        "matches": [{"pred_id": p, "gt_id": g, "reasoning": ""} for p, g in pairs],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }


def _ctx(client) -> inference.MatchingContext:
    return inference.MatchingContext(client=client)


def test_direct_match_three_pairs(fake_client, ok, make_finding):
    gt = [make_finding("g1"), make_finding("g2"), make_finding("g3")]
    pred = [make_finding("p1"), make_finding("p2"), make_finding("p3")]
    client = fake_client(ok(_matches_ok(("p1", "g1"), ("p2", "g2"), ("p3", "g3"))))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert len(out["matches"]) == 3
    assert out["validation_fallback"] is False
    assert out["retries"] == 0


def test_all_unmatched_in_each_direction(fake_client, ok, make_finding):
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    client = fake_client(ok({"matches": [], "unmatched_pred": ["p1"], "unmatched_gt": ["g1"]}))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["matches"] == []
    assert out["unmatched_pred"] == ["p1"]
    assert out["unmatched_gt"] == ["g1"]


def test_validation_retry_then_success(fake_client, ok, make_finding):
    gt = [make_finding("g1"), make_finding("g2")]
    pred = [make_finding("p1"), make_finding("p2")]
    # `bad` omits g2 entirely (missing from both matches and unmatched) — still invalid under N:N.
    bad = ok(
        {"matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}], "unmatched_pred": ["p2"], "unmatched_gt": []}
    )
    good = ok(_matches_ok(("p1", "g1"), ("p2", "g2")))
    client = fake_client(bad, good)
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["retries"] == 1
    assert out["validation_fallback"] is False
    assert len(client.calls) == 2


def test_validation_fallback_keeps_valid_matches(fake_client, ok, make_finding):
    """After max retries: keep individually-valid matches; orphans → unmatched."""
    gt = [make_finding("g1"), make_finding("g2")]
    pred = [make_finding("p1"), make_finding("p2")]
    # An unknown gt_id ("g_BOGUS") is the only invalid-under-N:N trigger that still
    # leaves one good match to salvage. p2's row is well-formed → fallback keeps it;
    # p1 (mapped to bogus gt) and g1 become orphans.
    bad = ok(
        {
            "matches": [
                {"pred_id": "p1", "gt_id": "g_BOGUS", "reasoning": ""},
                {"pred_id": "p2", "gt_id": "g2", "reasoning": ""},
            ],
            "unmatched_pred": [],
            "unmatched_gt": ["g1"],
        }
    )
    client = fake_client(bad, bad, bad)  # 1 initial + 2 retries

    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["validation_fallback"] is True
    # The p2→g2 match survives; the bogus row is dropped; p1 / g1 fall out as orphans.
    assert any(m["pred_id"] == "p2" and m["gt_id"] == "g2" for m in out["matches"])
    assert "p1" in out["unmatched_pred"]
    assert "g1" in out["unmatched_gt"]


def test_validation_allows_repeated_pred_id(fake_client, ok, make_finding):
    """1:N matching — one pred line covering several GT findings is valid output, no retry."""
    gt = [make_finding("g1"), make_finding("g2"), make_finding("g3")]
    pred = [make_finding("p1")]  # umbrella pred ("Cerebellum unremarkable" etc.)
    client = fake_client(ok(_matches_ok(("p1", "g1"), ("p1", "g2"), ("p1", "g3"))))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["validation_fallback"] is False
    assert out["retries"] == 0
    assert len(out["matches"]) == 3
    assert all(m["pred_id"] == "p1" for m in out["matches"])
    assert out["unmatched_pred"] == []
    assert out["unmatched_gt"] == []


def test_validation_allows_repeated_gt_id(fake_client, ok, make_finding):
    """N:1 matching — several pred findings covering one umbrella GT is valid, no retry."""
    gt = [make_finding("g1")]  # umbrella GT ("Multiple bilateral renal cysts" etc.)
    pred = [make_finding("p1"), make_finding("p2"), make_finding("p3")]
    client = fake_client(ok(_matches_ok(("p1", "g1"), ("p2", "g1"), ("p3", "g1"))))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["validation_fallback"] is False
    assert out["retries"] == 0
    assert len(out["matches"]) == 3
    assert all(m["gt_id"] == "g1" for m in out["matches"])
    assert out["unmatched_pred"] == []
    assert out["unmatched_gt"] == []


def test_validation_fallback_survives_malformed_match_entries(fake_client, ok, make_finding):
    """If the LLM's final response has `matches: ["string-entry", 42, {...valid}]`,
    fallback salvage must skip the non-dict entries and keep the valid one — not
    crash on `.get()`."""
    gt = [make_finding("g1"), make_finding("g2")]
    pred = [make_finding("p1"), make_finding("p2")]
    # Two non-dict entries + one valid; validator rejects this shape so all
    # retries are exhausted and `_fallback_match_result` runs on this payload.
    bad = ok(
        {
            "matches": ["not-a-dict", 42, {"pred_id": "p1", "gt_id": "g1", "reasoning": "ok"}],
            "unmatched_pred": [],
            "unmatched_gt": [],
        }
    )
    client = fake_client(bad, bad, bad)

    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert out["validation_fallback"] is True
    # The one valid pair survives; p2 / g2 fall out as unmatched.
    assert len(out["matches"]) == 1
    assert out["matches"][0]["pred_id"] == "p1" and out["matches"][0]["gt_id"] == "g1"
    assert "p2" in out["unmatched_pred"]
    assert "g2" in out["unmatched_gt"]


def test_status_conflict_still_matches(fake_client, ok, make_finding):
    """Stage 2 must still match status-conflicting pairs (INC is decided downstream)."""
    gt = [make_finding("g1", clinical_status="abnormal", text="Pneumothorax")]
    pred = [make_finding("p1", clinical_status="normal", text="No pneumothorax")]
    client = fake_client(ok(_matches_ok(("p1", "g1"))))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert len(out["matches"]) == 1


def test_canonical_order_independent_of_llm_order(fake_client, ok, make_finding):
    gt = [make_finding("g1"), make_finding("g2"), make_finding("g3")]
    pred = [make_finding("p1"), make_finding("p2"), make_finding("p3")]
    # LLM returns out of order
    client = fake_client(ok(_matches_ok(("p3", "g3"), ("p1", "g1"), ("p2", "g2"))))
    out = inference.match_findings(pred, gt, "s1", _ctx(client))
    assert [m["pred_id"] for m in out["matches"]] == ["p1", "p2", "p3"]


# ============================================================================
# Indication injection — Stage 2 user payload
# ============================================================================


def test_build_matching_messages_includes_indication():
    """`indication` should appear in the user-message JSON payload when set."""
    pred = [{"finding_id": "p1", "text": "f"}]
    gt = [{"finding_id": "g1", "text": "f"}]
    msgs = utils.build_matching_messages(pred, gt, indication="Trauma — r/o pneumothorax")
    user_content = msgs[-1]["content"]
    assert '"indication": "Trauma — r/o pneumothorax"' in user_content


def test_build_matching_messages_omits_empty_indication():
    pred = [{"finding_id": "p1", "text": "f"}]
    gt = [{"finding_id": "g1", "text": "f"}]
    msgs = utils.build_matching_messages(pred, gt, indication="")
    assert '"indication"' not in msgs[-1]["content"]


def test_match_findings_passes_indication_to_prompt(fake_client, ok, make_finding):
    """The indication string should travel from `match_findings` into the LLM messages."""
    gt = [make_finding("g1")]
    pred = [make_finding("p1")]
    client = fake_client(ok(_matches_ok(("p1", "g1"))))
    inference.match_findings(pred, gt, "s1", _ctx(client), indication="Workup of hepatic mass")
    user_msg = client.calls[0]["messages"][-1]["content"]
    assert '"indication": "Workup of hepatic mass"' in user_msg


# ============================================================================
# validate_matching_output — id coverage rules
# ============================================================================


def test_validate_accepts_valid_output():
    parsed = {
        "matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    assert utils.validate_matching_output(parsed, {"p1"}, {"g1"}) == []


def test_validate_accepts_repeated_pred_id_in_matches():
    """Same pred_id in multiple matches rows (1:N) — not an error."""
    parsed = {
        "matches": [
            {"pred_id": "p1", "gt_id": "g1", "reasoning": ""},
            {"pred_id": "p1", "gt_id": "g2", "reasoning": ""},
        ],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    assert utils.validate_matching_output(parsed, {"p1"}, {"g1", "g2"}) == []


def test_validate_accepts_repeated_gt_id_in_matches():
    """Same gt_id in multiple matches rows (N:1 umbrella GT) — not an error."""
    parsed = {
        "matches": [
            {"pred_id": "p1", "gt_id": "g1", "reasoning": ""},
            {"pred_id": "p2", "gt_id": "g1", "reasoning": ""},
        ],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    assert utils.validate_matching_output(parsed, {"p1", "p2"}, {"g1"}) == []


def test_validate_rejects_duplicate_pred_gt_pair():
    """Exact (pred_id, gt_id) duplicates in `matches` are LLM noise — they
    would double-count downstream as two muc_records. Repeats on either
    side individually (1:N / N:1) are still valid; only exact pair repeats
    are rejected."""
    parsed = {
        "matches": [
            {"pred_id": "p1", "gt_id": "g1", "reasoning": ""},
            {"pred_id": "p1", "gt_id": "g1", "reasoning": "redundant"},
        ],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("duplicate" in e and "p1" in e and "g1" in e for e in errors)


def test_validate_flags_id_in_both_matched_and_unmatched():
    """A pred_id (or gt_id) can't be in both matches and unmatched."""
    parsed = {
        "matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}],
        "unmatched_pred": ["p1"],
        "unmatched_gt": [],
    }
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("p1" in e and "both" in e for e in errors)


def test_validate_flags_unknown_id():
    parsed = {
        "matches": [{"pred_id": "p_BOGUS", "gt_id": "g1", "reasoning": ""}],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("p_BOGUS" in e for e in errors)


def test_validate_flags_missing_id():
    parsed = {
        "matches": [{"pred_id": "p1", "gt_id": "g1", "reasoning": ""}],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    # p2 appears nowhere → orphan
    errors = utils.validate_matching_output(parsed, {"p1", "p2"}, {"g1"})
    assert any("p2" in e for e in errors)


# ============================================================================
# validate_matching_output — shape errors (returned, not raised)
# ============================================================================


def test_validate_flags_top_level_non_object():
    """A top-level list (instead of an object) must return an error, not raise."""
    errors = utils.validate_matching_output([], {"p1"}, {"g1"})  # type: ignore[arg-type]
    assert errors and "JSON object" in errors[0]


def test_validate_flags_bucket_with_wrong_type():
    """`matches` / `unmatched_pred` / `unmatched_gt` must be lists."""
    parsed = {"matches": "not-a-list", "unmatched_pred": [], "unmatched_gt": []}
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("matches" in e and "must be a list" in e for e in errors)


def test_validate_flags_non_dict_match_entry():
    """A string item inside `matches` (instead of a {pred_id, gt_id, reasoning} object)
    must surface as a validation error, not raise AttributeError."""
    parsed = {"matches": ["not-a-dict"], "unmatched_pred": [], "unmatched_gt": []}
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("matches[0]" in e and "must be an object" in e for e in errors)


def test_validate_flags_unhashable_id_in_unmatched():
    """A dict/list inside `unmatched_pred` would crash `set(observed)` with
    TypeError on unhashable types; we surface it as a validation error instead."""
    parsed = {"matches": [], "unmatched_pred": [{"oops": "object"}], "unmatched_gt": []}
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("unmatched_pred[0]" in e and "must be a string" in e for e in errors)


def test_validate_flags_non_string_match_id():
    """An object-valued `pred_id` / `gt_id` inside `matches` must surface as a
    validation error, not blow up the downstream set conversion."""
    parsed = {
        "matches": [{"pred_id": {"oops": 1}, "gt_id": "g1", "reasoning": ""}],
        "unmatched_pred": [],
        "unmatched_gt": [],
    }
    errors = utils.validate_matching_output(parsed, {"p1"}, {"g1"})
    assert any("matches[0].pred_id" in e and "must be a string" in e for e in errors)
