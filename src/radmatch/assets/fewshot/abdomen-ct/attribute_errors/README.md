# Attribute-errors few-shot examples (abdomen-ct)

Stage 3b examples, most derived from the matches of an `abdomen-ct/matching/example_N.json`. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); a few such pairs stay here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Hepatic veins are patent vs Hepatic veins patent: no error; Three mesenteric lymph nodes… vs Three mesenteric lymph nodes…: no error |
| `example_3.json` | findings_gt + findings_pred example_3 | Small hypodense focus within the… vs Cyst in the right hepatic lobe…: diagnosis minor, measurement minor |
| `example_4.json` | matching/example_6 | 4 mm left UVJ stone causing mild… vs 4 mm left UVJ calculus: no error; 4 mm left UVJ stone causing mild… vs Mild left hydroureteronephrosis: no error; Sigmoid diverticulosis vs Sigmoid diverticulitis with…: diagnosis major; Aortic calcification vs Atherosclerotic calcification of…: no error; Small amount of ascites vs Large-volume ascites: severity major |
| `example_5.json` | constructed | Small bowel dilatation up to 3.8… vs Mild small bowel dilatation up to…: character minor, severity minor, diagnosis major; Possible minimally displaced… vs Minimally displaced right…: certainty major; Bosniak IIF left renal cyst vs Bosniak II left renal cyst: severity major; Gallbladder normal, possibly… vs Gallbladder normal without…: certainty minor |
| `example_6.json` | constructed | Closed-loop small bowel… vs Small bowel obstruction; no…: extent major; Solitary 2.1 cm hepatic… vs Multiple hepatic metastases, the…: extent major; Acute L1 compression fracture vs Chronic L1 compression deformity: diagnosis major; 1.2 cm splenule at the splenic… vs 1.2 cm soft-tissue nodule at the…: no error; Patchy hepatic steatosis in the… vs Diffuse hepatic steatosis: site minor; 2.0 cm hemangioma in liver… vs 1.4 cm hemangioma in liver…: measurement minor |
| `example_7.json` | constructed | Bilateral hydronephrosis vs Moderate left hydronephrosis: severity minor; Adrenal nodule vs 1.4 cm left adrenal nodule: measurement major; Multiple splenic hypodensities vs 8 mm hypodensity in the splenic…: site minor, measurement minor; Multiple splenic hypodensities vs 5 mm hypodensity near the splenic…: site minor, measurement minor; Hypodense lesion in the… vs Cystic lesion in the pancreatic…: character minor; Increased colonic diverticulosis vs Colonic diverticulosis: no error; Large hiatal hernia vs Moderate hiatal hernia: severity minor; Left inguinal hernia containing fat vs Inguinal hernia: no error; Right paracolic gutter fluid… vs Right paracolic gutter fluid…: character major; Colonic mass vs Sigmoid colon mass: site major |

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
