# RadMatch: Auditable Radiology Report Evaluation via Finding-Level Matching

[![PyPI](https://img.shields.io/pypi/v/radmatch)](https://pypi.org/project/radmatch/)
[![CI](https://img.shields.io/github/actions/workflow/status/raidium-med/RadMatch/ci.yaml?branch=main&label=CI)](https://github.com/raidium-med/RadMatch/actions/workflows/ci.yaml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**RadMatch** is an LLM-based evaluation framework for radiology report generation. It extracts atomic findings from each report, matches predictions to ground truth on **clinical equivalence**, and characterizes every error across **seven clinical attribute dimensions** — so a discrepancy is reported as a laterality flip, a severity change or a missed measurement rather than an undifferentiated penalty. From these it reports the **count of errors on clinically relevant findings**, alongside **safety recall and precision** for life-threatening findings.

The headline score is `actionable_errors_per_report`: the mean per-report count of errors involving non-routine findings. **Lower is better.**

**Every step is written to disk:** the findings extracted from each report, which prediction matched which ground truth and why, and each attribute error with the judge's reasoning. So a score is **auditable**: it can always be traced back to the findings that produced it, and an optional [**dashboard**](#dashboard) reads those records back, taking you from a dataset-level number to the individual finding pair behind it.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Per-stage usage](#per-stage-usage)
- [How RadMatch works](#how-radmatch-works)
- [Dashboard](#dashboard)
- [Self-hosted models](#self-hosted-models)
- [Adding a new LLM provider](#adding-a-new-llm-provider)
- [Citation](#citation)
- [License](#license)

## Installation

Install the latest release from PyPI:

```bash
pip install radmatch                  # or: uv pip install radmatch
pip install "radmatch[dashboard]"     # with the optional results dashboard
```

Or install directly from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/raidium-med/RadMatch.git
cd RadMatch
uv sync
```

## Quick start

### 1. Serve the judge

The examples use [Gemma-4-31B](https://huggingface.co/google/gemma-4-31B-it) as extractor and judge, served locally with [vLLM](https://docs.vllm.ai) in fp8 (two 32 GB GPUs, or one GPU with 48 GB or more without `--tensor-parallel-size`):

```bash
vllm serve google/gemma-4-31B-it --port 8000 --tensor-parallel-size 2 \
  --quantization fp8 --kv-cache-dtype fp8 --max-model-len 65536 \
  --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}' \
  --structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'

export RADMATCH_LOCAL_BASE_URL="http://localhost:8000/v1"
```

To use a hosted model instead, add its credentials to `.env` (`cp env.example .env`, then `source .env`) and pass its name, e.g. `--llm-judge gpt-5.5`. Out of the box RadMatch supports **OpenAI**, **Anthropic**, **Mistral**, and any OpenAI-compatible self-hosted endpoint. GPT and Claude models each work against either the vendor API or Azure — whichever the environment is configured for:

| Model family | Vendor API | Azure route |
|---|---|---|
| `gpt-*`, `kimi-*`, `deepseek-*` | `OPENAI_API_KEY` | `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` |
| `claude-*` | `ANTHROPIC_API_KEY` | `ANTHROPIC_FOUNDRY_BASE_URL` + `ANTHROPIC_FOUNDRY_API_KEY` |
| `magistral-*` | `MISTRAL_API_KEY` | — |

### 2. Run the pipeline

Extraction + matching + scoring in a single command:

```bash
uv run radmatch run_all \
  --reports-gt /path/to/ground_truth_reports \
  --reports-pred /path/to/predicted_reports \
  --output-dir /path/to/output \
  --llm-extractor local:google/gemma-4-31B-it \
  --llm-judge local:google/gemma-4-31B-it \
  --workers 64 \
  --fewshot chest-ct
```

Reports are `<series>.txt` files, paired by filename across the two directories. Outputs are written under `/path/to/output/radmatch_results/`, with the headline numbers in `metrics_summary.json`.

Every stage caches on success, so re-running the same command against the same `--output-dir` recomputes only the reports that failed and skips the rest. A stage reuses its output only if it was produced with the same config (model, few-shot, reasoning, prompt, schema) from the same inputs: changing the few-shot bundle re-extracts, re-matches and re-scores. `--retry-passes N` (default 1) automates that by running the chain up to N times, stopping as soon as nothing is missing or a pass recovers nothing.

A report that *fails* a stage drops out of the results and is listed in `failed_reports{,_matching,_scoring}.json`.

A report can also *degrade* rather than fail: Stage 2 falling back to the valid subset of its matches. It still produces cached output and still counts in `n_reports`, flagged as `validation_fallback` in `matching/<series>.json` — so a plain re-run skips it. Use `--retry-degraded` to re-match it, or `--match-retries` to buy the judge more attempts up front. Stage 3b never degrades: a chunk of pairs the judge keeps answering malformed (`--score-retries` attempts) or that times out is split in half and retried, and a pair that still fails drops the report rather than scoring it as if no attribute errors were found.

### Few-shot examples

Pass `--fewshot <bundle>` to any subcommand to adapt the LLM to a dataset's report style. Bundles shipped: `abdomen-ct`, `brain-mr`, `chest-ct`, `chest-xr`, `head-ct`. See [`src/radmatch/assets/fewshot/README.md`](https://github.com/raidium-med/RadMatch/blob/main/src/radmatch/assets/fewshot/README.md) to add your own.

## Per-stage usage

Each stage is also its own subcommand, so you can re-run just one. Findings and matches are cached on disk, so a costly earlier stage is reused across later-stage configurations.

### Stage 0: Extract study indications *(optional)*

When the study indication is available, parse it out of each report and pass it downstream as clinical context. It conditions finding significance, matching, and attribute-error judgements on the clinical question.

```bash
uv run radmatch extract_indications \
  --reports /path/to/ground_truth_reports \
  --output-dir /path/to/indications \
  --llm-extractor local:google/gemma-4-31B-it --workers 64
```

Writes one `<series>.txt` per report, empty where no indication was found. Pass the directory to any downstream subcommand with `--indications PATH`; after `extract_findings` copies it into the results directory, `match` and `score` pick it up automatically.

### Stage 1: Extract findings

```bash
uv run radmatch extract_findings \
  --reports-gt /path/to/ground_truth_reports \
  --reports-pred /path/to/predicted_reports \
  --output-dir /path/to/output \
  --llm-extractor local:google/gemma-4-31B-it \
  --workers 64 \
  --fewshot chest-ct
```

- Use `--workers` to control concurrency.
- Use `--limit` to process only a subset of reports during debugging.
- Use `--findings-gt` to reuse existing ground-truth findings instead of re-extracting them.
- Use `--indications` to inject Stage 0 output as context.

Writes findings JSON into `radmatch_results/findings_gt/` and `radmatch_results/findings_pred/`.

### Stage 2: Match findings

```bash
uv run radmatch match \
  --results-dir /path/to/output/radmatch_results \
  --llm-judge local:google/gemma-4-31B-it --workers 64 --fewshot chest-ct
```

### Stage 3: Score the alignment

```bash
uv run radmatch score \
  --results-dir /path/to/output/radmatch_results \
  --llm-judge local:google/gemma-4-31B-it --workers 64 --fewshot chest-ct
```

## How RadMatch works

For each (ground-truth, predicted) report pair, RadMatch runs a three-stage pipeline:

```
Stage 0 (LLM x 1, optional) Extract the study indication from each report
Stage 1 (LLM x 2)           Extract atomic findings + clinical significance
Stage 2 (LLM x 1)           Many-to-many matching on clinical equivalence
Stage 3a (deterministic)    Comparators on structured attributes
Stage 3b (LLM x ⌈N/10⌉)     LLM judgement of free-text attributes (N = matched pairs)
Stage 3c (deterministic)    MUC classification + actionable-error count
```

**Stage 1** breaks each report into atomic findings — single-sentence clinical observations — and tags each with its clinical significance (`critical` / `urgent` / `notable` / `routine`).

**Stage 2** matches every predicted finding to one or more ground-truth findings, and vice versa: an umbrella claim on one side ("Bilateral pleural effusions", "Multilevel cervical spondylosis C2-C3 through C7-T1") binds each atom it covers on the other. Status conflicts ("pneumothorax present" vs "no pneumothorax") and laterality flips (same organ and pathology, wrong side) still match, so Stage 3 records them as one error on the right dimension rather than as a miss plus a hallucination. Stage 2 only links findings; whether a link is correct is judged in Stage 3, so boilerplate such as "Study unremarkable" bound to a real abnormality comes out `INC`. Each report pair is matched in a single call; a long report needs a long answer, so that call gets three times `RADMATCH_REQUEST_TIMEOUT_S` (540 s by default), and a timeout is not retried.

**Stage 3** scores each matched pair on seven attribute dimensions: three structured (`clinical_status`, `comparison`, `measurement`) handled by deterministic comparators, and four free-text (`location`, `severity`, `morphology`, `certainty`) handled by an LLM. Every detected error is `major` or `minor`. Each pair then lands in one of five MUC categories:

| Category | Meaning |
|---|---|
| `COR` | Matched, no attribute errors. |
| `PAR` | Matched with only minor errors — finding identified, descriptors imprecise. Counts as a hit in safety recalls. |
| `INC` | Matched but materially wrong: status inverted, or at least one major attribute error. Counts as a miss. |
| `MIS` | Ground-truth finding unmatched — missed by the model. |
| `SPU` | Predicted finding unmatched — hallucinated. |

### Error characterization

Every difference within a matched pair is attributed to one of seven dimensions and graded
`major` or `minor`, so an error profile says *what kind* of mistake a system makes.

| Dimension | Graded by | What it compares |
|---|---|---|
| `clinical_status` | comparator | Presence vs absence. Any disagreement is a status inversion, always major. |
| `comparison` | comparator | Longitudinal trajectory. Major when it crosses between benign (`stable`, `improving`, `resolved`) and active (`worsening`, `new`), or when the prediction drops an active trajectory the ground truth records. |
| `measurement` | comparator + LLM | Numeric values against per-category thresholds; adding or omitting a value is minor. The LLM adds only differences that cross a clinical decision boundary. |
| `location` | LLM | Anatomic placement, including laterality and sub-anatomic detail. A left/right flip on a paired structure is always major. |
| `severity` | LLM | Qualitative magnitude — mild / moderate / severe, small / large. Major when it crosses an action threshold. |
| `morphology` | LLM | Shape, margin, character — spiculated vs smooth, solid vs cystic. |
| `certainty` | LLM | Diagnostic hedging — definite vs probable vs possible. |

`major` means the error would change management or the anatomy referred to; `minor` means
the prediction is less precise but would not mislead a clinician. Only `major` errors push a
matched pair to `INC`.

The dataset summary reports `attribute_breakdown` — a clean / minor / major count per
dimension — which localizes where a system errs, and `subsets` does the same per finding
type.

### Metrics

| Metric | Description |
|---|---|
| `actionable_errors_per_report` | Mean per-report count of `INC` + `MIS` + `SPU` where the finding involved is above `routine` significance. The headline number; lower is better. |
| `triage_recall` | Fraction of life-threatening findings (`critical` + `urgent`) the model recalled, counting `COR` and `PAR` as hits. This is the safety floor: a model can look acceptable on average while missing most urgent findings. |
| `actionable_recall` | Same, over `critical` + `urgent` + `notable`. A large gap from `triage_recall` means the model is differentially worse on the highest-stakes findings. |
| `triage_precision` | Of the predicted findings flagged at the triage tier, the fraction crediting a real finding. Flags confident over-calling. `null` when the model predicted none. |
| `actionable_precision` | Same, over the `critical` + `urgent` + `notable` prediction pool. |

Findings are also reported in `subsets` — `measurement`, `comparison`, `abnormal-regular`, `normal-regular` — each with its own MUC counts and an `actionable_errors_per_finding` rate, so a rare subset stays comparable to a common one.

### Significance tiers

Anchored to the ACR Actionable Findings Framework and the RSNA communication colour codes. Everything above `routine` counts as actionable.

| Tier | ACR | Examples |
|---|---|---|
| `critical` | red | Pneumothorax (present *or* ruled out in trauma), aortic dissection, massive PE, acute stroke, ICH |
| `urgent` | orange | Pulmonary edema, new suspicious mass, subsegmental PE, large effusion, abscess |
| `notable` | yellow | Stable granuloma, simple cyst, chronic atelectasis, minor scarring |
| `routine` | green | "Liver unremarkable", "no effusion" in general screening, anatomic variants |

### Output files

```
<output-dir>/radmatch_results/
├── metrics_summary.json             # dataset-level aggregate — the headline file
├── findings_gt/<series>.json        # Stage 1 — atomic findings from each GT report
├── findings_pred/<series>.json      # Stage 1 — atomic findings from each prediction
├── findings_{gt,pred}_config.json   # Stage 1 — the extraction config the findings came from
├── matching/<series>.json           # Stage 2 — finding-pair alignment + reasoning
├── attribute_errors/<series>.json   # Stage 3 — raw errors + MUC records per matched pair
├── per_report_metrics/<series>.json # per-report actionable errors, MUC counts, safety
└── indications/<series>.txt         # the indication used as context, when supplied
```

### Output formats

<details>
<summary>Finding JSON (Stage 1 output)</summary>

```json
[
  {
    "finding_id": "gt_001",
    "text": "Single-sentence clinical observation.",
    "clinical_status": "normal|abnormal",
    "clinical_significance": "critical|urgent|notable|routine",
    "comparison": "stable|improving|worsening|new|resolved | null",
    "measurements": [
      { "value": 5.2, "unit": "mm", "category": "size|count|attenuation|ratio|other" }
    ]
  }
]
```

</details>

<details>
<summary>Matching JSON (Stage 2 output)</summary>

```json
{
  "matches": [
    {
      "pred_id": "pred_001",
      "gt_id": "gt_001",
      "reasoning": "Brief explanation of the match"
    }
  ],
  "unmatched_pred": ["pred_002"],
  "unmatched_gt": ["gt_003"]
}
```

</details>

<details>
<summary><code>metrics_summary.json</code> (aggregated metrics)</summary>

```json
{
  "metadata": {
    "radmatch_version": "0.2.2",
    "llm_judge": "local:google/gemma-4-31B-it",
    "fewshot": "chest-ct",
    "n_reports": 100,
    "total_gt_findings": 401,
    "total_pred_findings": 382,
    "runtime": 612.9,
    "token_usage": { "prompt_tokens": 4565000, "completion_tokens": 211000, "calls": 396 },
    "token_cost": 0.0
  },
  "actionable_errors_per_report": 1.31,
  "actionable_errors_total": 131,
  "actionable_errors_per_finding": 0.42,
  "actionable_findings_total": 312,
  "clinical_safety_summary": {
    "triage_recall": 0.85,
    "actionable_recall": 0.79,
    "triage_precision": 0.88,
    "actionable_precision": 0.82
  },
  "muc_counts": { "COR": 215, "PAR": 72, "INC": 73, "MIS": 41, "SPU": 22 },
  "attribute_breakdown": {
    "location": { "evaluated": 287, "clean": 240, "minor": 31, "major": 16 },
    "severity": { "...": "..." }
  },
  "subsets": { "measurement": { "...": "..." } }
}
```

`clinical_safety_summary` also carries the hit and total counts behind each rate, and
`attribute_breakdown` has one entry per dimension.

</details>

## Dashboard

The optional **RadMatch Evaluation Dashboard** explores results report by report — findings side by side, coloured by match outcome, with the attribute errors and judge reasoning behind each pair.

```bash
pip install "radmatch[dashboard]"

# one-time index per results dir, for fast filtering
python -m radmatch.dashboard.build_dashboard_data --results-dir /path/to/output

radmatch-dashboard
```

Then point it at `/path/to/output` in the sidebar, or open `http://localhost:8501/?results_dir=/path/to/output` directly.

## Self-hosted models

Any open model behind an **OpenAI-compatible** endpoint (vLLM, SGLang, Ollama, TGI, ...) works, which keeps report text off a hosted API. Address it with a `local:` prefix, where the part after the prefix matches the server's served-model name, and point `RADMATCH_LOCAL_BASE_URL` at the server (`RADMATCH_LOCAL_API_KEY` if it needs one). The [Quick start](#quick-start) serves Gemma-4-31B this way; on a single smaller GPU, `google/gemma-4-12B-it` fits one card.

- `--llm-extractor` and `--llm-judge` are independent, so you can mix a local extractor with a hosted judge.
- Structured output uses the OpenAI `response_format` json_schema, which recent vLLM/SGLang map to guided decoding — use a server version that supports it.
- Set `--workers` to the server's concurrency; continuous batching does the rest.
- Local requests are sent with `temperature=0` and `seed=42` so repeat runs are reproducible; hosted APIs expose no equivalent guarantee. Override with `RADMATCH_LOCAL_TEMPERATURE` / `RADMATCH_LOCAL_SEED`. Continuous batching can still perturb greedy decoding, so determinism is close but not guaranteed.

## Adding a new LLM provider

RadMatch ships with clients for **OpenAI**, **Anthropic**, **Mistral**, and a generic OpenAI-compatible local client. Adding another hosted provider is three mechanical steps:

1. **Register the model(s)** in `src/radmatch/constants.py` by adding a new key to `MODEL_CATALOG`:

   ```python
   MODEL_CATALOG: dict[str, dict[str, dict[str, float] | None]] = {
       "mistral": {"magistral-medium-2509": {"input": 2.00, "output": 5.00, "cached_input": 0.20}},
       "openai": {"gpt-5.5": {...}, ...},
       "my_provider": {"my-model-v1": None},   # <-- add your provider and model IDs
   }
   ```

   Prices are USD per 1M tokens and only feed `token_cost`; `None` registers the model without pricing it.

2. **Implement a client** in `src/radmatch/llm_utils/llm_clients.py` — subclass `Client` and implement `complete(messages, response_format, max_tokens)`. `OpenAIClient` and `MistralClient` are working references.

3. **Wire the factory and the credential check** in the same file: add a branch to `build_client`, and add the required environment variables to `_PROVIDER_ENV_VARS` so `assert_credentials_for` fails fast when they are missing. Each entry there is a tuple of alternative variable sets, so a provider reachable two ways is satisfied by either.

Document the new variables in `env.example`.

## Citation

If you use RadMatch, please cite:

```bibtex
@inproceedings{corbiere2026radmatch,
  title     = {RadMatch: Auditable Radiology Report Evaluation via Finding-Level Matching},
  author    = {Corbi{\`e}re, Charles and Machado, L{\'e}o and Charley, Aubin and
               Caillard, Baptiste and Manceron, Pierre and Dancette, Corentin},
  booktitle = {Proceedings of the European Conference on Computer Vision (ECCV) Workshops,
               Medical Foundation Models Benchmarking Workshop},
  year      = {2026},
}
```

## License

RadMatch is released under the [Apache License 2.0](https://github.com/raidium-med/RadMatch/blob/main/LICENSE).
