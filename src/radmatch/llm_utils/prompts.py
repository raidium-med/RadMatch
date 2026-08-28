"""Prompt building and LLM message construction utilities."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from pathlib import Path
from typing import Sequence, TypedDict

from radmatch import constants, io
from radmatch.finding_extraction import extract_utils

logger = logging.getLogger(__name__)

# Assets ship inside the package (src/radmatch/assets/) so they survive a wheel build.
_ASSETS_DIR = Path(__file__).parent.parent / "assets"

# Canonical prompt filenames — pass these (not raw strings) to `load_prompt`
# so typos surface as import errors instead of silent FileNotFoundError.
PROMPT_FINDING_EXTRACTION = "prompt_finding_extraction.md"
PROMPT_MATCHING = "prompt_matching.md"
PROMPT_ATTRIBUTE_ERRORS = "prompt_attribute_errors.md"
PROMPT_INDICATION_EXTRACTION = "prompt_indication_extraction.md"


class FewshotExample(TypedDict):
    """One few-shot example loaded for Stages 2 / 3b.

    ``user`` and ``assistant`` carry the parsed JSON payloads — the
    builder JSON-serialises them at message-construction time.
    """

    user: dict
    assistant: dict


# ============================================================================
# Prompt Loading
# ============================================================================


@functools.lru_cache(maxsize=16)
def load_prompt(prompt_name: str) -> str:
    """Load a prompt file from assets directory (cached after first call)."""
    prompt_path = _ASSETS_DIR / "prompts" / prompt_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=16)
def prompt_fingerprint(prompt_name: str) -> str:
    """Short content hash of a prompt file, for cache invalidation.

    Stamped into the per-stage cache config so editing a prompt's text
    automatically invalidates stale cached outputs — no manual version bump to
    forget. Cached per process (the file doesn't change mid-run)."""
    return hashlib.sha256(load_prompt(prompt_name).encode("utf-8")).hexdigest()[:16]


# ============================================================================
# Few-Shot Examples Loading
# ============================================================================


@functools.lru_cache(maxsize=8)
def extraction_fewshot_messages(fewshot_name: str | None) -> tuple[dict, ...]:
    """Pre-serialized Stage 1 fewshot message prefix (user/assistant pairs).

    Cached so the user-prompt formatting + JSON serialization (with the
    json_schema-mandated `{"findings": [...]}` wrapper) happens once per
    `(process, fewshot)` instead of once per extracted report.
    """
    messages: list[dict] = []
    for ex in load_extraction_fewshot(fewshot_name):
        report = ex.get("report")
        assistant_payload = ex.get("assistant")
        if not report or assistant_payload is None:
            continue
        messages.append({"role": "user", "content": get_user_prompt(report)})
        # Wrap in `{"findings": [...]}` to match the Stage 1 json_schema root.
        messages.append(
            {"role": "assistant", "content": json.dumps({"findings": assistant_payload}, ensure_ascii=False)}
        )
    return tuple(messages)


@functools.lru_cache(maxsize=8)
def matching_fewshot_messages(fewshot_name: str | None) -> tuple[dict, ...]:
    """Pre-serialized Stage 2 fewshot message prefix (user/assistant pairs).

    Cached so the JSON serialization happens once per `(process, fewshot)`
    instead of once per matched report pair.
    """
    messages: list[dict] = []
    for ex in load_matching_fewshot(fewshot_name):
        messages.append({"role": "user", "content": json.dumps(ex["user"], ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(ex["assistant"], ensure_ascii=False)})
    return tuple(messages)


@functools.lru_cache(maxsize=8)
def attribute_errors_fewshot_messages(fewshot_name: str | None) -> tuple[dict, ...]:
    """Pre-serialized Stage 3b fewshot message prefix (user/assistant pairs).

    Cached so the JSON serialization happens once per `(process, fewshot)`
    instead of once per matched report pair.
    """
    messages: list[dict] = []
    for ex in load_attribute_errors_fewshot(fewshot_name):
        messages.append({"role": "user", "content": json.dumps(ex["user"], ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(ex["assistant"], ensure_ascii=False)})
    return tuple(messages)


@functools.lru_cache(maxsize=8)
def load_extraction_fewshot(fewshot_name: str | None) -> Sequence[dict[str, object]]:
    """Pair each `reports_gt/example_*.txt` with its `findings_gt/example_*.json`, as
    `{"report": str, "assistant": list_of_findings}` for `build_messages`.
    """
    if not fewshot_name:
        return []

    fewshot_dir = _ASSETS_DIR / constants.FEWSHOT_DIR
    example_set_dir = fewshot_dir / fewshot_name
    reports_dir = example_set_dir / constants.REPORTS_GT_DIR
    findings_dir = example_set_dir / constants.FINDINGS_GT_DIR

    if not reports_dir.exists():
        reports_dir = example_set_dir / "reports"
    if not findings_dir.exists():
        findings_dir = example_set_dir / "findings"

    missing_dirs = [d for d in (reports_dir, findings_dir) if not d.exists()]
    if missing_dirs:
        dirs_text = ", ".join(str(d) for d in missing_dirs)
        logger.error("Few-shot directories missing for '%s': %s", fewshot_name, dirs_text)
        return []

    examples: list[dict[str, object]] = []
    for report_path in sorted(reports_dir.glob(f"{constants.EXAMPLE_FILE_PREFIX}*.txt")):
        stem = report_path.stem
        findings_path = findings_dir / f"{stem}.json"

        if not findings_path.exists():
            logger.warning("Skipping few-shot '%s': missing findings JSON", stem)
            continue

        try:
            report_text = io.read_text_file(report_path) or ""
            findings_payload = io.load_json(findings_path, raise_on_error=True)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Invalid JSON in few-shot '%s': %s", stem, exc)
            continue

        if not isinstance(findings_payload, list):
            logger.warning("Skipping few-shot '%s': findings must be a list", stem)
            continue

        filtered_findings = [
            extract_utils.project_to_canonical_finding(finding)
            for finding in findings_payload
            if isinstance(finding, dict)
        ]

        examples.append({"report": report_text, "assistant": filtered_findings})

    return examples


@functools.lru_cache(maxsize=8)
def load_matching_fewshot(fewshot_name: str | None) -> Sequence[FewshotExample]:
    """Load Stage 2 batched-matching few-shot examples by bundle name.

    Files: ``assets/fewshot/<name>/matching/example_*.json`` shaped as
    ``{user: {pred_findings, gt_findings}, assistant: {matches, unmatched_pred, unmatched_gt}}``.
    Returns raw dicts; the consuming builder JSON-serialises each side.
    Cached by ``fewshot_name``.
    """
    if not fewshot_name:
        return []

    example_dir = _ASSETS_DIR / constants.FEWSHOT_DIR / fewshot_name / constants.MATCHING_DIR
    if not example_dir.exists():
        logger.error("Matching few-shot directory missing for '%s': %s", fewshot_name, example_dir)
        return []

    examples: list[FewshotExample] = []
    for example_path in sorted(example_dir.glob(f"{constants.EXAMPLE_FILE_PREFIX}*.json")):
        try:
            payload = io.load_json(example_path, raise_on_error=True)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Invalid JSON in matching few-shot '%s': %s", example_path.name, exc)
            continue
        if not isinstance(payload, dict) or "user" not in payload or "assistant" not in payload:
            logger.warning("Skipping matching few-shot '%s': missing 'user' or 'assistant'", example_path.name)
            continue
        examples.append({"user": payload["user"], "assistant": payload["assistant"]})

    return examples


@functools.lru_cache(maxsize=8)
def load_attribute_errors_fewshot(fewshot_name: str | None) -> Sequence[FewshotExample]:
    """Load Stage 3b attribute-errors few-shot examples by bundle name.

    Files: ``assets/fewshot/<name>/attribute_errors/example_*.json`` shaped as
    ``{user: {series_uuid, pairs}, assistant: {errors_per_match}}``.
    Returns raw dicts; the consuming builder JSON-serialises each side.
    Cached by ``fewshot_name``.
    """
    if not fewshot_name:
        return []

    example_dir = _ASSETS_DIR / constants.FEWSHOT_DIR / fewshot_name / constants.ATTRIBUTE_ERRORS_DIR
    if not example_dir.exists():
        logger.error("Attribute-errors few-shot directory missing for '%s': %s", fewshot_name, example_dir)
        return []

    examples: list[FewshotExample] = []
    for example_path in sorted(example_dir.glob(f"{constants.EXAMPLE_FILE_PREFIX}*.json")):
        try:
            payload = io.load_json(example_path, raise_on_error=True)
        except (FileNotFoundError, ValueError) as exc:
            logger.error("Invalid JSON in attribute-errors few-shot '%s': %s", example_path.name, exc)
            continue
        if not isinstance(payload, dict) or "user" not in payload or "assistant" not in payload:
            logger.warning("Skipping attribute-errors few-shot '%s': missing 'user' or 'assistant'", example_path.name)
            continue
        examples.append({"user": payload["user"], "assistant": payload["assistant"]})

    return examples


# ============================================================================
# Message Building
# ============================================================================


def get_user_prompt(report: str, indication: str | None = None) -> str:
    """Format the user prompt with the original report text.

    When `indication` is a non-empty string, prepend a `Study indication: <text>`
    block so the LLM sees the clinical context separately from the report body.
    """
    if indication:
        return (
            f"Study indication: {indication}\n\n"
            f"Please extract findings from the following radiology report:\n\n{report}"
        )
    return f"Please extract findings from the following radiology report:\n\n{report}"


def build_messages(
    system_instructions: str,
    report: str,
    fewshot_messages: Sequence[dict[str, object]] = (),
    indication: str | None = None,
) -> list[dict[str, object]]:
    """Construct Stage 1 chat messages: system + pre-serialized fewshot prefix + report.

    `fewshot_messages` is the cached output of `extraction_fewshot_messages`,
    so this call does no JSON serialization itself. `indication`, when present,
    is prepended to the user message via `get_user_prompt`.
    """
    return [
        {"role": "system", "content": system_instructions},
        *fewshot_messages,
        {"role": "user", "content": get_user_prompt(report, indication)},
    ]
