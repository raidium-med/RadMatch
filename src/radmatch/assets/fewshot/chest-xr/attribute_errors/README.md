# Attribute-errors few-shot examples (chest-xr)

Five Stage 3b examples: three derived from the matches of the corresponding `chest-xr/matching/example_N.json`, two constructed. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (status-conflict pair excluded) | 1 minor severity error (cardiomegaly mild vs moderate) + 3 clean pairs |
| `example_2.json` | matching/example_2 | Major severity (left-out moderate grade on the effusion, left-out severe grade on the LLL consolidation) + minor location (left basilar vs left lower lobe) + major sub-anatomic location (CVL upper RA vs PICC lower SVC) + 1 clean pair |
| `example_3.json` | matching/example_3 | 4 vs 6 mm surveillance nodule crosses the 6 mm threshold (major measurement); the comparison flip stays in Stage 3a |
| `example_4.json` | constructed | Certainty major for a hedged pneumothorax, minor for one step; pneumonia vs atelectasis major morphology |
| `example_5.json` | constructed | Bilateral vs one side major both ways, a left-out side major, a bilateral pred vs a left and a right gt no error, more detail no error, a left-out grade major, invented growth on a nodule major comparison, definite vs possible pneumonia major certainty, a side only the pred gives major, one side vs a gt covering both hila major |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
