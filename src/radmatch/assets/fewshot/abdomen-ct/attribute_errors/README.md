# Attribute-errors few-shot examples (abdomen-ct)

Stage 3b examples, most derived from the matches of an `abdomen-ct/matching/example_N.json`. A status-inversion pair reaches Stage 3b too and expects `[]` (prompt rule 1): the inversion is scored upstream.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | No free-text attribute errors — comparison flip on mesenteric LN and ratio diff on portal vein are owned by Stage 3a deterministic |
| `example_2.json` | findings_gt + findings_pred example_2 | No free-text attribute errors on the consolidated hematoma + active-bleeding match |
| `example_3.json` | findings_gt + findings_pred example_3 | Minor diagnosis error on the hepatic-cyst pair (pred gives only the density for a cyst that is not actionable) + minor measurement error (pred leaves out the 9 mm size of a simple hepatic cyst); CBD prior size 6 vs 5 mm under every threshold, no error |
| `example_4.json` | matching/example_6 | Constructed clinical long tail — a stone with its size and consequence judged against its group (no error), hypodense vs a hepatic cyst minor diagnosis (not actionable), diverticulosis vs diverticulitis major diagnosis, small vs large ascites major severity |
| `example_5.json` | constructed | Left-out air-fluid levels and mild grade on small bowel dilatation major, added obstruction major (diagnosis); hedged fracture major; two certainty steps major; Bosniak II vs IIF major; 'possibly' on a definite negative two certainty steps major; a 9 mm duct after cholecystectomy normal on both sides, no error |
| `example_6.json` | constructed | Major extent for an invented SBO transition point / closed loop, solitary vs multiple metastases and SMA abutment vs encasement; major diagnosis for acute vs chronic fracture (the age); splenule (normal variant) vs node no Stage 3b error (status inversion, scored upstream); major character for gas in a collection; predominant diverticulosis segment minor extent, added hernia content no error |
| `example_7.json` | constructed | Bilateral vs one side no site error (Stage 3a `laterality`) + left-out grade major, left-out size major (the left-out side is `laterality`'s), umbrella with no site vs located lesions major site per pair, more detail no error, bilateral pred vs left + right gt no error, density word vs a cystic pancreatic lesion major character, left-out simple-cyst size minor, invented change on diverticulosis no error, cause hedge no error, one-step grade difference minor, a side only the pred gives no site error (Stage 3a `laterality`) |

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

Status inversions (a normal finding matched to an abnormal one) are scored upstream; the few pairs here with one expect `[]`.
