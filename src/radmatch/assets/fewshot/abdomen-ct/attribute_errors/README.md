# Attribute-errors few-shot examples (abdomen-ct)

Three Stage 3b examples, each derived from the matches of the corresponding `abdomen-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | No free-text attribute errors — comparison flip on mesenteric LN and ratio diff on portal vein are owned by Stage 3a deterministic |
| `example_2.json` | matching/example_2 | No free-text attribute errors on the consolidated hematoma + active-bleeding match |
| `example_3.json` | matching/example_3 | Minor certainty error on hepatic-cyst pair (gt 'cyst' definite vs pred 'small hypodense focus' hedged); CBD prior-measurement diff is Stage 3a |

## Format

Each file is one example:

```json
{
  "scenario": "...",
  "description": "...",
  "user":      { "series_uuid": "...", "pairs": [{"pred_finding": {...}, "gt_finding": {...}}, ...] },
  "assistant": { "errors_per_match": [[...], [...], ...] }
}
```

`user` and `assistant` are stored as raw JSON objects (parsed dicts at load time). `radmatch.llm_utils.prompts.load_attribute_errors_fewshot` reads these files when `--fewshot abdomen-ct` is passed, and the Stage 3b message builder serialises each side at construction time.

INC pairs (clinical_status mismatches) are excluded upstream in `evaluate_attribute_errors_batched`, so all pairs in these examples have matching `clinical_status` on both sides.
