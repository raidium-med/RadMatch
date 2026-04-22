# Few-shot examples

This directory is empty by design — RadMatch does **not** ship bundled few-shot
examples, because the benchmark datasets we developed against (MIMIC-CXR,
Stanford Merlin, MR-RATE, …) have data-use agreements that forbid
redistribution of raw reports.

To use the `--fewshot <dataset_name>` CLI flag, create a subdirectory here
named after your dataset and populate it with examples you have the rights to
share (or keep local). The expected layout is:

```
assets/fewshot/<dataset_name>/
├── reports_gt/       # Ground-truth report text files: example_1.txt, example_2.txt, ...
├── reports_pred/     # Predicted report text files:    example_1.txt, example_2.txt, ...
├── findings_gt/      # Ground-truth findings JSON:      example_1.json, example_2.json, ...
├── findings_pred/    # Predicted findings JSON:         example_1.json, example_2.json, ...
└── matching/         # Example matching results for the LLM judge
```

Then run RadMatch with `--fewshot <dataset_name>`. If the directory is missing
or incomplete, RadMatch will log a warning and fall back to zero-shot prompting.
