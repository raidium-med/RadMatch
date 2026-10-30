# Attribute-errors few-shot examples (brain-mr)

Three Stage 3b examples, each derived from the matches of the corresponding `brain-mr/matching/example_N.json`. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); a few such pairs stay here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (every pair, with its match-group context) | Medulla oblongata, pons,… vs Medulla oblongata, pons,…: no error; Medulla oblongata, pons,… vs Both cerebellar hemispheres and…: no error; Hemispheric cortical sulcal… vs Hemispheric cortical sulcal…: no error |
| `example_2.json` | findings_gt + findings_pred example_2 | Putaminal metastasis right vs left: no error here, the side is Stage 3a `laterality`'s; major measurement error on the tentorial mass (thickness 1.5 vs 2 cm); major extent error (mass effect) on the pituitary metastasis (pred leaves out the growth into a mass pressing on the optic chiasm), whose comparison change Stage 3a scores |
| `example_3.json` | findings_gt + findings_pred example_3 | A 14 mm long diameter hypointense… vs An 11 mm long diameter…: site minor, measurement minor |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
