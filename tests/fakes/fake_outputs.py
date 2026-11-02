"""Fake RadMatch output blocks for the dashboard tests."""


def tier_block(errors=0, fn=0, recall=1.0, precision=1.0, gt_total=1, pred_total=1, n_reports=None) -> dict:
    """A `tiers.<name>` block; MIS-only FN and SPU-only FP keep the sub-splits consistent."""
    block = {
        "significance": ["critical"],
        "errors_total": errors,
        "fn_total": fn,
        "fp_total": errors - fn,
        "fn_mis_total": fn,
        "fn_inc_total": 0,
        "fp_spu_total": errors - fn,
        "fp_inc_total": 0,
        "findings_total": max(errors, gt_total),
        "errors_per_finding": errors / max(errors, gt_total),
        "recall": recall,
        "recall_hits": round(recall * gt_total),
        "gt_total": gt_total,
        "precision": precision,
        "precision_hits": round(precision * pred_total),
        "pred_total": pred_total,
    }
    if n_reports:
        per_report = {f"{k}_per_report": block[f"{k}_total"] / n_reports for k in ("errors", "fn", "fp")}
        block = {**per_report, **block}
    return block
