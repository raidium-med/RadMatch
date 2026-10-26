## TASK

Align the findings of a predicted report (pred) with the findings of a ground-truth report (gt). Decide which pred finding and which gt finding describe the same observation, and which findings stay unmatched on either side. Do not score correctness and do not flag status conflicts: every difference inside a match is scored downstream.

Input: `pred_findings` and `gt_findings`. Each finding has `finding_id` (an opaque string; pred ids usually start with `p_`, gt ids with `gt_`), `text`, `clinical_status` (`"normal"` / `"abnormal"`), `clinical_significance`, `comparison` and `measurements`.

---

## 1. WHEN A pred FINDING AND A gt FINDING MATCH

They match when they describe the same observation: the same organ or anatomic entity and the same pathology. Each match row carries a short `reasoning` (one clause); if that reasoning would say the pathology or the structure differs, do not match.

**Match despite these differences:**
- **Status.** pred "No pneumothorax" vs gt "Moderate pneumothorax" → match (one pneumothorax assessment; scored downstream as a status inversion).
- **Side or sub-site.** Same organ and pathology, different side / lobe / segment / quadrant → match. pred "Small left apical pneumothorax" vs gt "Small right apical pneumothorax" is one pneumothorax with the wrong location, scored downstream as a `major` location error (→ INC). Leaving them unmatched would count one mislocalisation as both an omission and a hallucination.
  - **Guard: prefer the same-side counterpart.** Findings on both sides of a paired structure (a left and a right renal cyst) are distinct entities: bind each to its own counterpart, and cross sides only when the other side has no same-side counterpart. gt "right lower lobe opacity" + gt "left lower lobe opacity" vs pred "left lower lobe opacity" only → match pred to the left gt; the right gt goes to `unmatched_gt` (an omission, not a flip).
- **Synonyms within one pathology category.** "Nodule" and "mass" in the same anatomy; "opacity" ≈ "consolidation" in the same context.
- **A negative or normal statement vs each abnormal finding it denies.** pred "Lungs clear" or "No pulmonary nodules" vs gt "4 mm right lower lobe nodule" → match. An organ-level "unremarkable" denies the abnormalities of that organ. Bind it even when the same statement also matches a normal finding on the other side.
- **Two readings of one abnormality.** Both reports describe an abnormality at the same site and differ in what they call it → match (one mischaracterised finding, scored downstream): pred "Large right apical bulla" vs gt "Right apical pneumothorax"; "Left lower lobe atelectasis" vs "Left lower lobe consolidation"; "Linear atelectasis in the lingula" vs "Lingular scarring"; "Hypodense lesion in liver segment 4" vs "Segment 4 hepatic cyst"; "Fibrotic strands in both apices" vs "Biapical scarring"; "Small right pleural effusion" vs "Right pleural thickening"; "Right adnexal cyst" vs "Right pelvic sidewall cystic lesion"; "Rectal fecaloma" vs "Fluid-filled rectum"; "Calcified granuloma in the right upper lobe" vs "Tiny right upper lobe nodules".
- **An organ removed vs the same organ described.** pred "Gallbladder with sludge" vs gt "Status post cholecystectomy" → match (one contradiction). A named resection removes its organs: right hemicolectomy (cecum, appendix, terminal ileum), Whipple (pancreatic head, duodenum, gallbladder), hysterectomy (uterus).
- **Names of one entity.** Ascites = free fluid = peritoneal fluid at any site, including "pelvic effusion" (the volume difference is scored downstream; never pleural fluid). In the lung, "infiltrate" = airspace opacity (consolidation, ground glass, pneumonia); "non-consolidative opacity" = ground glass. Unqualified "bowel loops" covers small bowel and colon. Subcentimetre hypodensities "too small to characterize, likely cysts" belong to the cyst set of that organ.
- **A negative for an inflammatory diagnosis vs its CT signs.** "No pancreatitis" vs "Peripancreatic fat stranding"; "No cholecystitis" vs "Gallbladder wall thickening with pericholecystic fluid" → match (status inversion, unless the sign is called minimal and the negative is qualified, as below).
- **A finding stated with its cause or consequence.** pred "Left UVJ stone causing mild hydroureteronephrosis" ↔ gt "Left UVJ calculus" and gt "Mild left hydroureteronephrosis" (1:N).
- **A negative of a larger or graded entity does not deny a smaller or benign one.** "No pulmonary mass" does not deny millimetric nodules; "No suspicious pulmonary nodule" does not deny a calcified granuloma or nodules called nonspecific: leave them unmatched (a size threshold, below, is the exception).
- **A finding below the threshold of a qualified negative.** pred "Small non-enlarged paratracheal lymph node" vs gt "No lymph nodes of pathological size"; "Trace pericardial fluid" vs "No significant pericardial effusion"; "Small calcified mediastinal nodes" vs "No enlarged lymph nodes"; "Trace pelvic free fluid" vs "No ascites" → match: one assessment, not a contradiction.

