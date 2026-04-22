"""Handler for extract_findings command."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

from radmatch.finding_extraction import (
    extract_findings,
    extract_findings_batch_retrieve,
    extract_findings_batch_status,
    extract_findings_batch_submit,
)

logger = logging.getLogger(__name__)


def handle_extract_findings(args: argparse.Namespace) -> None:
    """Handle extract_findings command."""
    if args.extract_mode == "infer":
        _handle_infer(args)
    elif args.extract_mode == "infer_batch":
        _handle_infer_batch(args)
    else:
        logger.error(f"Invalid extract_mode: {args.extract_mode}")
        sys.exit(1)


def _handle_infer(args: argparse.Namespace) -> None:
    """Handle single inference mode."""
    reports_gt = getattr(args, "reports_gt", None)
    findings_gt = getattr(args, "findings_gt", None)
    if not reports_gt and not findings_gt:
        logger.error("Either --reports-gt or --findings-gt must be provided")
        sys.exit(1)

    extract_findings(
        reports_gt_dir=Path(reports_gt) if reports_gt else None,
        reports_pred_dir=Path(args.reports_pred),
        output_dir=Path(args.output_dir),
        model_name=args.llm_extractor,
        fewshot=args.fewshot,
        workers=args.workers,
        limit=args.limit,
        findings_gt_dir=Path(findings_gt) if findings_gt else None,
        reasoning=args.reasoning,
    )


def _handle_infer_batch(args: argparse.Namespace) -> None:
    """Handle batch inference mode."""
    if args.batch_action == "submit":
        _handle_batch_submit(args)
    elif args.batch_action == "retrieve":
        _handle_batch_retrieve(args)
    elif args.batch_action == "status":
        _handle_batch_status(args)
    else:
        logger.error(f"Invalid batch_action: {args.batch_action}")
        sys.exit(1)


def _handle_batch_submit(args: argparse.Namespace) -> None:
    """Handle batch submit action."""
    reports_gt = getattr(args, "reports_gt", None)
    findings_gt = getattr(args, "findings_gt", None)
    if not reports_gt and not findings_gt:
        logger.error("Either --reports-gt or --findings-gt must be provided")
        sys.exit(1)

    extract_findings_batch_submit(
        reports_gt_dir=Path(reports_gt) if reports_gt else None,
        reports_pred_dir=Path(args.reports_pred),
        output_dir=Path(args.output_dir),
        model_name=args.llm_extractor,
        fewshot=args.fewshot,
        limit=args.limit,
        findings_gt_dir=Path(findings_gt) if findings_gt else None,
        reasoning=args.reasoning,
    )


def _handle_batch_retrieve(args: argparse.Namespace) -> None:
    """Handle batch retrieve action."""
    extract_findings_batch_retrieve(
        output_dir=Path(args.output_dir),
        job_id=getattr(args, "job_id", None),
    )


def _handle_batch_status(args: argparse.Namespace) -> None:
    """Handle batch status action."""
    extract_findings_batch_status(
        output_dir=Path(args.output_dir),
        job_id=getattr(args, "job_id", None),
    )
