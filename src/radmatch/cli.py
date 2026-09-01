#!/usr/bin/env python3
"""`radmatch` subcommands — one per stage, plus `run_all` and the optional
`extract_indications` preprocessor.

Stages hand off on disk: `findings_{gt,pred}/<series>.json` → `matching/<series>.json`
→ `attribute_errors/<series>.json` + `metrics_summary.json`, so each is independently
runnable. Handlers here are thin shims over the Python API.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import radmatch
from radmatch import constants
from radmatch.matching import inference as matching_inference
from radmatch.scoring import inference as scoring_inference

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


# ============================================================================
# Handlers — one per subcommand. Thin Namespace → public API adapters.
# ============================================================================


def handle_extract_findings(args: argparse.Namespace) -> None:
    if not args.reports_gt and not args.findings_gt:
        logger.error("Either --reports-gt or --findings-gt must be provided")
        sys.exit(1)
    radmatch.extract_findings(
        reports_gt_dir=Path(args.reports_gt) if args.reports_gt else None,
        reports_pred_dir=Path(args.reports_pred),
        output_dir=Path(args.output_dir),
        llm_extractor=args.llm_extractor,
        fewshot=args.fewshot,
        workers=args.workers,
        limit=args.limit,
        findings_gt_dir=Path(args.findings_gt) if args.findings_gt else None,
        reasoning=args.reasoning,
        indications_dir=Path(args.indications) if args.indications else None,
    )


def handle_match(args: argparse.Namespace) -> None:
    results_dir = Path(args.results_dir)
    radmatch.match_dataset(
        findings_gt_dir=results_dir / constants.FINDINGS_GT_DIR,
        findings_pred_dir=results_dir / constants.FINDINGS_PRED_DIR,
        output_dir=results_dir,
        llm_judge=args.llm_judge,
        fewshot=args.fewshot,
        workers=args.workers,
        reasoning=args.reasoning,
        indications_dir=Path(args.indications) if args.indications else None,
        max_match_retries=args.match_retries,
        retry_degraded=args.retry_degraded,
    )


def handle_score(args: argparse.Namespace) -> None:
    results_dir = Path(args.results_dir)
    radmatch.score_dataset(
        findings_gt_dir=results_dir / constants.FINDINGS_GT_DIR,
        findings_pred_dir=results_dir / constants.FINDINGS_PRED_DIR,
        matching_dir=results_dir / constants.MATCHING_DIR,
        output_dir=results_dir,
        llm_judge=args.llm_judge,
        fewshot=args.fewshot,
        workers=args.workers,
        reasoning=args.reasoning,
        indications_dir=Path(args.indications) if args.indications else None,
        max_score_retries=args.score_retries,
        retry_degraded=args.retry_degraded,
    )


def handle_run_all(args: argparse.Namespace) -> None:
    if not args.reports_gt and not args.findings_gt:
        logger.error("Either --reports-gt or --findings-gt must be provided")
        sys.exit(1)
    if args.indications and args.extract_indications:
        logger.error("--indications and --extract-indications are mutually exclusive")
        sys.exit(1)
    radmatch.run_all(
        reports_pred_dir=Path(args.reports_pred),
        output_dir=Path(args.output_dir),
        llm_extractor=args.llm_extractor,
        llm_judge=args.llm_judge,
        reports_gt_dir=Path(args.reports_gt) if args.reports_gt else None,
        findings_gt_dir=Path(args.findings_gt) if args.findings_gt else None,
        fewshot=args.fewshot,
        workers=args.workers,
        limit=args.limit,
        reasoning=args.reasoning,
        indications_dir=Path(args.indications) if args.indications else None,
        auto_extract_indications=args.extract_indications,
        max_match_retries=args.match_retries,
        max_score_retries=args.score_retries,
        retry_passes=args.retry_passes,
        retry_degraded=args.retry_degraded,
    )


def handle_extract_indications(args: argparse.Namespace) -> None:
    radmatch.extract_indications(
        reports_dir=Path(args.reports),
        output_dir=Path(args.output_dir),
        llm_extractor=args.llm_extractor,
        workers=args.workers,
        reasoning=args.reasoning,
    )


# ============================================================================
# Argparse wiring
# ============================================================================


_INDICATIONS_HELP = (
    "Optional directory of per-series indication .txt files "
    "(typically produced by `radmatch extract_indications`). When supplied, the "
    "indication is injected as context into every LLM stage."
)


def _add_extraction_arguments(parser: argparse.ArgumentParser) -> None:
    """Stage 1 arguments — shared by `extract_findings` and `run_all`."""
    parser.add_argument("--reports-gt", help="Directory containing ground truth report .txt files")
    parser.add_argument("--reports-pred", required=True, help="Directory containing predicted report .txt files")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--llm-extractor", required=True, help="LLM model name for finding extraction")
    parser.add_argument("--fewshot", default=None, help="Name of few-shot example set to load (optional)")
    parser.add_argument("--workers", type=int, default=15, help="Number of concurrent workers (default: 15)")
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
    parser.add_argument("--indications", default=None, help=_INDICATIONS_HELP)


def _add_judge_arguments(parser: argparse.ArgumentParser) -> None:
    """Stage 2 / Stage 3 arguments — shared by `match` and `score`."""
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Results directory containing findings_gt/ and findings_pred/",
    )
    parser.add_argument("--llm-judge", required=True, help="LLM model name for the judge")
    parser.add_argument("--workers", type=int, default=15, help="Number of concurrent workers (default: 15)")
    parser.add_argument("--fewshot", default=None, help="Name of few-shot example set to load (optional)")
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Reasoning effort for LLM models (default: none)",
    )
    parser.add_argument("--indications", default=None, help=_INDICATIONS_HELP)


def _add_match_retry_argument(parser: argparse.ArgumentParser) -> None:
    """Stage 2 retry budget. Outside the matching cache fingerprint, so changing it
    does not invalidate results already on disk."""
    parser.add_argument(
        "--match-retries",
        type=int,
        default=matching_inference.DEFAULT_MAX_RETRIES,
        help=(
            "Extra Stage 2 attempts on a malformed matching reply before falling back to "
            f"the valid subset (default: {matching_inference.DEFAULT_MAX_RETRIES})"
        ),
    )


def _add_score_retry_argument(parser: argparse.ArgumentParser) -> None:
    """Stage 3b retry budget. Outside the attribute-errors cache fingerprint."""
    parser.add_argument(
        "--score-retries",
        type=int,
        default=scoring_inference.DEFAULT_MAX_RETRIES,
        help=(
            "Extra Stage 3b attempts on a malformed attribute-errors reply before dropping "
            f"the report's text errors (default: {scoring_inference.DEFAULT_MAX_RETRIES})"
        ),
    )


def _add_retry_degraded_argument(parser: argparse.ArgumentParser) -> None:
    """Revisit reports that fell back rather than failed. Off by default: a fallback
    writes valid cached output, so retrying it re-pays the LLM cost every run."""
    parser.add_argument(
        "--retry-degraded",
        action="store_true",
        help=(
            "Recompute reports whose cached result fell back — a Stage 2 validation "
            "fallback or a degraded Stage 3b payload (default: reuse them)"
        ),
    )


def _add_indication_extraction_arguments(parser: argparse.ArgumentParser) -> None:
    """Arguments for the optional `extract_indications` preprocessor."""
    parser.add_argument("--reports", required=True, help="Directory of report .txt files")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write per-series indication .txt files into",
    )
    parser.add_argument("--llm-extractor", required=True, help="LLM model name for indication extraction")
    parser.add_argument("--workers", type=int, default=15, help="Number of concurrent workers (default: 15)")
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Reasoning effort for LLM models (default: none)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radmatch",
        description="Radiology report generation evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline (Stage 1 → 2 → 3)
  radmatch run_all \\
    --reports-gt /path/to/gt --reports-pred /path/to/pred \\
    --output-dir /path/to/output \\
    --llm-extractor gpt-5.2 --llm-judge gpt-5.2 --workers 20 --fewshot chest-ct

  # Or one stage at a time, reusing the previous stage's output
  radmatch extract_findings --reports-gt ... --reports-pred ... --output-dir ... \\
    --llm-extractor gpt-5.2
  radmatch match --results-dir /path/to/output/radmatch_results --llm-judge gpt-5.2
  radmatch score --results-dir /path/to/output/radmatch_results --llm-judge gpt-5.2
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    parser_extract = sub.add_parser("extract_findings", help="Stage 1 — extract findings from reports")
    _add_extraction_arguments(parser_extract)
    parser_extract.set_defaults(func=handle_extract_findings)

    parser_match = sub.add_parser("match", help="Stage 2 — match predicted vs ground-truth findings")
    _add_judge_arguments(parser_match)
    _add_match_retry_argument(parser_match)
    _add_retry_degraded_argument(parser_match)
    parser_match.set_defaults(func=handle_match)

    parser_score = sub.add_parser("score", help="Stage 3 — score the alignment produced by Stage 2")
    _add_judge_arguments(parser_score)
    _add_score_retry_argument(parser_score)
    _add_retry_degraded_argument(parser_score)
    parser_score.set_defaults(func=handle_score)

    parser_run_all = sub.add_parser("run_all", help="Run full pipeline: extract → match → score")
    _add_extraction_arguments(parser_run_all)
    parser_run_all.add_argument("--llm-judge", required=True, help="LLM model name for the judge")
    parser_run_all.add_argument(
        "--extract-indications",
        action="store_true",
        help=(
            "Auto-extract study indications before Stage 1 and use them as context "
            "(written to <output-dir>/radmatch_results/indications/). Mutually "
            "exclusive with --indications."
        ),
    )
    _add_match_retry_argument(parser_run_all)
    _add_score_retry_argument(parser_run_all)
    _add_retry_degraded_argument(parser_run_all)
    parser_run_all.add_argument(
        "--retry-passes",
        type=int,
        default=1,
        help=(
            "Run the extract → match → score chain up to N times, so a later pass picks up "
            "reports that dropped. Stops early once nothing is missing (default: 1)"
        ),
    )
    parser_run_all.set_defaults(func=handle_run_all)

    parser_indications = sub.add_parser(
        "extract_indications",
        help="Optional preprocessor — extract study indications from reports into per-series .txt files",
    )
    _add_indication_extraction_arguments(parser_indications)
    parser_indications.set_defaults(func=handle_extract_indications)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
