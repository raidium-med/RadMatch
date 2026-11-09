# Matching few-shot examples (msk-xr)

Four worked examples of the alignment patterns Stage 2 has to get right: three built from the msk-xr report pairs, one constructed. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Missed fracture as a status flip + grade diff + SPU variant + MIS |
| `example_2.json` | Fracture placed in a neighbouring bone + two normal statements + SPU |
| `example_3.json` | 1:1 matches on an arthroplasty follow-up: a device, a measured lucency, a dropped change |
| `example_4.json` | Constructed — pubic rami fractures on the other side 1:N, a hip negative denying a fracture, a variant below a qualified negative, a degenerative umbrella vs a vertebral fracture |

Stage 1 laterality conventions: a finding takes the laterality its sentence or its section header gives ("Left knee:" in example 4). In a study of one limb whose laterality the EXAMINATION line gives, an abnormality also takes that laterality, and a normal statement without a side word in its sentence or header stays `null` ("No periprosthetic fracture." in a right hip study). Findings of the spine take `null`: the spine is unpaired.

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
