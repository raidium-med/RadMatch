"""LLM-based indication extractor.

One LLM call per report → `{"indication": str}`. Empty string when the
report has no indication block. Each result is written to
`<output_dir>/<series_uuid>.txt` so downstream stages can load it via
`io.load_indications`.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from radmatch import constants, io
from radmatch.llm_utils import llm_clients, prompts

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


_INDICATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "indication_output",
        "schema": {
            "type": "object",
            "properties": {
                "indication": {"type": "string"},
            },
            "required": ["indication"],
            "additionalProperties": False,
        },
    },
}


def _extract_one(
    report_path: Path,
    client: llm_clients.Client,
    system_prompt: str,
) -> tuple[str, str | None]:
    """Run the LLM on one report; return `(series_uuid, indication_or_None)`.

    Returns `None` for indication on LLM / JSON failure — caller logs and
    writes an empty file so the series is still listed in the output dir.
    """
    series_uuid = report_path.stem
    report_text = io.read_text_file(report_path)
    if not report_text:
        return series_uuid, ""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": report_text},
    ]
    try:
        content = llm_clients.call_llm(client, messages, response_format=_INDICATION_SCHEMA)
    except Exception as exc:  # noqa: BLE001 — soft-fail per report, surface in stats
        logger.error("[Report %s] Indication LLM call failed: %s", series_uuid, exc)
        return series_uuid, None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("[Report %s] Indication JSON parse failed: %s", series_uuid, exc)
        return series_uuid, None

    indication = parsed.get("indication", "") if isinstance(parsed, dict) else ""
    if not isinstance(indication, str):
        return series_uuid, ""
    return series_uuid, indication.strip()


def extract_indications(
    reports_dir: Path,
    output_dir: Path,
    llm_extractor: str,
    workers: int = 15,
    reasoning: str = "none",
    client_factory=None,
) -> dict[str, str]:
    """Extract indications from every `*.txt` report under `reports_dir`.

    Writes one `<series_uuid>.txt` per processed report into `output_dir`
    (empty file when no indication was found). Reports whose output already
    exists are skipped — re-run extraction by deleting the stale file.
    Returns the same `{series_uuid: indication}` dict for in-process use.
    """
    if not reports_dir.exists():
        raise FileNotFoundError(f"Reports directory not found: {reports_dir}")
    report_files = sorted(reports_dir.glob("*.txt"))
    if not report_files:
        raise ValueError(f"No .txt reports found in {reports_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    to_process, skipped = io.filter_files_needing_processing(report_files, output_dir, ".txt")

    io.log_stage_banner(
        "INDICATION EXTRACTION",
        [
            ("model", llm_extractor),
            ("reports", reports_dir),
            ("output", output_dir),
            ("workers", workers),
            ("reasoning", reasoning),
        ],
    )
    logger.info("Reports found:     %6d", len(report_files))
    logger.info("  • to process:    %6d", len(to_process))
    logger.info("  • cached:        %6d", skipped)

    if not to_process:
        logger.info("Nothing to do — all reports already have indications.")
        return io.load_indications(output_dir)

    if client_factory is None:
        llm_clients.assert_credentials_for(llm_extractor)
        client_factory = llm_clients.build_client
    client = client_factory(model=llm_extractor, max_tokens=constants.MAX_TOKENS, reasoning=reasoning)
    system_prompt = prompts.load_prompt(prompts.PROMPT_INDICATION_EXTRACTION)

    failed = 0
    for series_uuid, indication in io.process_pairs_in_parallel(
        to_process,
        lambda path: _extract_one(path, client, system_prompt),
        workers=workers,
        desc="Indications",
        unit="report",
    ):
        if indication is None:
            # Don't write an empty file on failure — leaving the series absent lets a
            # later run retry it. A genuinely absent indication is an empty string
            # from the LLM, written normally below.
            failed += 1
            continue
        (output_dir / f"{series_uuid}.txt").write_text(indication, encoding="utf-8")

    indications = io.load_indications(output_dir)
    nonempty = sum(1 for v in indications.values() if v)
    io.log_stage_summary(
        "INDICATION SUMMARY",
        [
            f"  Reports processed:   {len(to_process):6d}",
            f"  Reports failed:      {failed:6d}",
            f"  Non-empty results:   {nonempty:6d}",
            f"  Empty results:       {len(indications) - nonempty:6d}",
        ],
    )
    return indications
