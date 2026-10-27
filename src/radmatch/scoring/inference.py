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
                "errors_per_pair": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pair_id": {"type": "integer"},
                            "errors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "dimension": {"type": "string"},
                                        "reasoning": {"type": "string"},
                                        "severity": {"type": "string"},
                                    },
                                    "required": ["dimension", "reasoning", "severity"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["pair_id", "errors"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["errors_per_pair"],
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


def _parse_error_lists_by_pair(content: str, n_pairs: int, series_uuid: str) -> list | None:
    """Parse a Stage 3b response into one raw error list per pair, in input order.

    Each entry names the `pair_id` it answers, so lists are placed by id, never by
    position. Returns None (so the caller retries) on a malformed payload, or unless
    the ids are exactly 1..`n_pairs`, each once.
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("[Report %s] Stage 3b returned invalid JSON: %s", series_uuid, exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning("[Report %s] Stage 3b output must be a JSON object, got %s", series_uuid, type(parsed).__name__)
        return None
    entries = parsed.get("errors_per_pair")
    if not isinstance(entries, list):
        logger.warning(
            "[Report %s] Stage 3b `errors_per_pair` must be a list, got %s", series_uuid, type(entries).__name__
        )
        return None
    by_id: dict[int, object] = {}
    for entry in entries:
        pair_id = entry.get("pair_id") if isinstance(entry, dict) else None
        if type(pair_id) is not int or not 1 <= pair_id <= n_pairs or pair_id in by_id:
            logger.warning("[Report %s] Stage 3b returned an unknown or repeated pair_id %r", series_uuid, pair_id)
            return None
        if not isinstance(entry.get("errors"), list):
            logger.warning("[Report %s] Stage 3b `errors` of pair_id %d must be a list", series_uuid, pair_id)
            return None
        by_id[pair_id] = entry["errors"]
    if len(by_id) != n_pairs:
        logger.warning("[Report %s] Stage 3b answered %d of %d pairs", series_uuid, len(by_id), n_pairs)
        return None
    return [by_id[i] for i in range(1, n_pairs + 1)]


def match_groups(matches: Sequence[dict]) -> list[tuple[list[str], list[str]]]:
    """Per match, the pred ids and gt ids of its connected match group, itself included."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for m in matches:
        parent[find("p:" + m["pred_id"])] = find("g:" + m["gt_id"])
    members: dict[str, set[str]] = {}
    for m in matches:
        members.setdefault(find("g:" + m["gt_id"]), set()).update({"p:" + m["pred_id"], "g:" + m["gt_id"]})
    groups = []
    for m in matches:
        group = members[find("g:" + m["gt_id"])]
        groups.append((sorted(x[2:] for x in group if x[0] == "p"), sorted(x[2:] for x in group if x[0] == "g")))
    return groups


def _group_context(matches: Sequence[dict], findings_pred: dict[str, dict], findings_gt: dict[str, dict]) -> list[dict]:
    """Per match, the texts of the other findings in its connected match group (`same_group_pred` /
    `same_group_gt`), so a pair inside a 1:N or N:1 group is judged against the whole group."""
    out = []
    for m, (group_preds, group_gts) in zip(matches, match_groups(matches)):
        ctx = {}
        preds = [i for i in group_preds if i != m["pred_id"]]
        gts = [i for i in group_gts if i != m["gt_id"]]
        if preds:
            ctx["same_group_pred"] = [findings_pred[i]["text"] for i in preds]
        if gts:
            ctx["same_group_gt"] = [findings_gt[i]["text"] for i in gts]
        out.append(ctx)
    return out


def _detect_attribute_errors_chunk(
    matches: Sequence[dict],
    findings_pred: dict[str, dict],
    findings_gt: dict[str, dict],
    series_uuid: str,
    client: llm_clients.Client,
    fewshot: str | None = None,
    indication: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    *,
    contexts: Sequence[dict],
) -> list[list[dict]]:
    """One schema-constrained LLM call over a chunk of matches, returning one error list
    per match in input order, placed by the `pair_id` each answer names. Raises
    `ValueError` on a timeout, or when the payload is still malformed after
    `max_retries` corrected re-calls.
    """
    pairs_payload = [
        {
            "pair_id": i,
            "pred_finding": findings_pred[m["pred_id"]],
            "gt_finding": findings_gt[m["gt_id"]],
            **contexts[i - 1],
        }
        for i, m in enumerate(matches, start=1)
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
        "content": f"Your previous reply was rejected. Return `errors_per_pair` with exactly one entry "
        f"for each pair_id from 1 to {len(matches)}.",
    }

    raw_error_lists: list | None = None
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

        raw_error_lists = _parse_error_lists_by_pair(content, len(matches), series_uuid)
        if raw_error_lists is not None:
            break
        if attempt < max_retries:
            logger.info(
                "[Report %s] Stage 3b output malformed; retrying (%d/%d)",
                series_uuid,
                attempt + 1,
                max_retries,
            )

    if raw_error_lists is None:
        raise ValueError(f"[Report {series_uuid}] Stage 3b output malformed after {max_retries + 1} attempts")

    output: list[list[dict]] = []
    for raw_list in raw_error_lists:
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
    contexts = _group_context(matches, findings_pred, findings_gt)

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
                contexts=contexts[lo:hi],
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
