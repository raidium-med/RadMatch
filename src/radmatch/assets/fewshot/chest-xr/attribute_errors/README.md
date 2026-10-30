# Attribute-errors few-shot examples (chest-xr)

Five Stage 3b examples: one derived from the matches of `chest-xr/matching/example_1.json`, two built from the chest-xr findings files, two constructed. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); a few such pairs stay here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 (status-conflict pair excluded) | Moderate cardiomegaly vs Mild cardiomegaly, unchanged: severity minor; No focal airspace opacities; no… vs No concerning focal airspace…: no error |
| `example_2.json` | findings_gt + findings_pred example_2 | Stable bilateral pleural effusion vs Moderate bilateral pleural…: severity minor; Left basilar opacity, likely… vs Severe left lower lobe…: severity major, site minor; Right PICC line ends in the lower… vs Right central venous line ends in…: site major |
| `example_3.json` | findings_gt + findings_pred example_3 | A 6 mm pulmonary nodule in the… vs A 4 mm pulmonary nodule in the…: measurement major, extent minor |
| `example_4.json` | constructed | Possible small left apical… vs Small left apical pneumothorax: certainty major; Left basilar opacity, likely… vs Left basilar opacity, likely…: diagnosis major; Mild cardiomegaly vs Mild enlargement of the cardiac…: no error |
| `example_5.json` | constructed | Right lower lobe opacity vs Bilateral lower lobe opacities: no error; Bilateral lower lobe consolidation vs Left lower lobe consolidation: no error; Bilateral lower lobe consolidation vs Right lower lobe consolidation: no error; Left lower lobe consolidation… vs Left lower lobe consolidation: no error; Right upper lobe nodule,… vs Right upper lobe nodule: comparison major; Right upper lobe nodule vs Enlarging right upper lobe nodule: comparison major; Bibasilar atelectasis vs Increased bibasilar atelectasis: no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
