"""Stage 3b — LLM calls asking whether the free-text attribute dimensions differ
between pred and gt, in chunks of `_STAGE3B_CHUNK_SIZE` matched pairs per call.

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
_MAX_TOKENS_ATTRIBUTE_ERRORS: int = min(constants.MAX_TOKENS, 16384)

# Extra attempts per chunk on a malformed or misaligned payload, each told what was
# wrong. Once spent, or on a timeout, the chunk is split in half.
DEFAULT_MAX_RETRIES: int = 3
_STAGE3B_CHUNK_SIZE: int = 10
_STAGE3B_TIMEOUT_S: float = constants.LLM_REQUEST_TIMEOUT_S / 3


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
    while len(raw_errors_per_match) > n_matches and raw_errors_per_match[-1] == []:
        raw_errors_per_match.pop()
    if len(raw_errors_per_match) != n_matches:
        logger.warning(
            "[Report %s] Stage 3b returned %d error lists for %d matches",
            series_uuid,
            len(raw_errors_per_match),
            n_matches,
        )
        return None
    return raw_errors_per_match


def _detect_attribute_errors_chunk(
    matches: Sequence[dict],
    findings_pred: dict[str, dict],
    findings_gt: dict[str, dict],
    series_uuid: str,
    client: llm_clients.Client,
    fewshot: str | None = None,
    indication: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> list[list[dict]]:
    """One schema-constrained LLM call over a chunk of matches, returning one error list
    per match in input order. Raises `ValueError` on a timeout, or when the payload is
    still malformed after `max_retries` corrected re-calls.
    """
    pairs_payload = [
        {
            "pred_finding": findings_pred[m["pred_id"]],
            "gt_finding": findings_gt[m["gt_id"]],
        }
        for m in matches
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
    correction = {
        "role": "user",
        "content": f"Your previous reply was rejected. Return `errors_per_match` as exactly "
        f"{len(matches)} lists, one per pair, in the order given.",
    }

    raw_errors_per_match: list | None = None
    for attempt in range(max_retries + 1):
        try:
            content = llm_clients.call_llm(
                client,
                messages=messages if attempt == 0 else [*messages, correction],
                response_format=_ATTRIBUTE_ERRORS_SCHEMA,
                max_tokens=_MAX_TOKENS_ATTRIBUTE_ERRORS,
                timeout=_STAGE3B_TIMEOUT_S,
            )
        except llm_clients.LLM_TIMEOUT_ERRORS as exc:
            raise ValueError(f"[Report {series_uuid}] Stage 3b call timed out") from exc
        except Exception:
            # Must not degrade to "no attribute errors": that is indistinguishable from a
            # clean pair, is cached as such, and silently scores the report as correct.
            logger.error("[Report %s] Stage 3b attribute-errors call failed", series_uuid)
            raise

        raw_errors_per_match = _parse_aligned_error_lists(content, len(matches), series_uuid)
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
        raise ValueError(f"[Report {series_uuid}] Stage 3b output malformed after {max_retries + 1} attempts")

    output: list[list[dict]] = []
    for raw_list in raw_errors_per_match:
        # Skip non-list items (e.g. the LLM returned a string or dict instead of a list)
        # rather than iterating their characters/keys; likewise non-dict inner items.
        if not isinstance(raw_list, list):
            output.append([])
            continue
        normalised = (_normalize_llm_error(err) for err in raw_list if isinstance(err, dict))
        output.append([e for e in normalised if e is not None])
    return output


def detect_attribute_errors(
    matches: Sequence[dict],
    findings_pred: dict[str, dict],
    findings_gt: dict[str, dict],
    series_uuid: str,
    client: llm_clients.Client,
    fewshot: str | None = None,
    indication: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> list[list[dict]]:
    """Stage 3b over all matched pairs, in chunks of `_STAGE3B_CHUNK_SIZE`, returning one
    error list per match in input order.

    A chunk that times out or stays malformed is split in half and retried, down to a
    single pair; a pair that still fails raises, so the report is recorded as failed
    rather than scored as if the judge had found no attribute errors.
    """
    if not matches:
        return []

    def run(lo: int, hi: int) -> list[list[dict]]:
        try:
            return _detect_attribute_errors_chunk(
                matches=matches[lo:hi],
                findings_pred=findings_pred,
                findings_gt=findings_gt,
                series_uuid=series_uuid,
                client=client,
                fewshot=fewshot,
                indication=indication,
                max_retries=max_retries,
            )
        except ValueError as exc:
            if hi - lo <= 1:
                raise
            mid = lo + (hi - lo) // 2
            logger.warning("[Report %s] Stage 3b chunk [%d:%d] failed (%s); splitting", series_uuid, lo, hi, exc)
            return run(lo, mid) + run(mid, hi)

    out: list[list[dict]] = []
    for start in range(0, len(matches), _STAGE3B_CHUNK_SIZE):
        out.extend(run(start, min(start + _STAGE3B_CHUNK_SIZE, len(matches))))
    return out
