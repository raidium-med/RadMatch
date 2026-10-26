# Attribute-errors few-shot examples (chest-xr)

Five Stage 3b examples: three derived from the matches of the corresponding `chest-xr/matching/example_N.json`, two constructed. A status-inversion pair reaches Stage 3b too and expects `[]` (prompt rule 1): the inversion is scored upstream.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (status-conflict pair excluded) | 1 minor severity error (cardiomegaly mild vs moderate) + 3 clean pairs |
| `example_2.json` | findings_gt + findings_pred example_2 | Major severity (left-out moderate grade on the effusion, left-out severe grade on the LLL consolidation) + minor site (left basilar vs left lower lobe) + major site (device tip: CVL upper RA vs PICC lower SVC) + 1 clean pair |
| `example_3.json` | findings_gt + findings_pred example_3 | 4 vs 6 mm surveillance nodule crosses the 6 mm threshold (major measurement); one nodule for a gt set of several on CT (major extent); the comparison flip stays in Stage 3a |
| `example_4.json` | constructed | Certainty major for a hedged pneumothorax, minor for one step; pneumonia vs atelectasis major diagnosis |
| `example_5.json` | constructed | Bilateral vs one side and a left-out side: no site error, the side is Stage 3a `laterality`'s; a bilateral pred vs a left and a right gt no error, more detail no error, a left-out grade major, invented growth on a nodule major comparison, definite vs possible pneumonia major certainty; a side only the pred gives and one side vs a gt covering both hila: no site error (Stage 3a `laterality`) |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
