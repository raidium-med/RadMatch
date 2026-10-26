# Attribute-errors few-shot examples (abdomen-ct)

Stage 3b examples, most derived from the matches of an `abdomen-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | No free-text attribute errors — comparison flip on mesenteric LN and ratio diff on portal vein are owned by Stage 3a deterministic |
| `example_2.json` | matching/example_2 | No free-text attribute errors on the consolidated hematoma + active-bleeding match |
| `example_3.json` | matching/example_3 | Minor certainty error on hepatic-cyst pair (gt 'cyst' definite vs pred 'small hypodense focus' hedged); CBD prior-measurement diff is Stage 3a |
| `example_4.json` | matching/example_6 | Constructed clinical long tail — a stone with its consequence judged against its group (no error), hypodense vs cyst minor, diverticulosis vs diverticulitis major morphology, small vs large ascites major severity |
| `example_5.json` | constructed | Added diagnosis (obstruction) and hedged fracture major; two certainty steps major; Bosniak II vs IIF major; hedged incidental negative minor; post-cholecystectomy duct no error |
| `example_6.json` | constructed | Major for an invented SBO transition point / closed loop, solitary vs multiple metastases, SMV abutment vs SMA encasement, acute vs chronic fracture, splenule vs node, gas in a collection; diverticulosis segment and small-hernia content minor |

## Format

Each file is one example:

```json
{
  "scenario": "...",
  "description": "...",
  "user":      { "series_uuid": "...", "pairs": [{"pair_id": 1, "pred_finding": {...}, "gt_finding": {...}}, ...] },
  "assistant": { "errors_per_pair": [{"pair_id": 1, "errors": [...]}, ...] }
}
```

`user` and `assistant` are stored as raw JSON objects (parsed dicts at load time). `radmatch.llm_utils.prompts.load_attribute_errors_fewshot` reads these files when `--fewshot abdomen-ct` is passed, and the Stage 3b message builder serialises each side at construction time.

INC pairs (clinical_status mismatches) are excluded upstream in `evaluate_attribute_errors_batched`, so all pairs in these examples have matching `clinical_status` on both sides.
