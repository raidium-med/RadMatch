"""Stage 3b — one batched LLM call per report, asking whether the free-text
attribute dimensions differ between pred and gt.

INC pairs are evaluated like any other, for diagnostics — their category is already
settled by Stage 3a's status inversion.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from radmatch import constants
from radmatch.llm_utils import llm_clients, prompts

logger = logging.getLogger(__name__)

# Sized for reasoning models: the budget covers hidden reasoning tokens plus the
# answer, and a heavy reasoner can burn >8k thinking before returning anything.
_MAX_TOKENS_ATTRIBUTE_ERRORS: int = 32768

# Extra attempts on a malformed or misaligned payload. Output is non-deterministic,
# so a re-call usually recovers; once spent, the pair degrades to empty text errors
# and still scores via Stage 3a.
DEFAULT_MAX_RETRIES: int = 1


_ATTRIBUTE_ERRORS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "attribute_errors_output",
        "schema": {
            "type": "object",
            "properties": {
                "errors_per_match": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "severity": {"type": "string"},
                                "reasoning": {"type": "string"},
                            },
                            "required": ["dimension", "severity", "reasoning"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
            "required": ["errors_per_match"],
            "additionalProperties": False,
        },
    },
}


def _normalize_llm_error(raw: dict) -> dict | None:
    """Drop unknown dimensions / severities; log a warning per drop."""
    dim = raw.get("dimension")
    sev = raw.get("severity")
    if dim not in constants.ATTRIBUTE_DIMENSIONS_LLM_ACCEPTED:
        logger.warning("Stage 3b dropping error with unknown dimension %r", dim)
        return None
    if sev not in constants.ATTRIBUTE_ERROR_SEVERITIES:
        logger.warning("Stage 3b dropping error with invalid severity %r", sev)
        return None
    return {"dimension": dim, "severity": sev, "reasoning": raw.get("reasoning", "")}


def _parse_aligned_error_lists(content: str, n_matches: int, series_uuid: str) -> list | None:
    """Parse a Stage 3b response into the raw per-match error lists.

    Returns the `errors_per_match` list when the payload is a well-formed JSON
    object whose list length matches `n_matches`; returns None on any malformed
    or misaligned shape so the caller can retry (a length mismatch can't be
    positionally realigned without mis-attributing every later pair's errors).
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("[Report %s] Stage 3b returned invalid JSON: %s", series_uuid, exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning("[Report %s] Stage 3b output must be a JSON object, got %s", series_uuid, type(parsed).__name__)
        return None
    raw_errors_per_match = parsed.get("errors_per_match") or []
    if not isinstance(raw_errors_per_match, list):
        logger.warning(
            "[Report %s] Stage 3b `errors_per_match` must be a list, got %s",
            series_uuid,
            type(raw_errors_per_match).__name__,
        )
        return None
    if len(raw_errors_per_match) != n_matches:
        logger.warning(
            "[Report %s] Stage 3b returned %d error lists for %d matches",
            series_uuid,
            len(raw_errors_per_match),
            n_matches,
        )
        return None
    return raw_errors_per_match


def detect_attribute_errors(
    matches: Sequence[dict],
    findings_pred: dict[str, dict],
    findings_gt: dict[str, dict],
    structured_errors_per_pair: Sequence[Sequence[dict]],
    series_uuid: str,
    client: llm_clients.Client,
    fewshot: str | None = None,
    indication: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> tuple[list[list[dict]], bool]:
    """One schema-constrained LLM call, returning one error list per input match in
    input order, plus whether the call degraded.

    `max_retries` extra attempts are made on a malformed or misaligned payload. Once
    spent, the errors come back empty and `degraded` is True — the pair still scores on
    Stage 3a, but its free-text dimensions are recorded as clean rather than unknown.
    """
    if not matches:
        return [], False

    if len(structured_errors_per_pair) != len(matches):
        raise ValueError(
            f"structured_errors_per_pair length {len(structured_errors_per_pair)} "
            f"does not match matches length {len(matches)}"
        )

    # All matches are shipped to the LLM. We still track `(orig_idx, match)`
    # tuples so the alignment / re-ordering / truncation logic below stays
    # identical to the previous filtered version.
    eligible: list[tuple[int, dict]] = list(enumerate(matches))

    pairs_payload = [
        {
            "pred_finding": findings_pred[m["pred_id"]],
            "gt_finding": findings_gt[m["gt_id"]],
        }
        for _, m in eligible
    ]
    user_payload: dict[str, object] = {"series_uuid": series_uuid}
    if indication:
        user_payload["indication"] = indication
    user_payload["pairs"] = pairs_payload

    messages: list[dict] = [
        {"role": "system", "content": prompts.load_prompt(prompts.PROMPT_ATTRIBUTE_ERRORS)},
        *prompts.attribute_errors_fewshot_messages(fewshot),
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    # Retry a malformed response before giving up; failure degrades to empty text
    # errors rather than losing the pair.
    raw_errors_per_match: list | None = None
    for attempt in range(max_retries + 1):
        try:
            content = llm_clients.call_llm(
                client,
                messages=messages,
                response_format=_ATTRIBUTE_ERRORS_SCHEMA,
                max_tokens=_MAX_TOKENS_ATTRIBUTE_ERRORS,
            )
        except Exception as exc:
            # call_llm already retried transient API errors; don't kill the dataset for one bad pair.
            logger.error("[Report %s] Stage 3b attribute-errors call failed; skipping pair: %s", series_uuid, exc)
            return [[] for _ in matches], True

        raw_errors_per_match = _parse_aligned_error_lists(content, len(eligible), series_uuid)
        if raw_errors_per_match is not None:
            break
        if attempt < max_retries:
            logger.info(
                "[Report %s] Stage 3b output malformed; retrying (%d/%d)",
                series_uuid,
                attempt + 1,
                max_retries,
            )

    if raw_errors_per_match is None:
        logger.error(
            "[Report %s] Stage 3b output malformed after %d attempts; dropping text errors for the report",
            series_uuid,
            max_retries + 1,
        )
        return [[] for _ in matches], True

    normalised_per_eligible: list[list[dict]] = []
    for raw_list in raw_errors_per_match[: len(eligible)]:
        normalised: list[dict] = []
        # Skip non-list items (e.g. the LLM returned a string or dict instead of a list)
        # rather than iterating their characters/keys.
        if not isinstance(raw_list, list):
            normalised_per_eligible.append([])
            continue
        for err in raw_list:
            if not isinstance(err, dict):
                # Nested malformed item (e.g. inner string in `[["location differs"]]`).
                # Drop silently — the per-pair lookup would AttributeError otherwise.
                continue
            n = _normalize_llm_error(err)
            if n is not None:
                normalised.append(n)
        normalised_per_eligible.append(normalised)

    # Re-align to the input matches order: eligible[i] → original index, INC pairs → [].
    output: list[list[dict]] = [[] for _ in matches]
    for (orig_idx, _), errs in zip(eligible, normalised_per_eligible):
        output[orig_idx] = errs
    return output, False
