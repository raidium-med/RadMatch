# Attribute-errors few-shot examples (brain-mr)

Three Stage 3b examples, each derived from the matches of the corresponding `brain-mr/matching/example_N.json`. A status-inversion pair reaches Stage 3b too and expects `[]` (prompt rule 1): the inversion is scored upstream.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (every pair, with its match-group context) | No free-text attribute errors on the merged completeness statements of two 1:N groups; two status inversions, no errors |
| `example_2.json` | findings_gt + findings_pred example_2 | Putaminal metastasis right vs left: no error here, the side is Stage 3a `laterality`'s; major measurement error on the tentorial mass (thickness 1.5 vs 2 cm); major extent error (mass effect) on the pituitary metastasis (pred leaves out the growth into a mass pressing on the optic chiasm), whose comparison change Stage 3a scores |
| `example_3.json` | findings_gt + findings_pred example_3 | Major site error (parietal vs frontal region) + major measurement error (14 vs 11 mm) on falx calcification |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
