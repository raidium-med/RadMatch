# Attribute-errors few-shot examples (abdomen-us)

Four Stage 3b examples: three derived from the matches of `abdomen-us/matching/` examples 1-3, one constructed. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); one pair of two normal statements stays here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | …hepatic echogenicity, consistent… vs …hepatic echogenicity, compatible…: no error; Cholelithiasis with multiple… vs Acute calculous cholecystitis…: certainty minor |
| `example_2.json` | matching/example_2 | 2.1 cm subserosal fibroid in the… vs 2.1 cm submucosal fibroid in the…: location major; 2.8 cm simple cyst in the left… vs 3.2 cm simple cyst in the left…: measurement major; No pelvic free fluid vs No free fluid in the pelvis: no error |
| `example_3.json` | matching/example_3 | …of the left kidney vs …of the right kidney: no error |
| `example_4.json` | constructed | 2.1 cm hypoechoic lesion in the… vs Multiple hypoechoic liver…: extent major; Mild left hydronephrosis vs Severe left hydronephrosis: grade major; 4.5 cm unilocular cyst in the… vs 4.5 cm cystic lesion with an…: appearance major; Enlarged edematous right ovary… vs Right ovarian torsion, with an…: diagnosis major; 3.8 cm endometrioma in the right… vs Enlarging 3.8 cm endometrioma in…: comparison major; Nonobstructing stones in both kidneys vs Nonobstructing stone in the right kidney / Nonobstructing stone in the left kidney: no error (group); Small simple cyst in the upper… vs Small simple right renal cyst: no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
