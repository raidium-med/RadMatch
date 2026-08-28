# Attribute-errors few-shot examples (brain-mr)

Three Stage 3b examples, each derived from the matches of the corresponding `brain-mr/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (cortical-sulci INC pair excluded) | No free-text attribute errors on the merged completeness statements |
| `example_2.json` | matching/example_2 | Major laterality location error on putaminal metastasis (right vs left); pituitary pair's comparison + significance shift is owned by Stage 3a |
| `example_3.json` | matching/example_3 | Major sub-anatomic location error on falx calcification (parietal vs frontal region) |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
