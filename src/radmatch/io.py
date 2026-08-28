"""I/O + orchestration helpers shared across stages.

Holds:
- JSON / text file utilities (read, write, validate-and-load).
- Pair-discovery helper used by the dataset orchestrators.
- A small `process_pairs_in_parallel` helper that wraps the
  ThreadPoolExecutor + tqdm pattern that all three stages need.
- Consistent stage-banner / stage-summary logging helpers.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeVar

from tqdm import tqdm

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def read_text_file(file_path: Path) -> str | None:
    """Read and validate text from a file. Returns None if empty or unreadable."""
    try:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning("Empty file: %s", file_path.name)
            return None
        return text
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError) as exc:
        logger.error("Failed to read %s: %s", file_path.name, exc)
        return None


def load_json(path: Path, default: T | None = None, raise_on_error: bool = True) -> object | T:
    """Read JSON from disk with helpful error messages."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if raise_on_error:
            raise
        logger.warning("JSON file not found: %s", path)
        return default

    content = content.strip()
    if not content:
        if raise_on_error:
            raise ValueError(f"Empty JSON file: {path}")
        logger.warning("Empty JSON file: %s", path)
        return default

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        if raise_on_error:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
        logger.error("Invalid JSON in %s: %s", path, exc)
        return default


def save_json(data: object, path: Path, indent: int = 2, ensure_ascii: bool = False) -> None:
    """Save data as JSON, written atomically.

    Temp file + `os.replace`, so an interrupted run can't leave a half-written cache
    file — the Stage 1 cache is existence-based and would treat it as complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def load_indications(indications_dir: Path | None) -> dict[str, str]:
    """Load `<series_uuid>.txt` indication files into a dict.

    Empty dict when the directory is None or missing; empty string per unreadable
    file. Callers treat a missing indication as a no-op.
    """
    if indications_dir is None:
        return {}
    try:
        paths = list(indications_dir.glob("*.txt"))
    except (FileNotFoundError, NotADirectoryError):
        return {}
    return {path.stem: read_text_file(path) or "" for path in paths}


def resolve_indications_dir(explicit: Path | None, results_dir: Path) -> Path | None:
    """Explicit override, else `<results_dir>/indications/` if it exists.

    Lets `match` / `score` reuse what `extract_findings` copied in, without
    re-supplying `--indications`.
    """
    from radmatch import constants

    if explicit is not None:
        return explicit
    fallback = results_dir / constants.INDICATIONS_DIR
    return fallback if fallback.exists() else None


def filter_files_needing_processing(
    input_files: list[Path],
    output_dir: Path,
    output_extension: str = ".json",
) -> tuple[list[Path], int]:
    """Partition `input_files` into (files needing processing, skipped count).

    A file is skipped if `output_dir/<stem><output_extension>` already exists.
    """
    files_to_process: list[Path] = []
    skipped_count = 0
    for input_file in input_files:
        if (output_dir / f"{input_file.stem}{output_extension}").exists():
            skipped_count += 1
        else:
            files_to_process.append(input_file)

    if skipped_count > 0:
        logger.info("Skipping %d report files that already have outputs", skipped_count)
    return files_to_process, skipped_count


# ============================================================================
# Stage logging helpers
# ============================================================================


_BANNER_WIDTH = 90


def log_stage_banner(title: str, config: Sequence[tuple[str, object]]) -> None:
    """Top-of-stage banner with config bullets. Used by all three stage orchestrators."""
    logger.info("")
    logger.info("=" * _BANNER_WIDTH)
    logger.info(title)
    logger.info("-" * _BANNER_WIDTH)
    logger.info("Configuration:")
    label_width = max((len(label) for label, _ in config), default=0)
    for label, value in config:
        logger.info("  • %-*s %s", label_width + 1, f"{label}:", value if value is not None else "None")
    logger.info("=" * _BANNER_WIDTH)
    logger.info("")


def log_stage_summary(title: str, lines: Sequence[str]) -> None:
    """Bottom-of-stage summary block."""
    logger.info("")
    logger.info("-" * _BANNER_WIDTH)
    logger.info(title)
    for line in lines:
        logger.info(line)
    logger.info("=" * _BANNER_WIDTH)


# ============================================================================
# Parallel pair processing
# ============================================================================


def process_pairs_in_parallel(
    items: Sequence[T],
    work_fn: Callable[[T], R],
    workers: int,
    desc: str,
    unit: str = "pair",
) -> Iterable[R]:
    """Run `work_fn` over `items` in a thread pool, yielding in completion order.

    Exceptions propagate — `work_fn` owns its own error handling if it wants to
    fail soft per item.
    """
    if not items:
        return
    actual_workers = min(workers, len(items))
    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {executor.submit(work_fn, item): item for item in items}
        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(items),
            desc=desc,
            unit=unit,
        ):
            yield future.result()
