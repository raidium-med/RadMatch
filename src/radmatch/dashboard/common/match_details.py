"""Detail-panel renderers for the selected-finding tuplet.

Extracted from `pages/1-Results_Explorer.py` to keep that page focused on
filter / column / selection orchestration. The single public entry point is
`render_selected_finding_panel`; everything else here is helper-private.
"""

from __future__ import annotations

import html
from typing import Sequence

import streamlit as st

from radmatch import constants as radmatch_constants
from radmatch.dashboard.common import shared
from radmatch.scoring import metrics as _scoring_metrics

_TRIAGE_TIERS = frozenset(radmatch_constants.TRIAGE_SIGNIFICANCE_TIERS)
_ACTIONABLE_TIERS = frozenset(radmatch_constants.ACTIONABLE_SIGNIFICANCE_TIERS)

_CELL_STYLE = (
    "padding:0.5rem 0.6rem;vertical-align:top;border:1px solid #fcd34d;"
    "background:#fffbeb;font-size:0.92rem;color:#1f2937;"
)
_HEADER_STYLE = (
    "padding:0.3rem 0.6rem;background:#fde68a;color:#92400e;font-size:0.72rem;"
    "font-weight:600;text-transform:uppercase;letter-spacing:0.04em;text-align:left;"
    "border:1px solid #fcd34d;"
)
_ERROR_COLOR = {"clean": "#15803d", "minor": "#b45309", "major": "#991b1b"}


def render_selected_finding_panel(
    info: shared.PerPairMatchInfo,
    selected_finding: dict[str, object] | None,
    *,
    is_gt: bool,
    gt_idx: dict[str, shared.PerPairMatchInfo],
    pred_idx: dict[str, shared.PerPairMatchInfo],
    gt_findings_by_id: dict[str, dict[str, object]],
    pred_findings_by_id: dict[str, dict[str, object]],
) -> None:
    """Inline yellow card showing the selection's connected component (tuplet).

    Tuplet-canonical: selecting any finding in the same connected component
    produces the same findings table + match list. Only the conclusion tracks
    the selected finding.
    """
    selected_id = str((selected_finding or {}).get("finding_id", ""))
    gt_id_set, pred_id_set = _connected_component(selected_id, is_gt, gt_idx, pred_idx)
    gt_ids = sorted(gt_id_set)
    pred_ids = sorted(pred_id_set)

    title_html = (
        "<div style='font-weight:700;font-size:1.0rem;color:#92400e;"
        "text-transform:uppercase;letter-spacing:0.04em;margin-bottom:0.4rem;'>"
        "Matching Details"
        "</div>"
    )

    findings_table = _render_findings_table(
        gt_ids=gt_ids,
        pred_ids=pred_ids,
        gt_findings_by_id=gt_findings_by_id,
        pred_findings_by_id=pred_findings_by_id,
    )

    category = info.category
    matches = _enumerate_tuplet_matches(gt_ids, gt_idx)

    if category in ("MIS", "SPU"):
        absence = "No matching finding in predictions." if category == "MIS" else "No matching finding in ground truth."
        match_sections = f"<div style='margin-top:0.7rem;font-size:0.93rem;color:#1f2937;'>{html.escape(absence)}</div>"
    elif len(matches) == 1:
        match_sections = _render_match_inline(matches[0]["cp"])
    else:
        sections: list[str] = []
        n = len(matches)
        for i, m in enumerate(matches, start=1):
            pair_text = (
                f"{html.escape(shared.format_finding_id(m['gt_id'], is_gt=True))}"
                f" → {html.escape(shared.format_finding_id(m['pred_id'], is_gt=False))}"
            )
            sections.append(_render_match_details(m["cp"], pair_text=pair_text, index=i, total=n))
        match_sections = "".join(sections)

    conclusion = _finding_level_conclusion(info, selected_finding or {}, is_gt_side=is_gt)

    st.markdown(
        f"<div class='selected-panel'>"
        f"  {title_html}"
        f"  {findings_table}"
        f"  {match_sections}"
        f"  {conclusion}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _connected_component(
    start_id: str,
    start_is_gt: bool,
    gt_idx: dict[str, shared.PerPairMatchInfo],
    pred_idx: dict[str, shared.PerPairMatchInfo],
) -> tuple[set[str], set[str]]:
    """BFS over the bipartite match graph: returns (gt_ids, pred_ids) reachable
    from the seed. Covers 1:1, 1:N, N:1, and any N:M components."""
    gt_set: set[str] = set()
    pred_set: set[str] = set()
    queue: list[tuple[str, bool]] = [(start_id, start_is_gt)]
    while queue:
        fid, is_gt = queue.pop()
        target = gt_set if is_gt else pred_set
        if fid in target:
            continue
        target.add(fid)
        info = (gt_idx if is_gt else pred_idx).get(fid)
        if info is None:
            continue
        other_set = pred_set if is_gt else gt_set
        for cp in info.counterparts:
            if cp.counterpart_id not in other_set:
                queue.append((cp.counterpart_id, not is_gt))
    return gt_set, pred_set


