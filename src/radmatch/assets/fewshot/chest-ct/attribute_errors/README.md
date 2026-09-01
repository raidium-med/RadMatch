# Attribute-errors few-shot examples (chest-ct)

Three Stage 3b examples, each derived from the matches of the corresponding `chest-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (heart-size INC pair excluded) | Major laterality location error on bronchiectasis (left vs right apex) + major severity on coronary calcifications (moderate vs severe) + clean aortic-arch + hepatic lesion pairs |
| `example_2.json` | matching/example_2 (hepatic INC pair excluded) | No free-text attribute errors — measurement diff on largest pulmonary nodule is Stage 3a |
| `example_3.json` | matching/example_3 (pleural-effusion INC pair excluded) | No free-text attribute errors — measurement diff on LLL nodule is Stage 3a |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
