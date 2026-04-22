"""I/O helpers for JSON and file operations."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

T = TypeVar("T")


def read_text_file(file_path: Path, logger_instance: logging.Logger | None = None) -> str | None:
    """Read and validate text from a file.

    Args:
        file_path: Path to the text file
        logger_instance: Optional logger instance (uses module logger if None)

    Returns:
        File text as string, or None if file is empty or cannot be read
    """
    logger_inst = get_logger(logger_instance)

    try:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text:
            logger_inst.warning(f"Empty file: {file_path.name}")
            return None
        return text
    except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError) as exc:
        logger_inst.error(f"Failed to read {file_path.name}: {exc}")
        return None


def get_logger(logger_instance: logging.Logger | None, module_name: str | None = None) -> logging.Logger:
    """Get logger instance, using module logger if None provided.

    Args:
        logger_instance: Optional logger instance
        module_name: Optional module name for logger (uses __name__ if None)

    Returns:
        Logger instance
    """
    if logger_instance is not None:
        return logger_instance
    if module_name:
        return logging.getLogger(module_name)
    return logging.getLogger(__name__)


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
    """Save data as JSON with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=ensure_ascii), encoding="utf-8")


def find_report_files(directory: Path) -> list[Path]:
    """Find all .txt report files in directory.

    Args:
        directory: Directory to search

    Returns:
        Sorted list of .txt file paths
    """
    return sorted(file for file in directory.iterdir() if file.is_file() and file.suffix.lower() == ".txt")


def filter_files_needing_processing(
    input_files: list[Path],
    output_dir: Path,
    output_extension: str = ".json",
    logger_instance: logging.Logger | None = None,
) -> tuple[list[Path], int]:
    """Filter files that need processing (skip those with existing outputs).

    Args:
        input_files: List of input file paths
        output_dir: Directory containing output files
        output_extension: Extension of output files (default: ".json")
        logger_instance: Optional logger instance

    Returns:
        Tuple of (files_to_process, skipped_count)
    """
    logger_inst = get_logger(logger_instance)
    files_to_process = []
    skipped_count = 0

    for input_file in input_files:
        output_path = output_dir / f"{input_file.stem}{output_extension}"

        if output_path.exists():
            skipped_count += 1
            continue

        files_to_process.append(input_file)

    if skipped_count > 0:
        logger_inst.info("Skipping %d report files that already have outputs", skipped_count)

    return files_to_process, skipped_count