def _enumerate_tuplet_matches(
    gt_ids: Sequence[str],
    gt_idx: dict[str, shared.PerPairMatchInfo],
) -> list[dict[str, object]]:
    """All match edges within the tuplet, deduped by (gt_id, pred_id)."""
    seen: set[tuple[str, str]] = set()
    matches: list[dict[str, object]] = []
    for gid in gt_ids:
        info = gt_idx.get(gid)
        if info is None:
            continue
        for cp in info.counterparts:
            key = (gid, cp.counterpart_id)
            if key in seen:
                continue
            seen.add(key)
            matches.append({"gt_id": gid, "pred_id": cp.counterpart_id, "cp": cp})
    return matches


def _render_findings_table(
    *,
    gt_ids: list[str],
    pred_ids: list[str],
    gt_findings_by_id: dict[str, dict[str, object]],
    pred_findings_by_id: dict[str, dict[str, object]],
) -> str:
    """Two-column GT / Pred table for a tuplet. Singleton side rowspans; N:M
    falls back to side-by-side rows."""

    def _text(findings_by_id: dict[str, dict[str, object]], fid: str) -> str:
        return html.escape((findings_by_id.get(fid) or {}).get("text", "") or "—")

    empty_cell = f"<td style='{_CELL_STYLE}color:#9ca3af;'>—</td>"

    if not gt_ids and not pred_ids:
        body = f"<tr>{empty_cell}{empty_cell}</tr>"
    elif not gt_ids:
        body = "".join(
            f"<tr>{empty_cell}<td style='{_CELL_STYLE}'>{_text(pred_findings_by_id, pid)}</td></tr>" for pid in pred_ids
        )
    elif not pred_ids:
        body = "".join(
            f"<tr><td style='{_CELL_STYLE}'>{_text(gt_findings_by_id, gid)}</td>{empty_cell}</tr>" for gid in gt_ids
        )
    elif len(gt_ids) == 1 and len(pred_ids) >= 1:
        gt_cell = f"<td rowspan='{len(pred_ids)}' style='{_CELL_STYLE}'>{_text(gt_findings_by_id, gt_ids[0])}</td>"
        rows = [f"<tr>{gt_cell}<td style='{_CELL_STYLE}'>{_text(pred_findings_by_id, pred_ids[0])}</td></tr>"]
        rows += [f"<tr><td style='{_CELL_STYLE}'>{_text(pred_findings_by_id, pid)}</td></tr>" for pid in pred_ids[1:]]
        body = "".join(rows)
    elif len(pred_ids) == 1 and len(gt_ids) >= 1:
        pred_cell = f"<td rowspan='{len(gt_ids)}' style='{_CELL_STYLE}'>{_text(pred_findings_by_id, pred_ids[0])}</td>"
        rows = [f"<tr><td style='{_CELL_STYLE}'>{_text(gt_findings_by_id, gt_ids[0])}</td>{pred_cell}</tr>"]
        rows += [f"<tr><td style='{_CELL_STYLE}'>{_text(gt_findings_by_id, gid)}</td></tr>" for gid in gt_ids[1:]]
        body = "".join(rows)
    else:
        # N:M (rare): list each side independently; pad the shorter side.
        n_rows = max(len(gt_ids), len(pred_ids))
        rows = []
        for i in range(n_rows):
            gt_cell_html = (
                f"<td style='{_CELL_STYLE}'>{_text(gt_findings_by_id, gt_ids[i])}</td>"
                if i < len(gt_ids)
                else empty_cell
            )
            pred_cell_html = (
                f"<td style='{_CELL_STYLE}'>{_text(pred_findings_by_id, pred_ids[i])}</td>"
                if i < len(pred_ids)
                else empty_cell
            )
            rows.append(f"<tr>{gt_cell_html}{pred_cell_html}</tr>")
        body = "".join(rows)

    return (
        "<table style='width:100%;border-collapse:collapse;margin-top:0.65rem;table-layout:fixed;'>"
        "<thead><tr>"
        f"<th style='width:50%;{_HEADER_STYLE}'>GT</th>"
        f"<th style='width:50%;{_HEADER_STYLE}'>Pred</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
    )


