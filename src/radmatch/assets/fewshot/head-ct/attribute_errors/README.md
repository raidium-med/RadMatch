# Attribute-errors few-shot examples (head-ct)

Three Stage 3b examples, each derived from the matches of the corresponding `head-ct/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Major location error: laterality flip on lateralized hemorrhagic temporal sequelae (right vs left hemisphere) + 2 clean matched pairs |
| `example_2.json` | matching/example_2 | Minor severity loss on chronic white matter changes (gt 'marked' vs pred drops) + 3 pairs without free-text errors (overall SDH comparison loss + anterior portion measurement diff are Stage 3a) |
| `example_3.json` | matching/example_3 | No free-text attribute errors — sub-mm measurement difference on the RUL micronodule is Stage 3a deterministic |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
