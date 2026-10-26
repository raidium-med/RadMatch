# Attribute-errors few-shot examples (brain-mr)

Three Stage 3b examples, each derived from the matches of the corresponding `brain-mr/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (cortical-sulci INC pair excluded) | No free-text attribute errors on the merged completeness statements |
| `example_2.json` | matching/example_2 | Major laterality location error on putaminal metastasis (right vs left); major measurement error on the tentorial mass (thickness 1.5 vs 2 cm); major severity error on the pituitary metastasis (pred leaves out the growth into a mass pressing on the optic chiasm), whose comparison + significance shift is owned by Stage 3a |
| `example_3.json` | matching/example_3 | Major sub-anatomic location error (parietal vs frontal region) + major measurement error (14 vs 11 mm) on falx calcification |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
