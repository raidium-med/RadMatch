# Few-shot bundles

Pass `--fewshot <bundle>` to any subcommand to adapt the LLM to a dataset's report
style. Five bundles ship with RadMatch:

| Bundle | Modality |
|---|---|
| `abdomen-ct` | Abdominal CT |
| `brain-mr` | Brain MR |
| `chest-ct` | Chest CT |
| `chest-xr` | Chest X-ray |
| `head-ct` | Head CT |

The report text in these bundles is de-identified: dates, names, and institutions are
replaced with `[DATE]`, `[NAME]`, `[HOSPITAL]` placeholders. Where the source de-identifier
mis-tagged a series/image number as a date, the tag is left in place (e.g. `S301- [DATE:440]`
is series 301, image 440) — those are intra-study coordinates, not identifiers.

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
