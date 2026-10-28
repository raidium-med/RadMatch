# Attribute-errors few-shot examples (head-ct)

Four Stage 3b examples: the first three built from the head-ct reports, the fourth constructed. A status-inversion pair reaches Stage 3b too and expects `[]` (prompt rule 1): the inversion is scored upstream.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Temporal sequelae right vs left: no error here, the side is Stage 3a `laterality`'s; their hemorrhage rule-outs, two normal findings on opposite sides, no error + 2 clean matched pairs |
| `example_2.json` | findings_gt + findings_pred example_2 | Major severity loss on chronic white matter changes (gt 'marked' vs pred drops) + minor measurement difference on the SDH, one finding with its portions (anterior 8 vs 10 mm, largest 13 mm on both: the 10 mm threshold is not in play; the overall change the pred leaves out is Stage 3a) |
| `example_3.json` | findings_gt + findings_pred example_3 | Minor measurement error: sub-mm difference on the RUL micronodule of a set of micronodules (5.1 vs 4.4 mm, both under the 6 mm threshold) + 2 clean pairs |
| `example_4.json` | constructed | Partly different distribution of microangiopathic white matter changes minor site (a diffuse process); maxillary retention cyst 18 vs 12 mm minor measurement (benign, not followed by its size); two normal findings worded differently, no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
