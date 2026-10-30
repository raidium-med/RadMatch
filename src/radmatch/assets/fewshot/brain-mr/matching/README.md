# Matching few-shot examples (brain-mr)

Three worked examples of the alignment patterns Stage 2 has to get right. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Status flip on cortical sulci + sinus normal denying mucosal thickening + a one-region pred statement covering two gt statements (1:N) |
| `example_2.json` | 1:N umbrella — pred parent-anatomy negative covering several GT rule-out atoms |
| `example_3.json` | N:1 umbrella — atomic pred WMH findings covering one umbrella GT |

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
