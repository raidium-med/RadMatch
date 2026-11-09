# Few-shot bundles

Pass `--fewshot <bundle>` to any subcommand to adapt the LLM to a dataset's report
style. Eight bundles ship with RadMatch:

| Bundle | Modality |
|---|---|
| `abdomen-ct` | Abdominal CT |
| `abdomen-us` | Abdominal, renal and bladder, pelvic and early obstetric ultrasound |
| `brain-mr` | Brain MR |
| `breast-mg` | Mammography, screening and diagnostic (its BI-RADS conventions also apply to breast MRI and ultrasound) |
| `chest-ct` | Chest CT |
| `chest-xr` | Chest X-ray |
| `head-ct` | Head CT |
| `msk-xr` | Musculoskeletal radiographs (extremities, hip and pelvis) |

The report text of the five dataset bundles (`abdomen-ct`, `brain-mr`, `chest-ct`, `chest-xr`,
`head-ct`) is de-identified: dates, names, and institutions are replaced with `[DATE]`, `[NAME]`,
`[HOSPITAL]` placeholders. Where the source de-identifier mis-tagged a series/image number as a
date, the tag is left in place (e.g. `S301- [DATE:440]` is series 301, image 440) — those are
intra-study coordinates, not identifiers.

`abdomen-us`, `breast-mg` and `msk-xr` are constructed for these bundles (written from scratch,
no dataset text); their `[DATE]` and `[NAME]` tags only imitate the de-identified style.

## Adding a bundle

Create `<bundle-name>/` here with this layout. A missing or incomplete directory logs a
warning and falls back to zero-shot prompting rather than failing.

```
<bundle-name>/
├── reports_gt/         # Ground-truth report text:  example_1.txt, example_2.txt, ...
├── reports_pred/       # Predicted report text:     example_1.txt, ...
├── findings_gt/        # Stage 1 output for each GT report:   example_1.json, ...
├── findings_pred/      # Stage 1 output for each pred report: example_1.json, ...
├── matching/           # Stage 2 examples: pred↔GT alignment
└── attribute_errors/   # Stage 3b examples: per-pair attribute errors
```

Stage 1 pairs each `reports_gt/` report with its `findings_gt/` answer; Stage 2 reads
`matching/` and Stage 3b `attribute_errors/`. `reports_pred/` and `findings_pred/` are not
loaded: they are the source the matching and attribute-errors examples were built from. Bundles installed from the wheel live
under `radmatch/assets/fewshot/` in site-packages, so a bundle of your own is easiest to
add in a source checkout.