def _conclusion_header(info: shared.PerPairMatchInfo, is_hit: bool, n_total: int) -> str:
    category = info.category
    if category == "MIS":
        return "Not predicted → <b>MIS</b>"
    if category == "SPU":
        return "Hallucinated, no GT counterpart → <b>SPU</b>"
    if n_total <= 1:
        if category == "COR":
            return "Matched, no attribute errors → <b>COR</b>"
        if category == "PAR":
            return "Matched, only minor attribute errors → <b>PAR</b>"
        return "Matched but materially wrong → <b>INC</b>"
    # N:N
    if is_hit:
        return f"Identified correctly by ≥1 of {n_total} matches → <b>{category}</b>"
    if sum(1 for cp in info.counterparts if cp.category == "INC") == n_total:
        return f"All {n_total} matches are INC → <b>INC</b>"
    return f"All {n_total} matches use generic boilerplate → <b>miss</b>"


def _finding_level_conclusion(
    info: shared.PerPairMatchInfo,
    finding: dict[str, object],
    *,
    is_gt_side: bool,
) -> str:
    """Outcome header + bullets showing ±impact on actionable_errors,
    triage / actionable recall + precision — computed from the finding's
    tier AND the side it sits on (recall is GT-only, precision is pred-only,
    so a pred-side SPU never enters recall and a GT-side MIS never enters
    precision)."""
    sig = str(finding.get("clinical_significance") or "")
    is_triage = sig in _TRIAGE_TIERS
    is_actionable = sig in _ACTIONABLE_TIERS
    # Recall lives on the GT side, precision on the pred side: a pred SPU only moves
    # actionable_errors / precision, and a GT MIS says nothing about precision.
    pred_side_no_recall = not is_gt_side and info.category == "SPU"
    gt_side_no_precision = is_gt_side and info.category == "MIS"

    counterparts = info.counterparts
    if info.category in ("MIS", "SPU"):
        is_hit = False
    elif counterparts:
        is_hit = any(
            _scoring_metrics.is_credited_match(
                category=cp.category, match_scope=cp.match_scope, gt_actionable=is_actionable
            )
            for cp in counterparts
        )
    else:
        is_hit = False

    headline = _conclusion_header(info, is_hit, len(counterparts))
    credited = bool(counterparts and is_hit)
    actionable_err = 1 if (is_actionable and not credited) else 0

    def _out_of_pool(reason: str | None = None) -> str:
        msg = reason or f"{sig or 'no significance'}, not in pool"
        return f"— <span style='color:#6b7280;'>({msg})</span>"

    def _recall_cell(in_pool: bool) -> str:
        if pred_side_no_recall:
            return _out_of_pool("pred-side, no GT recall impact")
        if not in_pool:
            return _out_of_pool()
        if is_hit:
            return "+1 hit"
        return "+0 hit <span style='color:#6b7280;'>(recall miss)</span>"

    def _precision_cell(in_pool: bool) -> str:
        if gt_side_no_precision:
            return _out_of_pool("GT-side, no pred precision impact")
        if not in_pool:
            return _out_of_pool()
        if is_hit:
            return "+1 hit"
        return "+0 hit <span style='color:#6b7280;'>(precision miss)</span>"

    actionable_errors_cell = _out_of_pool() if not is_actionable else f"+{actionable_err}"

    bullets = (
        f"<li><code>actionable_errors</code> {actionable_errors_cell}</li>"
        f"<li><code>triage_precision</code>: {_precision_cell(is_triage)}</li>"
        f"<li><code>triage_recall</code>: {_recall_cell(is_triage)}</li>"
        f"<li><code>actionable_precision</code>: {_precision_cell(is_actionable)}</li>"
        f"<li><code>actionable_recall</code>: {_recall_cell(is_actionable)}</li>"
    )
    return (
        "<div style='font-weight:600;font-size:0.85rem;color:#92400e;"
        "margin-top:0.85rem;margin-bottom:0.2rem;'>Conclusion</div>"
        f"<div style='font-size:0.85rem;color:#1f2937;font-weight:600;'>{headline}</div>"
        f"<ul style='margin:0.25rem 0 0 0;padding-left:1.2rem;font-size:0.82rem;color:#1f2937;'>{bullets}</ul>"
    )


