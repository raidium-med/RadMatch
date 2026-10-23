## TASK

For each matched pair of findings (pred vs gt), list the attribute errors: how the pred finding's description differs from the gt finding's. Judge only the five dimensions of §2. `clinical_status`, `comparison` and routine measurement differences (large differences, omissions, units, counts, attenuation) are scored deterministically upstream: do not repeat them.

Input: a JSON object with `series_uuid` (context only), an optional study `indication`, and `pairs`: a list of `{"pair_id": <int>, "pred_finding": {...}, "gt_finding": {...}}`, numbered from 1. Each finding has the standard fields (`text`, `clinical_status`, `clinical_significance`, etc.). When one finding was matched to several on the other side, the pair also carries `same_group_pred` / `same_group_gt`: the texts of the other findings in its match group.

---

## 1. DECISION RULES (apply to every pair)

1. **Status inversion → no errors.** If one finding is normal and the other abnormal, return `"errors": []` for that pair: the inversion is scored upstream.
2. **Judge the pair against its group.** Report errors of the pair's own two findings under its own `pair_id`. Within a group, a gt detail that another pred finding of the group states is not missing, and pred content that describes another gt finding of the group is not an error for this pair.
3. **Only a real difference is an error.** Silence is not a contradiction: a detail one side gives and the other does not mention (sub-site, extent, severity, morphology) is no error, or `minor` when the omitted detail would matter to a clinician (pred "atelectasis" vs gt "right middle lobe atelectasis" → at most `minor`); `major` needs two descriptions that exclude each other. A pair where neither side describes anything beyond the bare anatomy + pathology → `[]`.
4. **Grade each error** with the `severity` field:
   - `"major"`: the two descriptions are mutually exclusive AND the difference changes management or referenced anatomy.
   - `"minor"`: pred describes the same finding less precisely or differently, but a clinician would not be misled.
5. **When unsure, do not emit.** The metric uses these errors multiplicatively; spurious errors compound.

---

## 2. DIMENSIONS

Use only these five `dimension` names.

**`location`**: anatomic placement, including laterality (left / right) and sub-anatomic detail (lobe / segment / quadrant / zone).
- major: a laterality flip (left ↔ right) on a paired or asymmetric structure, always; unilateral ↔ bilateral, or extension to another organ, for a process managed by side or extent (pneumonia, consolidation, effusion, pneumothorax, a nodule or mass, metastases, embolism); a different liver segment or lobe for an indeterminate, suspicious or treated lesion; spinal levels two or more apart without overlap.
- minor: a location that covers the gt site plus extra sites in the same lung or organ, or the dominant gt site but not a lesser one; unilateral ↔ bilateral for linear, plate-like or dependent atelectasis, minor scarring, a set of small (< 6 mm) non-suspicious nodules or simple cysts; a different liver segment for a benign lesion (simple cyst, typical hemangioma); an adjacent spinal level.
- no error: a sub-site of the named lobe or organ (the lingula is part of the left upper lobe); both findings describe a clearly midline structure (aorta, IVC, SVC, heart, esophagus, trachea, bladder, prostate, uterus, vertebrae, rectum) and no sub-anatomic detail differs.

**`severity`**: qualitative magnitude: mild / moderate / severe, small / large, mass extent, percentage effacement.
- major: a change that crosses a clinical-action threshold: grades two steps apart (minimal or mild ↔ marked or severe, trace ↔ large).
- minor: mild ↔ moderate; any difference of hepatic steatosis grade (CT grading is imprecise and does not drive management).
- no error: neither side uses a descriptor, or both use the same one or near-synonyms.

**`morphology`**: shape, margin, character: spiculated vs smooth, irregular vs well-defined, solid vs cystic.
- major: spiculated vs smooth on a mass; a change of tissue composition that changes the differential (benign-pattern calcification vs none, solid vs ground-glass, cystic vs solid, fat vs fluid, pleural fluid vs pleural thickening); a different diagnosis for the same abnormality (bulla vs pneumothorax, atelectasis vs pneumonia, diverticulosis vs diverticulitis, cyst vs solid tumor); spiculation, cavitation or macroscopic fat that pred adds to a nodule gt describes without it.
- minor: "ill-defined" vs "hazy"; an attenuation word against a composition word ("hypodense lesion" vs "cyst"): hypodense, low-attenuation and hyperdense describe density, not composition; "infiltrate" vs "consolidation" at the same site.
- no error: neither side describes shape, margin or character.

**`certainty`**: diagnostic certainty / hedging: definite vs probable vs possible vs cannot-rule-out.
- Ladder: consistent with / diagnostic of > suspicious for / probably > possibly / may represent / versus artifact > less likely > unlikely.
- major: two or more steps apart on a finding whose work-up depends on it: gt "enlarged pulmonary artery, may reflect pulmonary hypertension" vs pred "diagnostic of pulmonary hypertension".
- minor: one step apart ("probable" vs "consistent with").
- no error: both findings use the same hedging level, or both are unhedged.

**`measurement`**: only a difference that looks numerically small yet crosses a clinical decision boundary for this specific structure, judged in context (finding text, `clinical_significance`, `indication`). Most pairs have none.
- major: the pred value would change the clinical interpretation. Spleen 13.0 cm (normal) vs 13.5 cm (splenomegaly): only ~4 % apart, but across the splenomegaly threshold. Aorta 4.9 → 5.4 cm near a surgical threshold; lymph node 9 → 11 mm across the pathologic short-axis cut-off.
- minor: a borderline difference unlikely to change management.
- no error: both values carry the same clinical interpretation (10.0 vs 10.5 mm nodule, both "small, routine follow-up"); the difference is large or obvious (scored upstream); or you are unsure whether a boundary is crossed.

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
