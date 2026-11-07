# Attribute-errors few-shot examples (breast-mg)

Four Stage 3b examples: three derived from the matches of `breast-mg/matching/` examples 1-3, one constructed. Live runs do not send the judge the pairs whose outcome the rules fix (a status inversion, two normal statements without a hedge, identical texts); one pair of two normal statements stays here to show the rules (prompt rule 1), with no error.

| File | Drawn from | Highlights |
|------|------------|------------|
| `example_1.json` | matching/example_1 | …breast at 10 o'clock, upper… vs …breast at 2 o'clock, upper outer…: location major; …nipple, BI-RADS 3 vs …nipple, BI-RADS 4A: grade major; …right breast vs …right breast + with no suspicious mass…: no error |
| `example_2.json` | matching/example_2 | …in the right breast upper outer… vs …in the left breast upper outer…: no error; New 0.9 cm oval circumscribed… vs Stable 0.9 cm oval circumscribed…: no error; Postsurgical architectural… vs Stable postsurgical…: location minor |
| `example_3.json` | matching/example_3 | …as a 1.9 x 1.8 cm irregular mass… vs …as a 2.2 x 1.8 cm irregular mass…: measurement major; No axillary lymphadenopathy vs No enlarged axillary lymph nodes…: no error |
| `example_4.json` | constructed | …biopsy clip, BI-RADS 6 vs …biopsy clip, with ulceration of…: extent major; …inner quadrant vs …inner quadrant + BI-RADS 4B: grade major; Large oil cyst at the right… vs Small oil cyst at the right…: grade minor; …mass with circumscribed margins… vs …mass with spiculated margins in…: appearance major; …left breast, consistent with… vs …left breast, concerning for…: diagnosis major; Possible extracapsular rupture… vs Extracapsular rupture of the…: certainty major; 1.3 cm oval circumscribed mass… vs Enlarging 1.3 cm oval…: comparison major; Benign vascular calcifications in both breasts vs …in the left breast / …in the right breast: no error (group); …right breast at 10 o'clock… vs …right breast upper outer quadrant: no error |

See `../../abdomen-ct/attribute_errors/README.md` for the file format and loader notes.
