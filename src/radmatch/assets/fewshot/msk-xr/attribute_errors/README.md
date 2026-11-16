# Attribute-errors few-shot examples (msk-xr)

Four Stage 3b examples: three derived from the matches of `msk-xr/matching/` examples 1-3, one constructed. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); one pair of two normal statements stays here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | Moderate osteoarthritis of both… vs Mild osteoarthritis of both hips…: grade minor |
| `example_2.json` | matching/example_2 | …the right fourth metacarpal neck… vs …the right fifth metacarpal neck…: location major; Normal alignment at the… vs No dislocation: no error |
| `example_3.json` | matching/example_3 | New 1 mm radiolucent line at the… vs New 3 mm radiolucent line at the…: measurement major; 2.4 cm osteolytic lesion in the… vs Enlarging 2.4 cm osteolytic…: comparison major |
| `example_4.json` | constructed | …tibial shaft vs …tibial shaft + extending into the tibial plafond: extent major; …distal radius + extending into the radiocarpal… vs …distal radius: extent major; Lytic lesion in the right… vs Permeative lytic lesion with…: appearance major; Healed fracture of the base of… vs Acute fracture of the base of…: diagnosis major; Probable nondisplaced fracture… vs Nondisplaced fracture of the…: certainty minor; …of the right distal fibula vs …of the left distal fibula: no error; Nondisplaced fractures of the right fourth and fifth… vs …the right fourth metatarsal shaft / …the right fifth metatarsal shaft: no error (group); Moderate medial compartment… vs Moderate osteoarthritis of the…: no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
