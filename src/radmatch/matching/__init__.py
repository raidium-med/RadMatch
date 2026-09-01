"""Stage 2 — batched matching.

Aligns predicted findings with ground-truth findings using a single LLM
call per report pair. The output (`MatchingOutput`) becomes the input
to Stage 3 scoring.

Public entry points:
- `match_findings` — per-pair (used internally by `match_dataset`).
- `match_dataset` — dataset-level orchestrator that writes
  `matching/<series>.json` per pair under `output_dir`.

Internal modules:
- `utils` — private helpers: validation, canonical ordering, message
  building, JSON schema, type aliases (`Match`, `MatchingOutput`).
- `inference` — the public entry points above.
"""

from radmatch.matching.inference import match_dataset, match_findings
from radmatch.matching.utils import Match, MatchingOutput

__all__ = ["Match", "MatchingOutput", "match_dataset", "match_findings"]
