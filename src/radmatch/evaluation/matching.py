"""LLM-based matching logic for comparing predicted findings against ground truth."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
from pathlib import Path
from typing import Sequence

from radmatch import constants, io
from radmatch.llm_utils import llm_clients, prompts

logger = logging.getLogger(__name__)

# Assets directory - relative to package root
_ASSETS_DIR = Path(__file__).parent.parent.parent.parent / "assets"


def load_matching_fewshot(fewshot_name: str | None) -> Sequence[dict[str, object]]:
    """Load few-shot examples for LLM judge matching."""
    if not fewshot_name:
        return []

    fewshot_dir = _ASSETS_DIR / "fewshot"
    example_set_dir = fewshot_dir / fewshot_name
    matching_dir = example_set_dir / "matching"

    if not matching_dir.exists():
        raise FileNotFoundError(f"Few-shot matching directory missing for examples '{fewshot_name}': {matching_dir}")

    findings_pred_dir = example_set_dir / "findings_pred"
    findings_gt_dir = example_set_dir / "findings_gt"

    if not findings_pred_dir.exists() or not findings_gt_dir.exists():
        raise FileNotFoundError(f"Few-shot findings directories missing for examples '{fewshot_name}'")

    examples: list[dict[str, object]] = []

    for matching_path in sorted(matching_dir.glob(f"{constants.EXAMPLE_FILE_PREFIX}*_*.json")):
        example_name = matching_path.stem

        matching_data = io.load_json(matching_path, raise_on_error=True)
        if not isinstance(matching_data, dict):
            raise ValueError(f"Few-shot example '{example_name}' must be a dictionary")

        matching_result = matching_data.get("matching_result")
        if not matching_result:
            raise ValueError(f"Few-shot example '{example_name}' missing matching_result")

        parts = example_name.rsplit("_", 1)
        if len(parts) != 2:
            raise ValueError(f"Few-shot example '{example_name}' invalid format (expected 'example_N_M')")

        report_name = parts[0]
        try:
            finding_index = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"Few-shot example '{example_name}' invalid finding index: {exc}") from exc

        findings_pred_path = findings_pred_dir / f"{report_name}.json"
        findings_gt_path = findings_gt_dir / f"{report_name}.json"

        if not findings_pred_path.exists():
            raise FileNotFoundError(
                f"Few-shot example '{example_name}' missing predicted findings: {findings_pred_path}"
            )
        if not findings_gt_path.exists():
            raise FileNotFoundError(
                f"Few-shot example '{example_name}' missing ground truth findings: {findings_gt_path}"
            )

        pred_findings_list = io.load_json(findings_pred_path, raise_on_error=True)
        gt_findings_list = io.load_json(findings_gt_path, raise_on_error=True)

        if not isinstance(pred_findings_list, list):
            raise ValueError(f"Few-shot example '{example_name}' predicted findings must be a list")
        if not isinstance(gt_findings_list, list):
            raise ValueError(f"Few-shot example '{example_name}' ground truth findings must be a list")

        if finding_index >= len(pred_findings_list):
            max_index = len(pred_findings_list) - 1
            raise IndexError(
                f"Few-shot example '{example_name}' finding index {finding_index} out of range (max: {max_index})"
            )

        predicted_finding = pred_findings_list[finding_index]

        corresponding_gt_id = matching_result.get("corresponding_gt_finding_id")
        corresponding_gt_index = None
        if corresponding_gt_id and corresponding_gt_id.startswith("gt_"):
            index_str = corresponding_gt_id[3:]
            corresponding_gt_index = int(index_str)
            if corresponding_gt_index < 1 or corresponding_gt_index > len(gt_findings_list):
                corresponding_gt_index = None

        pred_text = predicted_finding.get("text", "")
        gt_texts_list = [f"{j}. {gt_f.get('text', '')}" for j, gt_f in enumerate(gt_findings_list, 1)]

        user_content = f"""PREDICTED FINDING:
{pred_text}

GROUND TRUTH FINDINGS:
{chr(10).join(gt_texts_list)}"""

        assistant_content = json.dumps(
            {
                "matches": matching_result.get("matched", False),
                "corresponding_gt_index": corresponding_gt_index,
                "confidence": matching_result.get("confidence", "medium"),
                "reasoning": matching_result.get("reasoning", ""),
            },
            ensure_ascii=False,
        )

        examples.append({"user": user_content, "assistant": assistant_content})

    return examples


def match_findings_llm(
    pred_findings_list: list[dict[str, object]],
    gt_findings_list: list[dict[str, object]],
    series_uuid: str,
    client: llm_clients.SingleClient,
    workers: int = 5,
    fewshot: str | None = None,
) -> dict[str, dict[str, object]]:
    """Match predicted findings to ground truth findings using LLM judge with parallelization."""
    if not pred_findings_list:
        return {}

    if not gt_findings_list:
        return {
            finding.get("finding_id", f"unknown_{i}"): {
                "matched": False,
                "corresponding_gt_finding_id": None,
                "confidence": "high",
                "reasoning": "No ground truth findings available",
            }
            for i, finding in enumerate(pred_findings_list, 1)
        }

    gt_index_to_id: dict[int, str] = {
        i + 1: finding.get("finding_id", f"gt_{i+1}") for i, finding in enumerate(gt_findings_list)
    }

    used_gt_indices: set[int] = set()
    used_gt_lock = threading.Lock()
    actual_workers = min(workers, len(pred_findings_list))
    matching_results: dict[str, dict[str, object]] = {}

    matching_examples = load_matching_fewshot(fewshot)

    def _match_one_finding(pred_finding: dict[str, object]) -> tuple[str, dict[str, object]]:
        finding_id = pred_finding.get("finding_id", "unknown")
        if not finding_id:
            return finding_id, {
                "matched": False,
                "corresponding_gt_finding_id": None,
                "confidence": "low",
                "reasoning": "Missing finding_id",
            }

        base_prompt = prompts.load_prompt("prompt_llm_judge.md")
        pred_text = pred_finding.get("text", "")
        gt_texts_list = [f"{i}. {gt_f.get('text', '')}" for i, gt_f in enumerate(gt_findings_list, 1)]
        user_content = f"""PREDICTED FINDING:
{pred_text}

