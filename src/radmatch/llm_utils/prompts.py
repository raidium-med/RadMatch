"""Prompt building and LLM message construction utilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from radmatch import constants, io

logger = logging.getLogger(__name__)

# Assets directory
_ASSETS_DIR = Path(__file__).parent.parent.parent.parent / "assets"


# ============================================================================
# Prompt Loading
# ============================================================================


def load_prompt(prompt_name: str) -> str:
    """Load a prompt file from assets directory."""
    prompt_path = _ASSETS_DIR / "prompts" / prompt_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


# ============================================================================
# Few-Shot Examples Loading
# ============================================================================


def filter_finding_fields(finding: dict[str, object]) -> dict[str, object]:
    """Filter finding to only include fields needed for evaluation.

    Removes extra fields like abnormality_category and organ that might be present
    in pre-extracted findings.

    Args:
        finding: Finding dictionary (may contain extra fields)

    Returns:
        Filtered finding dictionary with only: finding_id, text, clinical_status, comparison, measurements
    """
    clinical_status_raw = finding.get("clinical_status", constants.DEFAULT_CLINICAL_STATUS)
    # Normalize clinical_status: validate against allowed values, default to abnormal if invalid
    clinical_status = (
        clinical_status_raw
        if clinical_status_raw in constants.CLINICAL_STATUS_VALUES
        else constants.DEFAULT_CLINICAL_STATUS
    )

    return {
        "finding_id": finding.get("finding_id", ""),
        "text": finding.get("text", ""),
        "clinical_status": clinical_status,
        "comparison": finding.get("comparison"),
        "measurements": finding.get("measurements", []),
    }


def load_fewshot(fewshot_name: str | None) -> Sequence[dict[str, object]]:
    """Load few-shot examples by name."""
    if not fewshot_name:
        return []

    fewshot_dir = _ASSETS_DIR / "fewshot"
    example_set_dir = fewshot_dir / fewshot_name
    reports_dir = example_set_dir / "reports_gt"
    findings_dir = example_set_dir / "findings_gt"

    if not reports_dir.exists():
        reports_dir = example_set_dir / "reports"
    if not findings_dir.exists():
        findings_dir = example_set_dir / "findings"

    missing_dirs = [d for d in (reports_dir, findings_dir) if not d.exists()]
    if missing_dirs:
        dirs_text = ", ".join(str(d) for d in missing_dirs)
        logger.warning("Few-shot directories missing for '%s': %s", fewshot_name, dirs_text)
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
            filter_finding_fields(finding) for finding in findings_payload if isinstance(finding, dict)
        ]

        examples.append({"report": report_text, "assistant": filtered_findings})

    return examples


# ============================================================================
# Message Building
# ============================================================================


def get_user_prompt(report: str) -> str:
    """Format the user prompt with the original report text."""
    return f"Please extract findings from the following radiology report:\\n\\n{report}"


def build_messages(
    system_instructions: str,
    report: str,
    examples: Sequence[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Construct chat completion messages with optional few-shot examples."""
    messages: list[dict[str, object]] = [{"role": "system", "content": system_instructions}]

    if examples:
        for example in examples:
            if example_report := example.get("report"):
                messages.append({"role": "user", "content": get_user_prompt(example_report)})
            if assistant_payload := example.get("assistant"):
                # Assistant payload is a list of findings (not wrapped in an object)
                messages.append({"role": "assistant", "content": json.dumps(assistant_payload, ensure_ascii=False)})

    messages.append({"role": "user", "content": get_user_prompt(report)})
    return messages


# ============================================================================
# Report Processing Prompts (Simplified - No Taxonomy)
# ============================================================================

# System instructions for report processing (simplified version without taxonomy)
SYSTEM_INSTRUCTIONS = load_prompt("prompt_finding_extraction.md")


def build_report_processing_messages(
    report: str, examples: Sequence[dict[str, object]] | None = None
) -> list[dict[str, object]]:
    """Build messages for report processing task."""
    return build_messages(SYSTEM_INSTRUCTIONS, report, examples)
