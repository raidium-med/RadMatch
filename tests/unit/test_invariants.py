"""Project-wide invariants — constants structure, CLI smoke."""

from __future__ import annotations

import pytest

from radmatch import cli, constants

# ============================================================================
# Constants — structural invariants only (no per-value asserts)
# ============================================================================


def test_clinical_significance_keys_consistent():
    assert constants.DEFAULT_CLINICAL_SIGNIFICANCE in constants.CLINICAL_SIGNIFICANCE_VALUES


def test_actionable_tiers_excludes_default():
    assert set(constants.ACTIONABLE_SIGNIFICANCE_TIERS).issubset(constants.CLINICAL_SIGNIFICANCE_VALUES)
    assert constants.DEFAULT_CLINICAL_SIGNIFICANCE not in constants.ACTIONABLE_SIGNIFICANCE_TIERS


def test_triage_is_subset_of_actionable():
    assert set(constants.TRIAGE_SIGNIFICANCE_TIERS).issubset(set(constants.ACTIONABLE_SIGNIFICANCE_TIERS))


def test_comparison_buckets_partition_comparison_values():
    union = constants.BENIGN_COMPARISONS | constants.ACTIVE_COMPARISONS
    assert union == constants.COMPARISON_VALUES
    assert constants.BENIGN_COMPARISONS.isdisjoint(constants.ACTIVE_COMPARISONS)


def test_muc_categories_set():
    """Output schema covers exactly the five expected categories. Set check so
    cosmetic reorderings don't trip the test — semantic membership only."""
    assert set(constants.MUC_CATEGORIES) == {"COR", "PAR", "INC", "MIS", "SPU"}


# ============================================================================
# CLI — argparse smoke for each subcommand
# ============================================================================


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            [
                "extract_findings",
                "--reports-gt",
                "/tmp/gt",
                "--reports-pred",
                "/tmp/p",
                "--output-dir",
                "/tmp/o",
                "--llm-extractor",
                "gpt-5-4",
            ],
            id="extract_findings",
        ),
        pytest.param(
            ["match", "--results-dir", "/tmp/r", "--llm-judge", "gpt-5-4"],
            id="match",
        ),
        pytest.param(
            ["score", "--results-dir", "/tmp/r", "--llm-judge", "gpt-5-4"],
            id="score",
        ),
        pytest.param(
            [
                "run_all",
                "--reports-gt",
                "/tmp/gt",
                "--reports-pred",
                "/tmp/p",
                "--output-dir",
                "/tmp/o",
                "--llm-extractor",
                "gpt-5-4",
                "--llm-judge",
                "gpt-5-4",
            ],
            id="run_all",
        ),
    ],
)
def test_cli_subcommand_parses(argv):
    args = cli.parse_args(argv)
    assert args.command == argv[0]
