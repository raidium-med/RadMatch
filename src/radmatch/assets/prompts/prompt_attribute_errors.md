## TASK

For each matched pair of findings (pred vs gt), list the attribute errors: how the pred finding's description differs from the gt finding's. Judge only the dimensions of §2. `clinical_status`, comparison labels, and counts, ratios and attenuation are scored deterministically upstream: do not repeat them. Sizes and changes over time are flagged upstream; you grade the ones that matter (§2 `measurement` and `comparison`).

Input: a JSON object with `series_uuid` (context only), an optional study `indication`, and `pairs`: a list of `{"pair_id": <int>, "pred_finding": {...}, "gt_finding": {...}}`, numbered from 1. Each finding has the standard fields (`text`, `clinical_status`, `clinical_significance`, etc.). When one finding was matched to several on the other side, the pair also carries `same_group_pred` / `same_group_gt`: the texts of the other findings in its match group.

---

## 1. DECISION RULES (apply to every pair)

1. **Status inversion → no errors.** If one finding is normal and the other abnormal, return `"errors": []` for that pair: the inversion is scored upstream.
2. **Judge the pair against its group.** Report errors of the pair's own two findings under its own `pair_id`. Within a group, a gt detail that another pred finding of the group states is not missing, and pred content that describes another gt finding of the group is not an error for this pair ("bilateral hydronephrosis" vs a left and a right hydronephrosis: no location error on either pair). An umbrella pred that does not state this gt finding's own side, site, level or size has left it out (rule 3): pred "enlarged mediastinal lymph nodes" vs gt "12 mm right paratracheal node" → `location` major.
3. **Leaving a detail out is an error; adding one is not.** A detail the gt gives that the pred leaves out (side, lobe, segment, level, site, severity grade, subtype or character) is an error of that dimension, graded `major`: pred "atelectasis" vs gt "right middle lobe atelectasis" → `location` major; pred "emphysema" vs gt "centrilobular emphysema" → `morphology` major. A pred more detailed than the gt is not an error (pred "consolidation in the posterior basal segment of the right lower lobe" vs gt "right lower lobe consolidation" → `[]`). A detail the exam already implies is not missing ("aortic calcification" on an abdominal CT). A pair where neither side gives anything beyond the bare anatomy + pathology → `[]`.
4. **Grade each error** with the `severity` field:
   - `"major"`: the two descriptions are mutually exclusive AND the difference changes management or referenced anatomy; a gt detail the pred leaves out (rule 3); almost every `location` error (§2).
   - `"minor"`: both findings give the detail and differ only slightly, so a clinician would not be misled (mild vs moderate).
5. **Do not invent differences.** When the two findings give the same detail in different words, do not emit. An omitted gt detail is not a case of doubt.

---

## 2. DIMENSIONS

Use only these six `dimension` names.

**`location`**: anatomic placement, including laterality (left / right) and sub-anatomic detail (lobe / segment / quadrant / zone).
A location error is major in almost every case.
- major: a laterality flip (left ↔ right); bilateral ↔ one side, for any finding, unless another finding of the group gives the other side (pred "bibasilar atelectasis" vs gt "left basilar atelectasis"; pred "right lower lobe opacity" vs gt "bilateral lower lobe opacities"), where a gt whose wording covers both sides ("the lung bases", "the kidneys", "the hila") counts as bilateral; a side only one of the two findings gives, either way (pred "pleural effusion" vs gt "left pleural effusion"; pred "left inguinal hernia" vs gt "inguinal hernia"); a different lobe, segment, level, quadrant, station or organ part; a gt location the pred leaves out (no side, no lobe, the whole organ for a gt segment, a class of lesions for a located one); sites the pred adds that neither the gt nor the group has; extension to another organ.
- minor (the exceptions): two words for the same site that a reader could not tell apart ("left base" vs "left lower lobe"); a diffuse or multi-site process whose predominant site differs.
- no error: the same site; a pred more precise than the gt (a segment of the gt lobe; the lingula for gt "left upper lobe"); a clearly midline structure (aorta, IVC, SVC, heart, esophagus, trachea, bladder, prostate, uterus, vertebrae, rectum) with no sub-anatomic detail differing.

**`severity`**: qualitative magnitude: mild / moderate / severe, small / large, mass extent, percentage effacement.
- major: a change of structured category that changes management, even one step apart (Bosniak II vs IIF, Lung-RADS 3 vs 4A, BI-RADS, LI-RADS); a change that crosses a clinical-action threshold: grades two steps apart (minimal or mild ↔ marked or severe, trace ↔ large); a grade the gt gives that the pred leaves out (pred "splenomegaly" vs gt "marked splenomegaly").
- minor: one step apart (mild ↔ moderate, small ↔ moderate, moderate ↔ large); any difference of hepatic steatosis grade (CT grading is imprecise and does not drive management).
- no error: neither side uses a descriptor, both use the same one or near-synonyms, or only the pred gives one.

