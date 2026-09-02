"""RadMatch — LLM-based evaluation framework for radiology report generation.

`run_all` chains the three stages over a directory of reports; the per-stage functions
run them individually, each caching to disk so a costly earlier stage is reused.
See README.md.
"""

from __future__ import annotations

from radmatch.finding_extraction.inference import ExtractionStats, extract_findings
from radmatch.indication_extraction.inference import extract_indications
from radmatch.llm_utils.llm_clients import assert_credentials_for
from radmatch.matching.inference import MatchingContext, match_dataset, match_findings
from radmatch.pipeline_runner import run_all
from radmatch.scoring.pipeline import ScoringContext, score_dataset, score_pair

__all__ = [
    "ExtractionStats",
    "MatchingContext",
    "ScoringContext",
    "assert_credentials_for",
    "extract_findings",
    "extract_indications",
    "match_dataset",
    "match_findings",
    "run_all",
    "score_dataset",
    "score_pair",
]