GROUND TRUTH FINDINGS:
{chr(10).join(gt_texts_list)}"""

        messages: list[dict[str, object]] = [{"role": "system", "content": base_prompt}]

        if matching_examples:
            for example in matching_examples:
                messages.append({"role": "user", "content": example["user"]})
                messages.append({"role": "assistant", "content": example["assistant"]})

        messages.append({"role": "user", "content": user_content})

        def _call_api():
            content = client.complete(messages=messages, response_format=None)
            if not content:
                raise ValueError("Empty API response")
            return content

        content, failure_reason = llm_clients.call_with_llm_retry(
            _call_api,
            series_uuid=series_uuid,
            logger_instance=logger,
        )

        if content is None:
            return finding_id, {
                "matched": False,
                "corresponding_gt_finding_id": None,
                "confidence": "low",
                "reasoning": failure_reason or "LLM API call failed",
                "api_failed": True,
            }

        try:
            response = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON response for finding %s in series %s: %s", finding_id, series_uuid, content)
            return finding_id, {
                "matched": False,
                "corresponding_gt_finding_id": None,
                "confidence": "low",
                "reasoning": "Invalid JSON response from LLM",
            }

        matches = response.get("matches", False)
        corresponding_gt_index = response.get("corresponding_gt_index")
        confidence = response.get("confidence", "medium")
        reasoning = response.get("reasoning", "")

        corresponding_gt_finding_id = None
        if corresponding_gt_index is not None:
            corresponding_gt_index = int(corresponding_gt_index)
            if corresponding_gt_index < 1 or corresponding_gt_index > len(gt_findings_list):
                logger.warning(
                    "Invalid corresponding_gt_index %d for finding %s in series %s",
                    corresponding_gt_index,
                    finding_id,
                    series_uuid,
                )
                corresponding_gt_index = None
            else:
                corresponding_gt_finding_id = gt_index_to_id[corresponding_gt_index]

        if matches and corresponding_gt_index is not None:
            with used_gt_lock:
                if corresponding_gt_index in used_gt_indices:
                    logger.debug(
                        "GT finding at index %d already matched for series %s, marking as unmatched",
                        corresponding_gt_index,
                        series_uuid,
                    )
                    matches = False
                    corresponding_gt_finding_id = None
                else:
                    used_gt_indices.add(corresponding_gt_index)

        return finding_id, {
            "matched": matches,
            "corresponding_gt_finding_id": corresponding_gt_finding_id,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {
            executor.submit(_match_one_finding, pred_finding): pred_finding.get("finding_id", "unknown")
            for pred_finding in pred_findings_list
        }

        for future in concurrent.futures.as_completed(futures):
            finding_id = futures[future]
            try:
                finding_id, match_result = future.result()
                matching_results[finding_id] = match_result
            except Exception as exc:
                logger.error("Error matching finding %s in series %s: %s", finding_id, series_uuid, exc)
                matching_results[finding_id] = {
                    "matched": False,
                    "corresponding_gt_finding_id": None,
                    "confidence": "low",
                    "reasoning": f"Error during matching: {exc}",
                    "api_failed": True,
                }

    # Reorder results to match original pred_findings_list order
    # This preserves the order of findings as they appear in pred_findings_list
    ordered_results = {}
    for pred_finding in pred_findings_list:
        finding_id = pred_finding.get("finding_id", "unknown")
        if finding_id in matching_results:
            ordered_results[finding_id] = matching_results[finding_id]
        else:
            logger.warning(
                "Finding ID %s not found in matching results for series %s, adding as unmatched",
                finding_id,
                series_uuid,
            )
            ordered_results[finding_id] = {
                "matched": False,
                "corresponding_gt_finding_id": None,
                "confidence": "low",
                "reasoning": "Finding not processed during matching",
            }
    # Return ordered dict preserving insertion order (Python 3.7+)
    return ordered_results


def compute_report_matching_stats(
    pred_findings_list: list[dict[str, object]],
    gt_findings_list: list[dict[str, object]],
    matching_results: dict[str, dict[str, object]],
) -> dict[str, int]:
    """Compute statistics for a single report."""
    gt_count = len(gt_findings_list)
    pred_count = len(pred_findings_list)
    tp = sum(1 for result in matching_results.values() if result.get("matched", False))
    fp = pred_count - tp
    matched_gt_ids = {
        result.get("corresponding_gt_finding_id") for result in matching_results.values() if result.get("matched")
    }
    matched_gt_ids.discard(None)
    fn = gt_count - len(matched_gt_ids)
    return {"gt_count": gt_count, "pred_count": pred_count, "tp": tp, "fp": fp, "fn": fn}
