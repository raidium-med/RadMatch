# Attribute-errors few-shot examples (head-ct)

Three Stage 3b examples: two built from the head-ct reports, one constructed (`example_4.json`). Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); a few such pairs stay here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Hypodense cortico-subcortical… vs Hypodense cortico-subcortical…: no error; No spontaneous hyperdensity in… vs No spontaneous hyperdensity in…: no error |
| `example_2.json` | findings_gt + findings_pred example_2 | Major severity loss on chronic white matter changes (gt 'marked' vs pred drops: a high grade left out) + minor measurement difference on the SDH, one finding with its portions (anterior 8 vs 10 mm, largest 13 mm on both: the 10 mm threshold is not in play) |
| `example_4.json` | constructed | Microangiopathic white matter… vs Periventricular and subcortical…: site minor; 18 mm mucous retention cyst in… vs 12 mm mucous retention cyst in…: measurement minor |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
