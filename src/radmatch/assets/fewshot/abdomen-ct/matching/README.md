# Matching few-shot examples (abdomen-ct)

Five worked examples of the alignment patterns Stage 2 has to get right. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Direct matches + comparison flip on actionable nodes |
| `example_2.json` | 1:N aggregate — pred parent-anatomy claim covering several GT atoms |
| `example_3.json` | N:1 aggregate — multiple atomic pred cysts covering one umbrella GT |
| `example_4.json` | SPU + MIS — a pred finding the GT never assesses, and a GT finding with no pred counterpart |
| `example_5.json` | Direct match despite a measurement difference |

## Format

Each file is one example:

```json
{
  "scenario": "...",
  "description": "...",
  "user":      { "pred_findings": [...], "gt_findings": [...] },
  "assistant": { "matches": [...], "unmatched_pred": [...], "unmatched_gt": [...] }
}
```

`radmatch.llm_utils.prompts.load_matching_fewshot` reads every `example_*.json` here and
appends each `user` / `assistant` pair to the matching prompt as one user/assistant turn.
Findings carry only the fields matching consumes — `finding_id`, `text`,
`clinical_status`, `comparison`, `measurements` — since significance plays no part in
aligning findings. `scenario` and `description` are documentation; the loader ignores them.
