# Attribute-errors few-shot examples (abdomen-ct)

Six Stage 3b examples: two derived from the matches of `abdomen-ct/matching/` examples, one built from the abdomen-ct findings files, three constructed. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); a few such pairs stay here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Hepatic veins are patent vs Hepatic veins patent: no error; Three mesenteric lymph nodes… vs Three mesenteric lymph nodes…: no error |
| `example_3.json` | findings_gt + findings_pred example_3 | Small hypodense focus within the… vs Cyst in the right hepatic lobe…: diagnosis minor, measurement minor |
| `example_4.json` | matching/example_6 | 6 mm left renal pelvis stone… vs 6 mm calculus in the left renal…: no error; 6 mm left renal pelvis stone… vs Moderate left hydronephrosis: no error; Sigmoid diverticulosis vs Sigmoid diverticulitis with…: diagnosis major; Aortic calcification vs Atherosclerotic calcification of…: no error; Small amount of ascites vs Large-volume ascites: grade major |
| `example_5.json` | constructed | Small bowel dilatation up to 3.8… vs Mild small bowel dilatation up to…: appearance minor, grade minor, diagnosis major; Possible minimally displaced… vs Minimally displaced right…: certainty major; Bosniak IIF left renal cyst vs Bosniak II left renal cyst: grade major; No definite gallstones vs No gallstones: certainty minor |
| `example_6.json` | constructed | Closed-loop small bowel… vs Small bowel obstruction; no…: extent major; Solitary 2.1 cm hepatic… vs Multiple hepatic metastases, the…: extent major; Acute L1 compression fracture vs Chronic L1 compression deformity: diagnosis major; Patchy hepatic steatosis in the… vs Diffuse hepatic steatosis: location minor; 2.0 cm hemangioma in liver… vs 1.4 cm hemangioma in liver…: measurement minor |
| `example_7.json` | constructed | Bilateral hydronephrosis vs Moderate left hydronephrosis: grade minor; Adrenal nodule vs 1.4 cm left adrenal nodule: measurement major; Multiple splenic hypodensities vs 8 mm hypodensity in the splenic…: location minor, measurement minor; Multiple splenic hypodensities vs 5 mm hypodensity near the splenic…: location minor, measurement minor; Hypodense lesion in the… vs Cystic lesion in the pancreatic…: appearance minor; Increased colonic diverticulosis vs Colonic diverticulosis: no error; Large hiatal hernia vs Moderate hiatal hernia: grade minor; Left inguinal hernia containing fat vs Inguinal hernia: no error; Right paracolic gutter fluid… vs Right paracolic gutter fluid…: appearance major; Colonic mass vs Sigmoid colon mass: location major |

## Format

Each file is one example:

```json
{
  "scenario": "...",
  "description": "...",
  "user":      { "series_uuid": "...", "indication": "...", "pairs": [{"pair_id": 1, "pred_finding": {...}, "gt_finding": {...}}, ...] },
  "assistant": { "errors_per_pair": [{"pair_id": 1, "errors": [...]}, ...] }
}
```

`user` and `assistant` are stored as raw JSON objects (parsed dicts at load time). `radmatch.llm_utils.prompts.load_attribute_errors_fewshot` reads these files when `--fewshot abdomen-ct` is passed, and the Stage 3b message builder serialises each side at construction time.

`indication` is optional, as in live calls, where it is sent only when the study has one. Status inversions (a normal finding matched to an abnormal one) are scored upstream and never sent to the judge, so no example carries one.
