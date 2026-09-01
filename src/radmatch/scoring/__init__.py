"""Stage 3 — score the alignment produced by Stage 2.

Three sub-stages: `comparators` (3a, deterministic), `inference` (3b, one batched LLM
call per report for the free-text dimensions), `metrics` (3c, MUC classification and
aggregation). `score_pair` and `score_dataset` are the entry points.
"""

from radmatch.scoring.pipeline import score_dataset, score_pair

__all__ = ["score_dataset", "score_pair"]
