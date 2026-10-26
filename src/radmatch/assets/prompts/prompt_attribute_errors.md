## TASK

For each matched pair of findings (pred vs gt), list the attribute errors: how the pred finding's description differs from the gt finding's. Judge only the dimensions of §2. `clinical_status` (normal vs abnormal), the side (`laterality`: left, right, bilateral), comparison labels, and counts, ratios and attenuation are scored deterministically upstream: do not repeat them. Sizes and changes over time are flagged upstream; you grade the ones that matter (§2 `measurement` and `comparison`).

Input: a JSON object with `series_uuid` (context only), an optional study `indication`, and `pairs`: a list of `{"pair_id": <int>, "pred_finding": {...}, "gt_finding": {...}}`, numbered from 1. Each finding has the standard fields (`text`, `clinical_status`, `clinical_significance`, etc.). When one finding was matched to several on the other side, the pair also carries `same_group_pred` / `same_group_gt`: the texts of the other findings in its match group.

---

## 1. DECISION RULES (apply to every pair)

1. **Status inversion → no errors.** If one finding is normal and the other abnormal, return `"errors": []` for that pair: the inversion is scored upstream.
2. **Judge the pair against its group.** Report errors of the pair's own two findings under its own `pair_id`. Within a group, a gt detail that another pred finding of the group states is not missing, and pred content that describes another gt finding of the group is not an error for this pair ("bilateral hydronephrosis" vs a left and a right hydronephrosis: no error on either pair). An umbrella pred that does not state this gt finding's own site, level or size has left it out (rule 3): pred "enlarged mediastinal lymph nodes" vs gt "12 mm right paratracheal node" → `site` major.
3. **Leaving a detail out is an error; adding one is not.** A detail the gt gives that the pred leaves out (lobe, segment, level, site, extent, severity grade, character, diagnosis, subtype or age; the side is scored upstream) is an error of that dimension, graded `major` unless the dimension's rules below make it `minor`: pred "atelectasis" vs gt "right middle lobe atelectasis" → `site` major. A pred more detailed than the gt is not an error (pred "consolidation in the posterior basal segment of the right lower lobe" vs gt "right lower lobe consolidation" → `[]`), except a clinical claim the gt does not support: an added complication, extension or actionable diagnosis is an error (§2 `extent`, `diagnosis`). A detail the exam already implies is not missing ("aortic calcification" on an abdominal CT). A pair where neither side gives anything beyond the bare anatomy + pathology → `[]`.
4. **Grade each error** with the `severity` field:
   - `"major"`: the two descriptions are mutually exclusive AND the difference changes management or referenced anatomy; a gt detail the pred leaves out (rule 3); almost every `site` error (§2).
   - `"minor"`: both findings give the detail and differ only slightly, so a clinician would not be misled (mild vs moderate); the minor cases each dimension lists.
5. **Do not invent differences.** When the two findings give the same detail in different words, do not emit. An omitted gt detail is not a case of doubt.
6. **One difference, one dimension.** Report each difference once, under the dimension whose definition it fits; the boundaries are given in §2.

---

## 2. DIMENSIONS

Use only these eight `dimension` names.

**`site`**: where the finding sits within the side: lobe, segment, zone, level, quadrant, station, organ part, vessel, device tip position. The side itself (left, right, bilateral) is scored upstream from each finding's `laterality`: never report a side difference, and judge two findings on different sides by their site alone (pred "right lower lobe" vs gt "left lower lobe" → `[]`; pred "right middle lobe" vs gt "left lower lobe" → a different lobe). How far the finding reaches is `extent`.
A site error is major in almost every case.
- major: a different lobe, segment, level, quadrant, station, organ part or vessel; a device tip in a different structure (pred "lower SVC" vs gt "upper right atrium"); a gt site the pred leaves out (no lobe, the whole organ for a gt segment, a class of lesions for a located one); sites the pred adds that neither the gt nor the group has.
- minor (the exceptions): two words for the same site that a reader could not tell apart ("left base" vs "left lower lobe").
- no error: the same site; a difference of side only; a pred more precise than the gt (a segment of the gt lobe; the lingula for gt "left upper lobe"); a clearly midline structure (aorta, IVC, SVC, heart, esophagus, trachea, bladder, prostate, uterus, vertebrae, rectum) with no sub-anatomic detail differing.

**`extent`**: how far and how many: one lesion vs several, focal vs multifocal vs diffuse, distribution and predominance, extension or invasion into a neighbouring structure, vascular involvement, mass effect, and complications (perforation, obstruction, abscess, rupture, herniation). A count given as a number is `measurement`; a grade word (mild, large) is `severity`.
- major: one lesion vs several (a solitary vs multiple metastases); confined vs extending or invading (abutment vs invasion of the mediastinum, abutment vs encasement of a vessel); extension to another organ; mass effect or a complication that only one of the two findings gives, also when the pred adds it (pred "closed-loop obstruction with a transition point" vs gt "small bowel obstruction").
- minor: a different predominant site or distribution of the same process ("sigmoid-predominant" vs "descending-colon-predominant" diverticulosis).
- no error: the same extent in different words.