**Do not match:**
- **Different organ or bowel segment:** liver vs spleen; small bowel vs colon vs rectum; stomach vs duodenum.
- **Different pathology or different structure**, unless both are readings of one abnormality at the same site (above): "renal cyst" vs "renal stone"; "aortic calcification" vs "aortic aneurysm".
- **Different properties of one structure that do not contradict each other:** "portal vein patent" vs "portal vein wall calcification".
- **An entity the negative does not name.** A negative denies only the entity it names, in its own compartment: "No consolidation" does not deny a mass or nodule; "No hydronephrosis" does not deny a renal lesion; "No bowel inflammation" does not deny an abdominal-wall collection. Negatives of opacity ("no infiltrate", "no consolidation", "no ground glass") do not deny air-containing lucencies (emphysema, bulla, cyst, a "lucent" or "light transmission" area). "Vessels patent" denies occlusion and thrombosis, not calcification, plaque, aneurysm or a stent. "No acute osseous abnormality" denies acute findings, not degenerative change or a healed fracture.
- **A linear opacity vs a nodule.** Cord-like, strip-like, band-like or linear lung opacities never match a nodule or a dot-like opacity.
- **An umbrella statement vs a distinct named diagnosis or another body region.** "Degenerative change of the spine", "increased lung markings", "lymph nodes normal" do not cover "vertebral compression fracture", "bronchiectasis", or nodes of another region (abdominal vs mediastinal).

---

## 2. GRANULARITY: ONE ROW PER (pred, gt) PAIR

One finding (an umbrella) may cover several findings on the other side. Emit one match row per covered pair, repeating the umbrella's id: 1:N when one pred covers several gt, N:1 when several pred cover one gt. The findings linked by match rows form a match group.

| Umbrella pattern | Match rows |
|---|---|
| Parent anatomy covers specific structures | pred "Bile ducts unremarkable" ↔ gt "no intrahepatic biliary dilatation", gt "no extrahepatic biliary dilatation" |
| Organ-level negative covers several rule-outs | pred "Cerebellum unremarkable" ↔ gt "no tumor in cerebellum", "no hemorrhage in cerebellum", "no traumatic lesion in cerebellum", "no ischemic lesion in cerebellum" |
| Several lesions in one sentence | pred "Simple renal cysts in upper pole and parapelvic region, 28 mm and 23 mm" ↔ gt "upper pole cyst 28 mm", gt "parapelvic cyst 23 mm" |
| Bilateral statement vs one finding per side | "Bilateral pleural effusions" ↔ the left and the right effusion on the other side (1:N, or N:1 when gt is bilateral) |
| Umbrella gt covers specific preds | gt "Multiple bilateral subcentimeter renal cysts" ↔ pred "Right renal cyst 8 mm", "Left renal cyst 6 mm", "Left renal cyst 4 mm" |
| Broad gt negative covers granular preds | gt "Lungs are clear" ↔ pred "No focal consolidation in the right lung", "No focal consolidation in the left lung" |

- **Another instance joins its group.** The same process at an additional site, or one more member of an already matched set ("another pleural plaque"), is added to that match group, not left unmatched.
- **Cover only what the umbrella describes.** Bind a finding to an umbrella only when the umbrella clinically covers it (same anatomy and pathology category, as in §1); never use an umbrella to absorb a finding it did not describe. If the umbrella clearly maps to only one finding, match that one and leave the rest unmatched.

---

## 3. OUTPUT

Return only a JSON object with exactly these three keys, no other text and no markdown fences:

```json
{
  "matches": [
    {"pred_id": "<pred finding_id>", "gt_id": "<gt finding_id>", "reasoning": "<one clause>"}
  ],
  "unmatched_pred": ["<pred finding_id>", ...],
  "unmatched_gt":   ["<gt finding_id>", ...]
}
```

ID rules, the same for pred and gt:
- Every input id appears either in one or more `matches` rows or exactly once in its `unmatched_*` list, never both and never neither.
- No duplicates within `unmatched_pred` or `unmatched_gt`; no id that is not in the input.
- Both input lists empty → `{"matches": [], "unmatched_pred": [], "unmatched_gt": []}`. One list empty → every id of the other list goes to its `unmatched_*` list.

Output only the JSON object now.