**`morphology`**: shape, margin, character: spiculated vs smooth, irregular vs well-defined, solid vs cystic.
- major: spiculated vs smooth on a mass; one lesion vs several (a solitary vs multiple metastases); a change of tissue composition that changes the differential (benign-pattern calcification vs none, solid vs ground-glass, cystic vs solid, fat vs fluid, pleural fluid vs pleural thickening); a different diagnosis for the same abnormality (bulla vs pneumothorax, atelectasis vs pneumonia, diverticulosis vs diverticulitis, cyst vs solid tumor); spiculation, cavitation or macroscopic fat that pred adds to a nodule gt describes without it; a character, subtype or composition the gt gives that the pred leaves out (pred "emphysema" vs gt "centrilobular emphysema"); a composition the gt gives that the pred states only as a density (pred "hypodense lesion" vs gt "cyst": hypodense, low-attenuation and hyperdense describe density, not composition).
- minor: "ill-defined" vs "hazy"; "infiltrate" vs "consolidation" at the same site.
- no error: neither side describes shape, margin or character, or only the pred does; the pred names the diagnosis of what the gt describes (pred "bronchiectasis" vs gt "dilated bronchi"): more detail, not a different diagnosis.

**`certainty`**: diagnostic certainty / hedging: definite vs probable vs possible vs cannot-rule-out.
- Ladder: consistent with / diagnostic of > suspicious for / probably > possibly / may represent / versus artifact > less likely > unlikely.
- major: two or more steps apart: gt "enlarged pulmonary artery, may reflect pulmonary hypertension" vs pred "diagnostic of pulmonary hypertension"; pred "possible rib fracture" vs gt "rib fracture".
- minor: one step apart ("probable" vs "consistent with").
- no error: both findings use the same hedging level, or both are unhedged. A hedge on what the finding is counts: gt "haze, possibly pulmonary edema" is a possible edema, so a definite edema is two steps away. Only a hedge on why it is there leaves the finding itself definite: "possibly related to", "likely due to", "probably secondary to", or a hedged cause word ("likely reactive", "possibly post-operative").

**`measurement`**: sizes (`measurements`, or written in the text), judged against the structure and context (finding text, `clinical_significance`, `indication`).
- major: a gt size the pred leaves out (rule 3), unless the pred gives a size class or bound that covers it ("tiny" or "millimetric" for a gt under 6 mm, "subcentimeter" under 10 mm, "< 5 mm" for 4 mm, "enlarged" for a lymph node over 10 mm) or another pred of the group gives the size; a difference that crosses a decision threshold of the structure: lung nodule 6 and 8 mm (Fleischner), lymph node short axis 10 mm, thoracic aorta 4 and 5.5 cm, abdominal aorta 3 and 5.5 cm, spleen 13 cm, common bile duct 6 mm (10 mm after cholecystectomy), pancreatic duct 3 mm; a difference of more than 20 % and at least 2 mm on any other measured finding (a mass 3.0 vs 4.0 cm).
- minor: a difference or a left-out size on a simple renal, hepatic or splenic cyst (no follow-up at any size); a smaller difference that stays on one side of every threshold.
- no error: the same value; a size only the pred gives; a size class or bound that covers the gt value.

**`comparison`**: only a change over time the pred states and the gt does not give ("new", "increased", "enlarging" vs no comparison); every other comparison difference is scored upstream.
- major: on a finding followed by its size or number: a nodule, mass, lymph node, aneurysm or dilated aorta, effusion, metastasis.
- no error: on any other finding.

---

## 3. OUTPUT

Return only a JSON object with one key, `errors_per_pair`: one entry `{"pair_id": <int>, "errors": [...]}` for every input pair, each `pair_id` exactly once. A pair without errors has `"errors": []`; no pairs → `{"errors_per_pair": []}`. Every error has a `dimension` from §2, a `severity` of `"major"` or `"minor"`, and a short, non-empty `reasoning` (one clause). Other dimension or severity values are dropped downstream. No text outside the JSON, no markdown fences.

```json
{
  "errors_per_pair": [
    {"pair_id": 1, "errors": [
      {"dimension": "location", "severity": "major", "reasoning": "pred says right lower lobe, gt says left lower lobe"}
    ]},
    {"pair_id": 2, "errors": []},
    {"pair_id": 3, "errors": [
      {"dimension": "severity", "severity": "minor", "reasoning": "pred says mild-to-moderate, gt says moderate"}
    ]}
  ]
}
```

Output only the JSON object now.
