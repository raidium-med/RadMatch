"""Prompt utilities — message construction + fewshot loaders + extraction prompt invariants."""

from __future__ import annotations

import json

import pytest

from radmatch import constants
from radmatch.finding_extraction import extract_utils
from radmatch.llm_utils import prompts

EXTRACTION_PROMPT_PATH = prompts._ASSETS_DIR / "prompts" / "prompt_finding_extraction.md"


# ============================================================================
# build_messages — system + user + interleaved few-shot pairs
# ============================================================================


def test_build_messages_no_examples():
    msgs = prompts.build_messages("system text", "report text")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == "system text"
    assert "report text" in msgs[1]["content"]


def test_extraction_fewshot_messages_wraps_assistant_in_findings(monkeypatch):
    """`extraction_fewshot_messages` should serialize the assistant payload
    as `{"findings": [...]}` to match the Stage 1 json_schema root."""
    fake_examples = [
        {"report": "ex1 report", "assistant": [{"finding_id": "ex1_001", "text": "F"}]},
        {"report": "ex2 report", "assistant": [{"finding_id": "ex2_001", "text": "G"}]},
    ]
    monkeypatch.setattr(prompts, "load_extraction_fewshot", lambda _: fake_examples)
    prompts.extraction_fewshot_messages.cache_clear()

    msgs = prompts.extraction_fewshot_messages("fake-bundle")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert "ex1 report" in msgs[0]["content"]
    payload = json.loads(msgs[1]["content"])
    assert payload == {"findings": [{"finding_id": "ex1_001", "text": "F"}]}


def test_build_messages_with_indication_prepends_block():
    """Non-empty `indication` should land in the user message before the report."""
    msgs = prompts.build_messages("system text", "report text", indication="Trauma — r/o pneumothorax")
    user_content = msgs[-1]["content"]
    assert "Study indication: Trauma — r/o pneumothorax" in user_content
    # Indication block must precede the report block so the LLM sees it as context first.
    assert user_content.index("Study indication") < user_content.index("report text")


def test_build_messages_empty_indication_omits_block():
    """Empty / None indication should not add the prompt block."""
    msgs_none = prompts.build_messages("sys", "report", indication=None)
    msgs_empty = prompts.build_messages("sys", "report", indication="")
    for msgs in (msgs_none, msgs_empty):
        assert "Study indication" not in msgs[-1]["content"]


def test_build_messages_interleaves_fewshot_prefix_before_user():
    """`build_messages` splices in the pre-serialized fewshot prefix as-is."""
    fewshot_prefix = (
        {"role": "user", "content": "ex1 user"},
        {"role": "assistant", "content": '{"findings": [{"finding_id": "ex1_001"}]}'},
        {"role": "user", "content": "ex2 user"},
        {"role": "assistant", "content": '{"findings": [{"finding_id": "ex2_001"}]}'},
    )
    msgs = prompts.build_messages("sys", "user report", fewshot_prefix)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "user report" in msgs[-1]["content"]
    payload = json.loads(msgs[2]["content"])
    assert payload["findings"][0]["finding_id"] == "ex1_001"


# ============================================================================
# filter_finding_fields — schema-conformance
# ============================================================================


def test_project_to_canonical_finding_drops_unknown_keys():
    finding = {
        "finding_id": "x_1",
        "text": "f",
        "clinical_status": "abnormal",
        "comparison": None,
        "measurements": [],
        "unknown_extra_field": "should-be-dropped",
        "another_extra": "should-be-dropped",
    }
    out = extract_utils.project_to_canonical_finding(finding)
    assert "unknown_extra_field" not in out
    assert "another_extra" not in out


def test_project_to_canonical_finding_defaults_missing_fields():
    out = extract_utils.project_to_canonical_finding({"finding_id": "x_1", "text": "f"})
    assert out["clinical_status"] == constants.DEFAULT_CLINICAL_STATUS
    assert out["clinical_significance"] == constants.DEFAULT_CLINICAL_SIGNIFICANCE
    assert out["comparison"] is None
    assert out["measurements"] == []


def test_project_to_canonical_finding_preserves_clinical_significance():
    """Pre-extracted GTs reused via --findings-gt must keep their `clinical_significance` —
    otherwise the safety recalls' GT pool collapses to the all-routine default."""
    out = extract_utils.project_to_canonical_finding(
        {"finding_id": "x_1", "text": "f", "clinical_significance": "critical"}
    )
    assert out["clinical_significance"] == "critical"


