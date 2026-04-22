"""Handler for evaluate command."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

from radmatch.evaluation import eval

logger = logging.getLogger(__name__)


def handle_evaluate(args: argparse.Namespace) -> None:
    """Handle evaluate command."""
    eval.evaluate_findings(
        result_dir=Path(args.results_dir),
        model_name=getattr(args, "llm_judge", "gpt-5-4"),
        workers=getattr(args, "workers", 5),
        fewshot=getattr(args, "fewshot", None),
        reasoning=args.reasoning,
    )
