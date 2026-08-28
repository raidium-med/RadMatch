#!/usr/bin/env python3
"""Build the per-report parquet index for the dashboard.

Reads `per_report_metrics/<series>.json` (written by RadMatch's `score_pair`)
and produces `aux/report_index.parquet` — one row per series with the metrics
the dashboard filters and sorts on.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from radmatch import constants, io
from radmatch.dashboard.common import constants as dashboard_constants

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _flatten(metrics: dict[str, object]) -> dict[str, float | int | bool]:
    """One row per series, with the columns the dashboard needs for filtering / sort."""
    muc = metrics.get("muc_counts") or {}
    safety = metrics.get("clinical_safety_summary") or {}
    return {
        "actionable_errors": int(metrics.get("actionable_errors_total") or 0),
        "triage_recall": safety.get("triage_recall") or 0.0,
        "actionable_recall": safety.get("actionable_recall") or 0.0,
        "triage_precision": safety.get("triage_precision") or 0.0,
        "actionable_precision": safety.get("actionable_precision") or 0.0,
        **{f"muc_{cat.lower()}": int(muc.get(cat, 0)) for cat in constants.MUC_CATEGORIES},
    }


def _per_finding_attributes(*finding_sets: list[dict]) -> dict[str, list[str]]:
    """Distinct clinical_significance / measurement category / comparison values
    across one or more finding lists (typically GT + Pred). Empty lists are kept
    rather than None so pyarrow serialises them as list<string>; the dashboard
    filter treats empty as "no match". Predicted-side hallucinations with an
    actionable significance or a measurement must show up in the filters too,
    so both sides feed in."""
    significances: set[str] = set()
    measurements: set[str] = set()
    comparisons: set[str] = set()
    for findings in finding_sets:
        for f in findings:
            if not isinstance(f, dict):
                continue
            sig = f.get("clinical_significance")
            if isinstance(sig, str) and sig:
                significances.add(sig)
            for m in f.get("measurements") or []:
                if isinstance(m, dict):
                    cat = m.get("category")
                    if isinstance(cat, str) and cat:
                        measurements.add(cat)
            comp = f.get("comparison")
            if isinstance(comp, str) and comp:
                comparisons.add(comp)
    return {
        "clinical_significances": sorted(significances),
        "measurement_types": sorted(measurements),
        "comparisons": sorted(comparisons),
    }


def _match_scopes(matching: dict | None) -> list[str]:
    """Distinct `match_scope` values across the report's matches (drives the
    Match Scope filter). Empty list when the report has no matches."""
    if not isinstance(matching, dict):
        return []
    scopes: set[str] = set()
    for m in matching.get("matches", []) or []:
        if isinstance(m, dict):
            s = m.get("match_scope")
            if isinstance(s, str) and s:
                scopes.add(s)
    return sorted(scopes)


def build_report_index(radmatch_dir: Path) -> pd.DataFrame:
    """Walk `per_report_metrics/*.json` (+ matching `findings_gt/*.json`) and
    produce one row per series. Includes filter columns derived from per-finding
    attributes so the dashboard can multiselect without re-reading JSON."""
    per_report_dir = radmatch_dir / "per_report_metrics"
    findings_gt_dir = radmatch_dir / "findings_gt"
    findings_pred_dir = radmatch_dir / "findings_pred"
    matching_dir = radmatch_dir / "matching"
    if not per_report_dir.exists():
        return pd.DataFrame()

    def _load_findings_list(directory: Path, stem: str) -> list[dict]:
        loaded = io.load_json(directory / f"{stem}.json", raise_on_error=False) or []
        return loaded if isinstance(loaded, list) else []

    rows: list[dict[str, object]] = []
    for path in tqdm(sorted(per_report_dir.glob("*.json")), desc="Building index"):
        data = io.load_json(path, raise_on_error=False)
        if not isinstance(data, dict):
            continue
        gt_findings = _load_findings_list(findings_gt_dir, path.stem)
        pred_findings = _load_findings_list(findings_pred_dir, path.stem)
        matching_data = io.load_json(matching_dir / f"{path.stem}.json", raise_on_error=False)
        rows.append(
            {
                "report_id": path.stem,
                **_flatten(data),
                **_per_finding_attributes(gt_findings, pred_findings),
                "match_scopes": _match_scopes(matching_data),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the dashboard's per-report parquet index.")
    parser.add_argument("--results-dir", type=Path, required=True, help="Parent dir containing radmatch_results/.")
    args = parser.parse_args()

    parent = args.results_dir.expanduser().resolve()
    radmatch_dir = (
        parent
        if parent.name == dashboard_constants.RADMATCH_RESULTS_DIR
        else parent / dashboard_constants.RADMATCH_RESULTS_DIR
    )
    if not radmatch_dir.exists():
        logger.error("radmatch_results/ not found at %s", radmatch_dir)
        return

    df = build_report_index(radmatch_dir)
    if df.empty:
        logger.warning("No per_report_metrics found under %s — nothing to index", radmatch_dir)
        return

    aux_dir = radmatch_dir / constants.AUX_DIR
    aux_dir.mkdir(parents=True, exist_ok=True)
    out_path = aux_dir / "report_index.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info("Wrote %d rows to %s", len(df), out_path)


if __name__ == "__main__":
    main()
