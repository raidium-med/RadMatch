# Matching few-shot examples (abdomen-ct)

Nine worked examples of the alignment patterns Stage 2 has to get right. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | 1:1 matches + comparison flip on actionable nodes |
| `example_2.json` | 1:N umbrella — pred parent-anatomy claim covering several GT atoms |
| `example_3.json` | N:1 umbrella — multiple atomic pred cysts covering one umbrella GT |
| `example_4.json` | SPU + MIS — a pred finding the GT never assesses, and a GT finding with no pred counterpart |
| `example_5.json` | 1:1 match despite a measurement difference |
| `example_6.json` | Constructed clinical long tail — stone with the hydroureteronephrosis it causes (1:N), hypodense lesion vs cyst and diverticulosis vs diverticulitis (two readings), bowel segments not matched |
| `example_7.json` | Constructed — 'fast-in fast-out', 'low-density shadow', 'no metastatic disease' and 'no source of hematuria' as denials, post-cholecystectomy duct |
| `example_8.json` | Constructed — splenule vs splenic hilar node (two readings), a variant beside 'no lymphadenopathy', diverticulosis beside 'no diverticulitis', SBO with and without transition point, leftovers across organs not paired |
| `example_9.json` | Constructed — negatives matched only to what they deny ('no hydronephrosis' vs a nonobstructing stone, patency vs plaque, a named vein vs another vein, 'no peritoneal disease' vs pneumatosis), real denials of ascites, free air and a venous thrombosis |

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
`clinical_status`, `laterality`, `comparison`, `measurements` — since significance plays no part in
aligning findings. `scenario` and `description` are documentation; the loader ignores them.