**`severity`**: qualitative magnitude: mild / moderate / severe, small / large, percentage effacement, and structured categories.
- major: a change of structured category that changes management, even one step apart (Bosniak II vs IIF, Lung-RADS 3 vs 4A, BI-RADS, LI-RADS); a change that crosses a clinical-action threshold: grades two steps apart (minimal or mild ↔ marked or severe, trace ↔ large); a grade the gt gives that the pred leaves out (pred "splenomegaly" vs gt "marked splenomegaly").
- minor: one step apart (mild ↔ moderate, small ↔ moderate, moderate ↔ large); any difference of hepatic steatosis grade (CT grading is imprecise and does not drive management).
- no error: neither side uses a descriptor, both use the same one or near-synonyms, or only the pred gives one.

**`character`**: what the finding looks like: shape, margin, composition, density or signal, enhancement, calcification, fat, gas, cavitation, septa, air-fluid levels. What the finding is called is `diagnosis`.
- major: spiculated vs smooth on a mass; a composition or feature that changes the differential (benign-pattern calcification vs none, solid vs ground-glass, cystic vs solid, fat vs fluid, pleural fluid vs pleural thickening, enhancing vs non-enhancing); spiculation, cavitation or macroscopic fat that the pred adds to a nodule the gt describes without it; a feature that changes the differential and that only one of the two findings gives (gas in a collection; air-fluid levels in dilated bowel).
- minor: two words for nearly the same appearance ("ill-defined" vs "hazy").
- no error: neither side describes the appearance, or only the pred does without changing the differential.

**`diagnosis`**: what the abnormality is: the named entity, its subtype, its age (acute, subacute, chronic, healed), the cause of a secondary finding, the device type. The appearance is `character`, the hedge `certainty`, structured categories (Bosniak, Lung-RADS) `severity`; a change since a prior study is `comparison` ("new" is not "acute").
- major: two committed diagnoses that exclude each other and change management for the same abnormality (bulla vs pneumothorax, atelectasis vs pneumonia, diverticulosis vs diverticulitis, a normal variant vs a neoplasm, reactive vs malignant nodes, cyst vs solid tumor); a cause that changes management (pred "duct dilatation after cholecystectomy" vs gt "duct dilatation from a pancreatic head mass"); a subtype that changes management (type A vs type B dissection); acute vs chronic or healed (acute vs chronic emboli, acute vs healed fracture), and an "acute" the gt gives that the pred leaves out on a critical or urgent finding; an actionable gt diagnosis (pneumonia, abscess, malignancy, appendicitis, dissection, embolism) that the pred gives only as an appearance or a generic term (pred "opacity" vs gt "pneumonia"); an actionable diagnosis the pred adds that the gt does not support (pred "hepatic metastasis" vs gt "indeterminate hepatic lesion").
- minor: a generic term or an appearance for a gt diagnosis or subtype that is not actionable (pred "hypodense lesion" vs gt "simple cyst"; pred "emphysema" vs gt "centrilobular emphysema"); two names on one spectrum or with the same management ("infiltrate" vs "consolidation"); a different device type (PICC vs port); neighbouring ages (subacute vs acute, subacute vs chronic).
- no error: synonyms; the pred names the diagnosis of what the gt describes (pred "bronchiectasis" vs gt "dilated bronchi"); a pred differential that contains the gt diagnosis (a hedge: `certainty`); an age only the pred gives.

**`certainty`**: diagnostic certainty / hedging: definite vs probable vs possible vs cannot-rule-out.
- Ladder: consistent with / diagnostic of > suspicious for / probably > possibly / may represent / versus artifact > less likely > unlikely.
- major: two or more steps apart: gt "enlarged pulmonary artery, may reflect pulmonary hypertension" vs pred "diagnostic of pulmonary hypertension"; pred "possible rib fracture" vs gt "rib fracture".
- minor: one step apart ("probable" vs "consistent with").
- no error: both findings use the same hedging level, or both are unhedged. A hedge on what the finding is counts: gt "haze, possibly pulmonary edema" is a possible edema, so a definite edema is two steps away. Only a hedge on why it is there, or on what accentuates it, leaves the finding itself definite: "possibly related to", "likely due to", "probably secondary to", "likely from cardiac decompensation", "possibly accentuated by positioning", or a hedged cause word ("likely reactive", "possibly post-operative").

**`measurement`**: sizes (`measurements`, or written in the text), judged against the structure and context (finding text, `clinical_significance`, `indication`).
- major: a gt size the pred leaves out (rule 3), unless the pred gives a size class or bound that covers it ("tiny" or "millimetric" for a gt under 6 mm, "subcentimeter" under 10 mm, "< 5 mm" for 4 mm, "enlarged" for a lymph node over 10 mm) or another pred of the group gives the size; a difference that crosses a decision threshold of the structure: lung nodule 6 and 8 mm (Fleischner), lymph node short axis 10 mm, thoracic aorta 4 and 5.5 cm, abdominal aorta 3 and 5.5 cm, spleen 13 cm, common bile duct 6 mm (10 mm after cholecystectomy), pancreatic duct 3 mm; a difference of more than 20 % of the gt value and at least 2 mm on any other measured finding (a mass 3.0 vs 4.0 cm).
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
      {"dimension": "site", "severity": "major", "reasoning": "pred says right lower lobe, gt says right middle lobe"}
    ]},
    {"pair_id": 2, "errors": []},
    {"pair_id": 3, "errors": [
      {"dimension": "severity", "severity": "minor", "reasoning": "pred says mild-to-moderate, gt says moderate"}
    ]}
  ]
}
```

Output only the JSON object now.
