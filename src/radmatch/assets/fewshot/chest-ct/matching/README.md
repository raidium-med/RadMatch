# Matching few-shot examples (chest-ct)

Worked examples of the alignment patterns Stage 2 has to get right. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Laterality flip + status flip + severity flip + measurement diff |
| `example_2.json` | 1:N umbrella — pred enumerates spinal levels covering multiple GT atoms |
| `example_3.json` | N:1 umbrella — atomic pred pulmonary nodules covering one umbrella GT |
| `example_4.json` | Constructed clinical long tail — bulla vs pneumothorax (two readings of one abnormality), scarring synonyms, sub-threshold node, post-lobectomy state, a negative that does not deny other entities |
| `example_5.json` | Constructed — translated vocabulary (light transmission area, density and cord-like shadows), 'no metastatic disease' denies the suspicious nodules |
| `example_6.json` | Constructed — aortic segments matched segment to segment, per-vessel calcium grid as one finding, clot burden inside the PE finding, residual thymus vs thymoma (two readings), leftovers across systems not paired |
| `example_7.json` | Constructed — negatives matched only to what they deny ('no mass' vs millimetric nodules, calibre vs plaque, pleural vs pericardial, qualified 'no suspicious nodule'), a real denial and a cardiothoracic-ratio equivalence |

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
Stage 2 sees only the `finding_id`, `text`, `clinical_status` and `laterality` of each finding
(`radmatch.llm_utils.prompts.matching_view`) and each match row as `reasoning`, `pred_id`, `gt_id`;
the `comparison` and `measurements` kept in the files are not sent. Each `reasoning` is one plain
clause. `scenario` and `description` are documentation; the loader ignores them.
