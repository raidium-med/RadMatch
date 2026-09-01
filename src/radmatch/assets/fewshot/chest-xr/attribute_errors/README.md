# Attribute-errors few-shot examples (chest-xr)

Three Stage 3b examples, each derived from the matches of the corresponding `chest-xr/matching/example_N.json`. INC pairs (status conflicts) are excluded — Stage 3b never sees them in production.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (status-conflict pair excluded) | 1 minor severity error (cardiomegaly mild vs moderate) + 3 clean pairs |
| `example_2.json` | matching/example_2 | Major severity (LLL collapse vs basilar atelectasis) + major sub-anatomic location (CVL upper RA vs PICC lower SVC) + 2 clean pairs |
| `example_3.json` | matching/example_3 | No free-text attribute errors — the size + comparison deltas on the surveillance nodule live in Stage 3a deterministic comparators and are intentionally NOT re-emitted at Stage 3b |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
