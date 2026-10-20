# Attribute-errors few-shot examples (chest-ct)

Stage 3b examples, most derived from the matches of the corresponding `chest-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (heart-size INC pair excluded) | Major laterality location error on bronchiectasis (left vs right apex) + major severity on coronary calcifications (moderate vs severe) + clean aortic-arch + hepatic lesion pairs |
| `example_2.json` | matching/example_2 (hepatic INC pair excluded) | No free-text attribute errors — measurement diff on largest pulmonary nodule is Stage 3a |
| `example_3.json` | matching/example_3 (pleural-effusion INC pair excluded) | No free-text attribute errors — measurement diff on LLL nodule is Stage 3a |
| `example_4.json` | matching/example_4 (status inversions excluded) | Major morphology for bulla vs pneumothorax, major location for unilateral vs bilateral; no error for synonyms, a sub-threshold node, a post-surgical state |
| `example_5.json` | constructed | Certainty major for a hedged fracture or a hedged PE rule-out; added malignant reading of nodes and a Lung-RADS bucket change major; one certainty step minor |
| `example_6.json` | constructed | Major for acute vs chronic emboli, solitary vs multiple nodules, ground-glass vs solid, abutment vs invasion, residual thymus vs thymoma, clot burden; one emphysema grade minor; calcium grid vs list no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
