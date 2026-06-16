# [🚧 Update in progress] RadMatch: Finding-Based Matching for Radiology Report Generation Evaluation

[![CI](https://img.shields.io/github/actions/workflow/status/raidium-med/RadMatch/ci.yaml?branch=main&label=CI)](https://github.com/raidium-med/RadMatch/actions/workflows/ci.yaml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> [!NOTE]
> A substantially updated version of RadMatch is on the way. We have been
> developing a new version internally that differs significantly from the
> currently released code. It will be presented soon. The code on `main`
> reflects the previously released version.

**RadMatch** is an LLM-based evaluation pipeline for radiology report generation. It extracts structured findings from each report, uses an LLM judge to match predictions to ground truth on **clinical equivalence**, and counts matched predictions as true positives, unmatched predictions as false positives, and unmatched ground-truth findings as false negatives. From these, RadMatch reports **precision, recall, and F1** — overall, per report, and per finding type.

## Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [How it works](#how-it-works)
- [Adding a new LLM provider](#adding-a-new-llm-provider)
- [License](#license)

## Installation

RadMatch is distributed as a source package managed with [uv](https://docs.astral.sh/uv/). Install from source:

```bash
git clone https://github.com/raidium-med/RadMatch.git
cd RadMatch
uv sync
```

Or install directly from GitHub into an existing project:

```bash
uv pip install git+https://github.com/raidium-med/RadMatch.git
```

## Quick Start

### 1. Configure environment variables

```bash
# Copy env.example and add your API keys/credentials
cp env.example .env
# Load env variables
source .env
```

Out of the box RadMatch supports **Azure OpenAI** and **Mistral** models. See [Adding a new LLM provider](#adding-a-new-llm-provider) to wire a new one.

### 2. Run the pipeline

Extraction + evaluation in a single command — the common path:

```bash
uv run radmatch run_all \
  --reports-gt /path/to/ground_truth_reports \
  --reports-pred /path/to/predicted_reports \
  --output-dir /path/to/output \
  --llm-extractor gpt-5 \
  --llm-judge gpt-5 \
  --workers 5 \
  --fewshot <your-dataset>
```

Outputs are written under `/path/to/output/radmatch_results/` (findings, per-report matching, and `metrics_summary.json`).

### Few-shot examples

To help the LLM adapt to a dataset's report style, pass `--fewshot <dataset_name>` to any subcommand. See [`assets/fewshot/README.md`](assets/fewshot/README.md) for the expected directory layout.

### Stage-by-stage

Alternatively, run extraction and evaluation as two separate subcommands. Useful when you want to re-run only one stage, or use the batch API for cost-efficient large runs.

#### Extract findings

The pipeline supports two inference modes:

##### Single inference
Individual API calls with parallel workers. Use this mode for:
- **debugging**: test your setup on a small subset with `--limit`
- **small datasets**: fewer than ~100 reports

```bash
uv run radmatch extract_findings infer \
  --reports-gt /path/to/ground_truth_reports \
  --reports-pred /path/to/predicted_reports \
  --output-dir /path/to/output \
  --llm-extractor gpt-5 \
  --workers 5 \
  --fewshot <your-dataset>
```
- Use `--workers` to control concurrency.
- Use `--limit` to process only a subset of reports during debugging.
- Use `--fewshot` to load few-shot examples (optional).
- Use `--findings-gt` to copy existing ground truth findings and only extract from predicted reports.

##### Batch inference
Uses provider batch APIs for cost efficiency. Use for production runs over entire datasets.

Submit the batch job:
```bash
uv run radmatch extract_findings infer_batch submit \
  --reports-gt /path/to/ground_truth_reports \
  --reports-pred /path/to/predicted_reports \
  --output-dir /path/to/output \
  --llm-extractor gpt-5
```
For Mistral models, you can monitor status in the [Mistral batches console](https://console.mistral.ai/build/batches), or run `uv run radmatch extract_findings infer_batch status --output-dir /path/to/output`.

Retrieve and process results:
```bash
uv run radmatch extract_findings infer_batch retrieve \
  --output-dir /path/to/output
```
This writes findings JSON files into `radmatch_results/findings_gt/` and `radmatch_results/findings_pred/`.

#### Evaluate findings

Compare predicted findings against ground truth using LLM-based evaluation:
```bash
uv run radmatch evaluate \
  --results-dir /path/to/output/radmatch_results \
  --llm-judge gpt-5 \
  --workers 5 \
  --fewshot <your-dataset>
```
- The `--results-dir` must contain `findings_gt/` and `findings_pred/` subdirectories.
- Use `--fewshot` to provide few-shot examples for the LLM judge (optional).


## How it works

### Matching findings

The evaluation process uses a **finding-by-finding** matching approach with an LLM judge:

1. **Report-level processing**: Process one report at a time, loading both predicted and ground truth findings.

2. **Finding-by-finding matching**: For each predicted finding:
   - The LLM judge receives the predicted finding and all ground truth findings from that report
   - The judge determines if the predicted finding semantically matches any GT finding
   - Returns: `matched` (boolean), `corresponding_gt_finding_id`, `confidence`, `reasoning`, and `api_failed`

3. **One-to-one matching constraint**:
   - Each predicted finding can match at most one ground truth finding
   - Each ground truth finding can be matched by at most one predicted finding
   - If multiple predicted findings try to match the same GT, only the first match is accepted

4. **Semantic matching criteria**: The LLM judge focuses on **clinical equivalence**:
   - Matches findings that describe the same clinical observation, even with different wording
   - Does not require exact text matches (e.g., "pulmonary nodule" matches "lung nodule")

### Computing metrics

Three metric variants are computed from the match set:

| Metric | Description |
|--------|-------------|
| **Report-averaged** | Average F1/precision/recall across reports (equal report weighting) |
| **Micro-averaged** | Aggregated TP/FP/FN (weighted by finding frequency) |
| **Per-type** | Metrics broken down by finding category (e.g., abnormal-regular, normal-regular) |

Finding type categories:
- **abnormal-regular**: Abnormal findings without measurements or comparison
- **normal-regular**: Normal findings without measurements or comparison
- **longitudinal**: Findings with comparison (stable, improving, worsening, new, resolved)
- **measurement**: Findings with quantitative measurements

### Output formats

<details>
<summary>Finding JSON (extraction output)</summary>

```json
[
  {
    "text": "Single-sentence clinical observation.",
    "clinical_status": "normal|abnormal",
    "comparison": "stable|improving|worsening|new|resolved" | null,
    "measurements": [
      {
        "value": 5.2,
        "unit": "mm",
        "category": "size|count|attenuation|ratio|other"
      }
    ]
  }
]
```

</details>

<details>
<summary>Matching result JSON (per-report matching output)</summary>

```json
{
  "pred_001": {
    "matched": true,
    "corresponding_gt_finding_id": "gt_001",
    "confidence": "high|medium|low",
    "reasoning": "Brief explanation of match",
    "api_failed": false
  },
  "pred_002": {...},
  "..."
}
```

</details>

<details>
<summary><code>metrics_summary.json</code> (aggregated metrics)</summary>

```json
{
  "metadata": { ... },
  "metrics": {
    "report_averaged": { "f1": 0.85, "precision": 0.82, "recall": 0.88, "gt_count": 102, "pred_count": 110 },
    "micro_averaged": { "f1": 0.83, "precision": 0.81, "recall": 0.85, "gt_count": 102, "pred_count": 110 },
    "abnormal-regular": { "micro_averaged": { "f1": 0.80, "precision": 0.78, "recall": 0.82, "gt_count": 40, "pred_count": 45 } },
    "normal-regular": { "micro_averaged": { "f1": 0.90, "precision": 0.88, "recall": 0.92, "gt_count": 50, "pred_count": 52 } },
    "longitudinal": {
      "micro_averaged": { "f1": 0.85, "precision": 0.84, "recall": 0.86, "gt_count": 10, "pred_count": 12 },
      "macro_averaged": { "f1": 0.82, "precision": 0.81, "recall": 0.83 },
      "per_category": { "stable": { "f1": 0.90, "precision": 0.88, "recall": 0.92, "gt_count": 5, "pred_count": 6 } }
    },
    "measurement": {
      "micro_averaged": { "f1": 0.88, "precision": 0.86, "recall": 0.90, "gt_count": 12, "pred_count": 13, "mre": 0.05 },
      "macro_averaged": { "f1": 0.84, "precision": 0.82, "recall": 0.86, "gt_count": 12, "pred_count": 13, "mre": 0.06 },
      "per_category": { "size": { "f1": 0.87, "precision": 0.85, "recall": 0.89, "gt_count": 6, "pred_count": 7, "mre": 0.04 } }
    },
    "report_score_statistics": { ... },
    "findings_counts": { "gt": 102, "pred": 110, "tp": 200, "fp": 50, "fn": 40 }
  }
}
```

</details>


## Adding a new LLM provider

RadMatch ships with built-in clients for **Azure OpenAI** and **Mistral**. Adding another provider is three mechanical steps:

1. **Register the model(s)** in `src/radmatch/constants.py` by adding a new key to `MODEL_CATALOG`:

   ```python
   MODEL_CATALOG: dict[str, set[str]] = {
       "mistral": {"magistral-medium-2509"},
       "azure": {"gpt-5", ...},
       "my_provider": {"my-model-v1"},   # <-- add your provider and model IDs
   }
   ```

2. **Implement a client** in `src/radmatch/llm_utils/llm_clients.py`:
   - Subclass `SingleClient` and implement `complete(messages, response_format)` for interactive/parallel runs.
   - (Optional, only if you want the `infer_batch` subcommand) subclass `BatchClient` and implement its `submit` / `status` / `retrieve` methods.

3. **Wire the factory** at the bottom of `llm_clients.py` — add a branch in `build_single_client` (and `build_batch_client` if applicable) that dispatches to your new class when `provider == "my_provider"`.

API keys should be read from environment variables and documented in `env.example`.

## License

RadMatch is released under the [Apache License 2.0](LICENSE).