def test_project_to_canonical_finding_invalid_clinical_significance_defaults():
    out = extract_utils.project_to_canonical_finding(
        {"finding_id": "x_1", "text": "f", "clinical_significance": "BOGUS"}
    )
    assert out["clinical_significance"] == constants.DEFAULT_CLINICAL_SIGNIFICANCE


# ============================================================================
# load_prompt + few-shot loaders
# ============================================================================


def test_load_prompt_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        prompts.load_prompt("nonexistent_12345.txt")


@pytest.mark.parametrize(
    "loader",
    [prompts.load_extraction_fewshot, prompts.load_matching_fewshot, prompts.load_attribute_errors_fewshot],
)
def test_fewshot_loaders_return_empty_for_unknown_or_none(loader):
    assert loader(None) == []
    assert loader("nonexistent_12345") == []


@pytest.mark.parametrize("bundle", sorted(p.name for p in (prompts._ASSETS_DIR / "fewshot").iterdir() if p.is_dir()))
def test_every_matching_fewshot_file_loads(bundle: str):
    """Every `example_*.json` on disk must load.

    A file the loader silently skips — wrong schema, bad JSON — is dead weight that still
    ships in the wheel, so count the files rather than hardcoding a number.
    """
    on_disk = sorted((prompts._ASSETS_DIR / "fewshot" / bundle / "matching").glob("example_*.json"))
    examples = prompts.load_matching_fewshot(bundle)
    assert len(examples) == len(on_disk), f"{bundle}: {len(on_disk) - len(examples)} file(s) skipped by the loader"
    for ex in examples:
        assert {"pred_findings", "gt_findings"} <= ex["user"].keys()
        assert {"matches", "unmatched_pred", "unmatched_gt"} <= ex["assistant"].keys()


def test_matching_fewshot_examples_satisfy_the_live_validator():
    """Examples must obey the same rules the judge's own output is held to — an invalid
    example teaches the judge to emit invalid output."""
    from radmatch.matching.utils import validate_matching_output

    for bundle in sorted(p.name for p in (prompts._ASSETS_DIR / "fewshot").iterdir() if p.is_dir()):
        for i, ex in enumerate(prompts.load_matching_fewshot(bundle), start=1):
            pred_ids = {f["finding_id"] for f in ex["user"]["pred_findings"]}
            gt_ids = {f["finding_id"] for f in ex["user"]["gt_findings"]}
            errors = validate_matching_output(ex["assistant"], pred_ids, gt_ids)
            assert not errors, f"{bundle} matching example #{i}: {errors}"


def test_attribute_errors_fewshot_examples_shape():
    bundle_dir = prompts._ASSETS_DIR / "fewshot" / "abdomen-ct" / "attribute_errors"
    examples = prompts.load_attribute_errors_fewshot("abdomen-ct")
    assert len(examples) == len(sorted(bundle_dir.glob("example_*.json")))
    for ex in examples:
        assert {"series_uuid", "pairs"} <= ex["user"].keys()
        assert "errors_per_match" in ex["assistant"]
        assert len(ex["user"]["pairs"]) == len(ex["assistant"]["errors_per_match"])


# ============================================================================
# Extraction prompt — content invariants (catches silent prompt drift)
# ============================================================================


@pytest.fixture(scope="module")
def extraction_prompt() -> str:
    assert EXTRACTION_PROMPT_PATH.exists(), f"missing: {EXTRACTION_PROMPT_PATH}"
    return EXTRACTION_PROMPT_PATH.read_text()


def test_extraction_prompt_mentions_every_significance_tier(extraction_prompt):
    for tier in constants.CLINICAL_SIGNIFICANCE_VALUES:
        assert f'"{tier}"' in extraction_prompt


def test_extraction_prompt_describes_orthogonality_and_rule_out(extraction_prompt):
    lower = extraction_prompt.lower()
    assert "independent" in lower or "orthogonal" in lower
    assert "rule-out" in lower or "rule out" in lower


def test_extraction_prompt_output_schema_mentions_clinical_significance(extraction_prompt):
    assert "clinical_significance" in extraction_prompt


def test_extraction_prompt_uses_study_indication_for_tier(extraction_prompt):
    """Significance assignment must reference the `Study indication:` block —
    otherwise the LLM tiers rule-outs on text alone and triage findings get
    routine-default by surface form ("no pneumothorax"). This is the
    safety-tier fix from the clinical review."""
    lower = extraction_prompt.lower()
    # The prompt must reference the indication block AND tell the LLM that
    # rule-outs inherit the indication's tier.
    assert "study indication" in lower
    assert "indication" in lower and ("inherit" in lower or "promote" in lower)
