# Attribute-errors few-shot examples (chest-ct)

Stage 3b examples, most derived from the matches of the corresponding `chest-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (heart-size INC pair excluded) | Major laterality location error on bronchiectasis (left vs right apex) + minor severity on coronary calcifications (moderate vs severe, one step) + aortic arch 4.1 vs 3.6 cm across the 4 cm threshold (major measurement) + clean hepatic lesion pair |
| `example_2.json` | matching/example_2 (hepatic INC pair excluded) | Minor measurement error on the largest pulmonary nodule (2.5 x 1.6 vs 3.1 x 1.7 cm, under 20 % difference) + clean node pair |
| `example_3.json` | matching/example_3 (pleural-effusion INC pair excluded) | LLL nodule 11 vs 13 mm on one side of every threshold (minor measurement) |
| `example_4.json` | matching/example_4 (status inversions excluded) | Major morphology for bulla vs pneumothorax, major location for unilateral vs bilateral; no error for synonyms, a sub-threshold node, a post-surgical state |
| `example_5.json` | constructed | Certainty major for a hedged fracture or a hedged PE rule-out; added malignant reading of nodes, a left-out 'mildly' grade and a Lung-RADS bucket change major; one certainty step minor; a left-out emphysema subtype major |
| `example_6.json` | constructed | Major for acute vs chronic emboli, solitary vs multiple nodules, ground-glass vs solid, abutment vs invasion, residual thymus vs thymoma, clot burden; one emphysema grade minor; a vessel list that leaves out the calcium grades major; solitary nodule vs bilateral nodules also major location |
| `example_7.json` | constructed | Umbrella pred with no station vs located nodes major location per pair ('enlarged' covers the 12 and 15 mm sizes), left-out lobe and subtype major, more detail no error, bilateral vs one side major, bilateral pred vs left + right gt no error, size class covering the gt value no error, cause hedge no error, invented growth on a mass major comparison, a diagnosis name for a described finding no error, a left-out side major |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
