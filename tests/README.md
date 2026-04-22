# RadMatch Tests

Unit and integration tests for the `radmatch` package.

## Test Files

**Unit Tests:**
- `test_io.py` - I/O operations, JSON handling, file finding
- `test_extract_utils.py` - Finding normalization and file operations
- `test_prompts.py` - Prompt building and example loading
- `test_llm_clients.py` - Error detection and retry logic
- `test_batch_utils.py` - Batch utility functions
- `test_inference.py` - Inference utilities and helpers
- `test_metrics.py` - Metrics computation (F1, precision, recall, MRE)
- `test_matching.py` - Matching logic and statistics
- `test_eval_utils.py` - Evaluation utility functions
- `test_eval_logging.py` - Evaluation logging functionality

**Integration Tests:**
- `test_extract_findings.py` - Finding extraction workflow (with mocked LLM)
- `test_eval.py` - Evaluation workflows

## Running Tests

### Setup

From the `radmatch/` directory:

```bash
uv sync
```

### Run Tests

**All tests:**
```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

**Unit tests only:**
```bash
uv run python -m unittest discover -s tests/unit -p "test_*.py" -v
```

**Integration tests only:**
```bash
uv run python -m unittest discover -s tests/integration -p "test_*.py" -v
```

**Specific test file:**
```bash
uv run python -m unittest tests.unit.test_io -v
```

**Specific test class:**
```bash
uv run python -m unittest tests.unit.test_io.TestLoadJson -v
```

**Specific test method:**
```bash
uv run python -m unittest tests.unit.test_io.TestLoadJson.test_load_json_valid -v
```
