# Attribute-errors few-shot examples (head-ct)

Three Stage 3b examples, each derived from the matches of the corresponding `head-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Major location error: laterality flip on lateralized hemorrhagic temporal sequelae (right vs left hemisphere) + 2 clean matched pairs |
| `example_2.json` | matching/example_2 | Major severity loss on chronic white matter changes (gt 'marked' vs pred drops) + minor measurement difference on the anterior SDH portion (8 vs 10 mm) + 2 pairs without free-text errors (overall SDH comparison loss is Stage 3a) |
| `example_3.json` | matching/example_3 | Minor measurement error: sub-mm difference on the RUL micronodule (5.1 vs 4.4 mm, both under the 6 mm threshold) + 2 clean pairs |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