def _match_body(cp: "shared.CounterpartMatchInfo", *, with_scope_in_header: bool) -> str:
    """Reasoning + attribute table; shared between 1:1 inline and N:N <details>."""
    scope_badge = shared.build_match_scope_badge(cp.match_scope) if with_scope_in_header else ""
    reasoning = html.escape(cp.match_reasoning or "(no reasoning recorded)")
    attribute_table = _attribute_errors_html_for_pair(cp)
    return (
        f"<div style='display:flex;align-items:center;gap:0.4rem;font-weight:600;font-size:0.82rem;"
        f"color:#92400e;margin-bottom:0.25rem;'>"
        f"<span>Matching Reasoning</span>{scope_badge}"
        f"</div>"
        f"<div style='color:#1f2937;font-size:0.92rem;'>{reasoning}</div>"
        f"{attribute_table}"
    )


def _render_match_inline(cp: "shared.CounterpartMatchInfo") -> str:
    return f"<div style='margin-top:0.7rem;'>{_match_body(cp, with_scope_in_header=True)}</div>"


def _render_match_details(
    cp: "shared.CounterpartMatchInfo",
    *,
    pair_text: str,
    index: int,
    total: int,
) -> str:
    """Collapsible <details> per N:N match.
    Summary: `Match X of Y  [pill]  GT01 → Pred01  [scope]  ▾`."""
    summary = (
        "<summary style='cursor:pointer;list-style:none;padding:0.45rem 0.6rem;"
        "border:1px solid #fcd34d;border-radius:0.3rem;background:#fffbeb;"
        "display:flex;align-items:center;gap:0.4rem;'>"
        f"<span style='font-weight:600;font-size:0.82rem;color:#92400e;'>Match {index} of {total}</span>"
        f"{shared.render_outcome_pill(cp.category)}"
        f"<span style='color:#374151;font-size:0.82rem;font-weight:600;'>{pair_text}</span>"
        f"{shared.build_match_scope_badge(cp.match_scope)}"
        "<span style='margin-left:auto;color:#92400e;font-size:0.75rem;'>▾</span>"
        "</summary>"
    )
    body = f"<div style='padding:0.5rem 0.6rem 0.3rem 0.6rem;'>{_match_body(cp, with_scope_in_header=False)}</div>"
    return f"<details style='margin-top:0.5rem;'>{summary}{body}</details>"


def _attribute_errors_html_for_pair(cp: "shared.CounterpartMatchInfo") -> str:
    """All 7 attribute dimensions × per-dim severity. Major > minor > clean
    precedence per dimension."""
    severity_rank = {"major": 2, "minor": 1, "clean": 0}
    by_dim: dict[str, dict[str, str]] = {}
    for err in list(cp.structured_errors) + list(cp.text_errors):
        dim = str(err.get("dimension", ""))
        sev = str(err.get("severity", ""))
        existing = by_dim.get(dim)
        if existing and severity_rank.get(existing["error"], 0) >= severity_rank.get(sev, 0):
            continue
        by_dim[dim] = {"error": sev, "reasoning": str(err.get("reasoning", ""))}

    rows_html: list[str] = []
    for dim in shared.DIMENSION_DISPLAY_ORDER:
        entry = by_dim.get(dim, {"error": "clean", "reasoning": ""})
        severity = entry["error"]
        color = _ERROR_COLOR.get(severity, "#374151")
        rows_html.append(
            f"<tr style='border-top:1px solid #fde68a;'>"
            f"<td style='padding:0.3rem 0.55rem;'>{html.escape(dim)}</td>"
            f"<td style='padding:0.3rem 0.55rem;color:{color};font-weight:600;'>"
            f"{html.escape(severity)}</td>"
            f"<td style='padding:0.3rem 0.55rem;font-size:0.82rem;color:#374151;'>"
            f"{html.escape(entry['reasoning'])}</td>"
            f"</tr>"
        )

    return (
        "<div style='font-weight:600;font-size:0.85rem;color:#92400e;"
        "margin-top:0.7rem;margin-bottom:0.25rem;'>Attribute Errors</div>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>"
        "<thead><tr style='text-align:left;color:#6b7280;font-size:0.72rem;text-transform:uppercase;"
        "letter-spacing:0.02em;'>"
        "<th style='padding:0.3rem 0.55rem;'>Dimension</th>"
        "<th style='padding:0.3rem 0.55rem;'>Error</th>"
        "<th style='padding:0.3rem 0.55rem;'>Reasoning</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
