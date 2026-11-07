# Matching few-shot examples (abdomen-us)

Four worked examples of the alignment patterns Stage 2 has to get right: three built from the abdomen-us report pairs, one constructed. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Status flip on portal flow direction + hedged diagnosis + MIS |
| `example_2.json` | 1:1 matches on a pelvic ultrasound: fibroid layer, cyst size, two normal statements |
| `example_3.json` | Pertinent negative as a status flip + laterality flip + SPU + MIS |
| `example_4.json` | Constructed — an organ-level normal denying a lesion and matching a size statement, pole shift, bladder wall, ureteral jets vs a stone |

## Format

Each file is one example:

```json
{
  "scenario": "...",
  "description": "...",
  "user":      { "indication": "...", "pred_findings": [...], "gt_findings": [...] },
  "assistant": { "matches": [...], "unmatched_pred": [...], "unmatched_gt": [...] }
}
```

`radmatch.llm_utils.prompts.load_matching_fewshot` reads every `example_*.json` here and
appends each `user` / `assistant` pair to the matching prompt as one user/assistant turn.
Stage 2 sees only the `finding_id`, `text`, `clinical_status` and `laterality` of each finding
(`radmatch.llm_utils.prompts.matching_view`) and each match row as `reasoning`, `pred_id`, `gt_id`;
the `comparison` and `measurements` kept in the files are not sent. Each `reasoning` is one plain
clause. `indication` is optional, as in live calls, where it is sent only when the study has one.
`scenario` and `description` are documentation; the loader ignores them.
