#!/usr/bin/env python3
"""CLI for radiology report generation evaluation pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from radmatch import constants
from radmatch.cli import evaluate, extract_findings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


def _add_extraction_arguments(parser: argparse.ArgumentParser) -> None:
    """Add extraction-related arguments to a parser."""
    parser.add_argument("--reports-gt", help="Directory containing ground truth report .txt files")
    parser.add_argument("--reports-pred", required=True, help="Directory containing predicted report .txt files")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--llm-extractor", required=True, help="LLM model name for finding extraction")
    parser.add_argument("--fewshot", default=None, help="Name of few-shot example set to load (optional)")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers (default: 5)")
    parser.add_argument("--limit", type=int, help="Limit number of reports (for debugging)")
    parser.add_argument(
        "--findings-gt", help="Path to existing ground truth findings directory to adapt (alternative to --reports-gt)"
    )
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Reasoning effort for LLM models (default: none)",
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Radiology report generation evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract findings (single inference)
  radmatch extract_findings infer \\
    --reports-gt /path/to/gt --reports-pred /path/to/pred \\
    --output-dir /path/to/output --llm-extractor gpt-5-4 \\
    --workers 15 --fewshot merlin

  # Extract findings (batch submit)
  radmatch extract_findings infer_batch submit \\
    --reports-gt /path/to/gt --reports-pred /path/to/pred \\
    --output-dir /path/to/output --llm-extractor gpt-5-4 \\
    --fewshot merlin

  # Extract findings (batch retrieve)
  radmatch extract_findings infer_batch retrieve \\
    --output-dir /path/to/output

  # Extract findings (batch status)
  radmatch extract_findings infer_batch status \\
    --output-dir /path/to/output

  # Evaluate findings
  radmatch evaluate \\
    --results-dir /path/to/output --llm-judge gpt-5-4

  # Run full pipeline
  radmatch run_all \\
    --reports-gt /path/to/gt --reports-pred /path/to/pred \\
    --output-dir /path/to/output \\
    --llm-extractor gpt-5-4 --llm-judge gpt-5-4 \\
    --workers 5 --fewshot merlin

  # Run full pipeline (adapt existing gt findings)
  radmatch run_all \\
    --findings-gt /path/to/existing/gt_findings \\
    --reports-pred /path/to/pred --output-dir /path/to/output \\
    --llm-extractor gpt-5-4 --llm-judge gpt-5-4 \\
    --workers 5 --fewshot merlin
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    # Extract findings subcommand with nested subparsers
    parser_extract = subparsers.add_parser("extract_findings", help="Extract findings from reports")
    extract_subparsers = parser_extract.add_subparsers(dest="extract_mode", required=True, help="Extraction mode")

    # Single inference
    parser_infer = extract_subparsers.add_parser("infer", help="Single inference mode (real-time)")
    _add_extraction_arguments(parser_infer)

    # Batch inference
    parser_infer_batch = extract_subparsers.add_parser("infer_batch", help="Batch inference operations")
    batch_subparsers = parser_infer_batch.add_subparsers(dest="batch_action", required=True, help="Batch action")

    # Batch submit
    parser_batch_submit = batch_subparsers.add_parser("submit", help="Create and submit batch jobs")
    _add_extraction_arguments(parser_batch_submit)

    # Batch retrieve
    parser_batch_retrieve = batch_subparsers.add_parser("retrieve", help="Retrieve and process batch results")
    parser_batch_retrieve.add_argument("--output-dir", required=True, help="Output directory")
    parser_batch_retrieve.add_argument("--job-id", help="Specific job ID to retrieve (optional)")

    # Batch status
    parser_batch_status = batch_subparsers.add_parser("status", help="Check batch job status")
    parser_batch_status.add_argument("--output-dir", required=True, help="Output directory")
    parser_batch_status.add_argument("--job-id", help="Specific job ID to check (optional)")

    # Evaluate subcommand
    parser_eval = subparsers.add_parser("evaluate", help="Evaluate findings by comparing predicted vs ground truth")
    parser_eval.add_argument(
        "--results-dir",
        required=True,
        help="Results directory containing findings_gt/ and findings_pred/",
    )
    parser_eval.add_argument("--llm-judge", required=True, help="LLM model name for evaluation judge")
    parser_eval.add_argument("--workers", type=int, default=5, help="Number of concurrent workers (default: 5)")
    parser_eval.add_argument("--fewshot", default=None, help="Name of few-shot example set to load (optional)")
    parser_eval.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Reasoning effort for LLM models (default: none)",
    )

    # Run all subcommand
    parser_run_all = subparsers.add_parser("run_all", help="Run full pipeline: extract findings and evaluate")
    _add_extraction_arguments(parser_run_all)
    parser_run_all.add_argument("--llm-judge", required=True, help="LLM model name for evaluation judge")

    return parser.parse_args()


def main() -> None:
    """Main CLI entry point."""
    args = parse_args()

    if args.command == "extract_findings":
        extract_findings.handle_extract_findings(args)
    elif args.command == "evaluate":
        evaluate.handle_evaluate(args)
    elif args.command == "run_all":
        handle_run_all(args)
    else:
        logger.error(f"Invalid command: {args.command}")
        sys.exit(1)


def handle_run_all(args: argparse.Namespace) -> None:
    """Run full pipeline: extract findings and evaluate in sequence."""
    # Validate: either --reports-gt or --findings-gt must be provided
    reports_gt = getattr(args, "reports_gt", None)
    findings_gt = getattr(args, "findings_gt", None)
    if not reports_gt and not findings_gt:
        logger.error("Either --reports-gt or --findings-gt must be provided")
        sys.exit(1)

    logger.info("Running full pipeline: extract findings → evaluate")

    args.extract_mode = "infer"
    extract_findings.handle_extract_findings(args)

    eval_args = argparse.Namespace(
        results_dir=Path(args.output_dir) / constants.RESULTS_DIR,
        llm_judge=args.llm_judge,
        workers=getattr(args, "workers", 5),
        fewshot=getattr(args, "fewshot", None),
        reasoning=args.reasoning,
    )
    evaluate.handle_evaluate(eval_args)


if __name__ == "__main__":
    main()
