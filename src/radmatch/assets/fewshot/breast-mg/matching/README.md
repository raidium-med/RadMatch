# Matching few-shot examples (breast-mg)

Four worked examples of the alignment patterns Stage 2 has to get right: three built from the breast-mg report pairs, one constructed. Findings use placeholder ids (`p_1`, `gt_1`) rather than real report ids, so each example is self-contained.

| File | Scenario |
|------|----------|
| `example_1.json` | Clock position shift + BI-RADS category change + node negative as a status flip + two right breast negatives |
| `example_2.json` | Laterality flip (no same-side counterpart) + new vs stable + left-out quadrant |
| `example_3.json` | Size difference on a known cancer + a qualified negative that does not deny probably benign calcifications (SPU) + a missed second lesion (MIS) |
| `example_4.json` | Constructed — a normal statement about a breast surgically removed, fibroadenoma umbrella 1:N, mass vs focal asymmetry, node negative vs an enlarged node, 'no suspicious calcifications' vs dystrophic calcifications |

Stage 1 conventions for mammography: the BI-RADS sentence "no suspicious mass, calcifications or architectural distortion" is kept as one finding with the ruled-out diagnosis it defines ("no mammographic evidence of malignancy"), under the row "a ruled-out diagnosis and its defining negative signs"; a BI-RADS assessment category stays in the text of the finding it is assigned to (the recommendation is dropped); "which may obscure small masses" after the breast density is an examination-quality hedge and is dropped. Stage 2: "no suspicious X" is a qualified negative, so it does not deny a finding called probably benign (BI-RADS 3) or benign.

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
