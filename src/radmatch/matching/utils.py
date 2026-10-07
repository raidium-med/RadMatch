"""Private helpers for Stage 2 batched matching.

Types, JSON schema for the LLM response, validation rules, canonical
ordering, and message assembly. The public entry points
(`match_findings`, `match_dataset`) live in `inference.py`.
"""

from __future__ import annotations

import json
from typing import Sequence, TypedDict

from radmatch.llm_utils import prompts


class Match(TypedDict):
    """One pred ↔ gt alignment row."""

    pred_id: str
    gt_id: str
    reasoning: str


class MatchingOutput(TypedDict):
    """Stage 2 output for one report pair."""

    matches: list[Match]
    unmatched_pred: list[str]
    unmatched_gt: list[str]
    validation_fallback: bool
    retries: int


MATCHING_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "matching_output",
        "schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pred_id": {"type": "string"},
                            "gt_id": {"type": "string"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["pred_id", "gt_id", "reasoning"],
                        "additionalProperties": False,
                    },
                },
                "unmatched_pred": {"type": "array", "items": {"type": "string"}},
                "unmatched_gt": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["matches", "unmatched_pred", "unmatched_gt"],
            "additionalProperties": False,
        },
    },
}


def validate_matching_output(
    parsed: dict,
    input_pred_ids: set[str],
    input_gt_ids: set[str],
) -> list[str]:
    """Validation errors for one matching output, empty if valid.

    Each id appears either in one-or-more `matches` rows or exactly once in the
    matching `unmatched_*` list, never both — repeats in `matches` are how an umbrella
    claim covers several atoms on the other side.

    Returns rather than raises, so `match_findings` can feed the message back to the
    LLM on a retry.
    """
    errors: list[str] = []

    if not isinstance(parsed, dict):
        return [f"top-level output must be a JSON object, got {type(parsed).__name__}"]

    def _coerce_list(key: str) -> list:
        value = parsed.get(key, [])
        if not isinstance(value, list):
            errors.append(f"{key!r} must be a list, got {type(value).__name__}")
            return []
        return value

    matches = _coerce_list("matches")
    unmatched_pred = _coerce_list("unmatched_pred")
    unmatched_gt = _coerce_list("unmatched_gt")

    def _collect_id(value: object, label: str) -> str | None:
        """Append a validation error and return None when `value` isn't a string."""
        if not isinstance(value, str):
            errors.append(f"{label} must be a string, got {type(value).__name__}")
            return None
        return value

    pred_in_matches: set[str] = set()
    gt_in_matches: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for i, m in enumerate(matches):
        if not isinstance(m, dict):
            errors.append(f"matches[{i}] must be an object, got {type(m).__name__}")
            continue
        pid = _collect_id(m.get("pred_id"), f"matches[{i}].pred_id")
        gid = _collect_id(m.get("gt_id"), f"matches[{i}].gt_id")
        if pid is not None:
            pred_in_matches.add(pid)
        if gid is not None:
            gt_in_matches.add(gid)
        if pid is not None and gid is not None:
            if (pid, gid) in seen_pairs:
                errors.append(f"matches[{i}]: duplicate (pred_id, gt_id) pair ({pid!r}, {gid!r})")
            seen_pairs.add((pid, gid))

    clean_unmatched_pred = [
        s for i, x in enumerate(unmatched_pred) if (s := _collect_id(x, f"unmatched_pred[{i}]")) is not None
    ]
    clean_unmatched_gt = [
        s for i, x in enumerate(unmatched_gt) if (s := _collect_id(x, f"unmatched_gt[{i}]")) is not None
    ]

    for side, in_matches, unmatched, valid_ids in (
        ("pred", pred_in_matches, clean_unmatched_pred, input_pred_ids),
        ("gt", gt_in_matches, clean_unmatched_gt, input_gt_ids),
    ):
        unmatched_set = set(unmatched)
        # Unmatched bucket must stay unique (a finding is either matched,
        # possibly to several on the other side, or it's an orphan — never both).
        if len(unmatched) != len(unmatched_set):
            seen: set[str] = set()
            for x in unmatched:
                if x in seen:
                    errors.append(f"{side} ID {x!r} appears more than once in unmatched_{side}")
                seen.add(x)
        for x in sorted(in_matches & unmatched_set):
            errors.append(f"{side} ID {x!r} appears in both matches and unmatched_{side}")
        for x in in_matches | unmatched_set:
            if x not in valid_ids:
                errors.append(f"{side} ID {x!r} is not present in the input findings")
        for x in valid_ids:
            if x not in in_matches and x not in unmatched_set:
                errors.append(
                    f"{side} ID {x!r} is missing from the output (must appear in matches or unmatched_{side})"
                )

    return errors


def canonical_order(matches: list[dict], pred_id_order: Sequence[str]) -> list[dict]:
    """Return `matches` sorted by the input pred_findings order."""
    order = {pid: i for i, pid in enumerate(pred_id_order)}
    return sorted(matches, key=lambda m: order.get(m.get("pred_id", ""), len(order)))


def build_matching_messages(
    pred_findings: list[dict],
    gt_findings: list[dict],
    fewshot_name: str | None = None,
    correction_errors: Sequence[str] | None = None,
    indication: str = "",
) -> list[dict]:
    """Assemble the Stage 2 prompt. `correction_errors` is included on
    a validation retry to nudge the model to fix its mistakes. The
    fewshot prefix is fetched from `prompts.matching_fewshot_messages`
    (memoised, so the JSON serialization happens once per process).

    `indication`, when non-empty, is included in the user payload so the
    judge has the clinical context for the study (helps adjudicate
    binarization artifacts and significance assignment).
    """
    system = prompts.load_prompt(prompts.PROMPT_MATCHING)
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(prompts.matching_fewshot_messages(fewshot_name))

    user_payload: dict[str, object] = {"pred_findings": pred_findings, "gt_findings": gt_findings}
    if indication:
        user_payload = {"indication": indication, **user_payload}
    user = json.dumps(user_payload, ensure_ascii=False)
    if correction_errors:
        user = (
            "Your previous response was invalid. Errors:\n- "
            + "\n- ".join(correction_errors)
            + "\n\nReturn corrected output for the same input below.\n\n"
            + user
        )
    messages.append({"role": "user", "content": user})
    return messages
