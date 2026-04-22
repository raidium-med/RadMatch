"""Tests for evaluation utility functions."""

from __future__ import annotations

import unittest

from radmatch import constants
from radmatch.evaluation import eval_utils


class TestNormalizeComparison(unittest.TestCase):
    """Test normalize_comparison function."""

    def test_normalize_comparison_valid(self):
        """Test normalizing valid comparison values."""
        self.assertEqual(eval_utils.normalize_comparison("stable"), "stable")
        self.assertEqual(eval_utils.normalize_comparison("IMPROVING"), "improving")
        self.assertEqual(eval_utils.normalize_comparison("  Worsening  "), "worsening")
        self.assertEqual(eval_utils.normalize_comparison("new"), "new")
        self.assertEqual(eval_utils.normalize_comparison("RESOLVED"), "resolved")

    def test_normalize_comparison_invalid(self):
        """Test normalizing invalid comparison values."""
        self.assertIsNone(eval_utils.normalize_comparison("invalid"))
        self.assertIsNone(eval_utils.normalize_comparison("unknown"))

    def test_normalize_comparison_empty(self):
        """Test normalizing empty comparison values."""
        self.assertIsNone(eval_utils.normalize_comparison(None))
        self.assertIsNone(eval_utils.normalize_comparison(""))
        self.assertIsNone(eval_utils.normalize_comparison("   "))

    def test_normalize_comparison_non_string(self):
        """Test normalizing non-string comparison values."""
        self.assertIsNone(eval_utils.normalize_comparison(123))
        self.assertIsNone(eval_utils.normalize_comparison([]))


class TestNormalizeMeasurementToBaseUnit(unittest.TestCase):
    """Test normalize_measurement_to_base_unit function."""

    def test_normalize_measurement_no_unit(self):
        """Test normalization when unit is None."""
        result = eval_utils.normalize_measurement_to_base_unit(5.0, None, "size")
        self.assertEqual(result, 5.0)

    def test_normalize_measurement_size_units(self):
        """Test normalization of size units to mm."""
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "mm", "size"), 1.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "cm", "size"), 10.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "m", "size"), 1000.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "inch", "size"), 25.4)

    def test_normalize_measurement_attenuation_units(self):
        """Test normalization of attenuation units (HU is base unit)."""
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "hu", "attenuation"), 1.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "hounsfield", "attenuation"), 1.0)

    def test_normalize_measurement_unknown_unit(self):
        """Test normalization with unknown unit returns original value."""
        result = eval_utils.normalize_measurement_to_base_unit(5.0, "unknown_unit", "size")
        self.assertEqual(result, 5.0)

    def test_normalize_measurement_case_insensitive(self):
        """Test that unit normalization is case insensitive."""
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "CM", "size"), 10.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "Cm", "size"), 10.0)

    def test_normalize_measurement_category_ignored(self):
        """Test that category parameter doesn't affect conversion (unit dict is global)."""
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "cm", "size"), 10.0)
        self.assertEqual(eval_utils.normalize_measurement_to_base_unit(1.0, "cm", "other"), 10.0)


class TestCompareMeasurements(unittest.TestCase):
    """Test compare_measurements function."""

    def test_compare_measurements_empty(self):
        """Test comparing empty measurement lists."""
        self.assertEqual(eval_utils.compare_measurements([], []), [])
        self.assertEqual(eval_utils.compare_measurements([{"value": 5.0}], []), [])
        self.assertEqual(eval_utils.compare_measurements([], [{"value": 5.0}]), [])

    def test_compare_measurements_same_category(self):
        """Test comparing measurements in same category."""
        gt_measurements = [{"value": 10.0, "category": "size", "unit": "mm"}]
        pred_measurements = [{"value": 12.0, "category": "size", "unit": "mm"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "size")
        self.assertEqual(result[0]["gt_value"], 10.0)
        self.assertEqual(result[0]["pred_value"], 12.0)
        self.assertIsNotNone(result[0]["mre"])
        self.assertEqual(result[0]["gt_unit"], "mm")
        self.assertEqual(result[0]["pred_unit"], "mm")

    def test_compare_measurements_different_units(self):
        """Test comparing measurements with different units."""
        gt_measurements = [{"value": 1.0, "category": "size", "unit": "cm"}]
        pred_measurements = [{"value": 10.0, "category": "size", "unit": "mm"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gt_value"], 10.0)
        self.assertEqual(result[0]["pred_value"], 10.0)
        self.assertEqual(result[0]["mre"], 0.0)

    def test_compare_measurements_different_categories(self):
        """Test that measurements in different categories are not compared."""
        gt_measurements = [{"value": 10.0, "category": "size"}]
        pred_measurements = [{"value": 5.0, "category": "attenuation"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(result, [])

    def test_compare_measurements_multiple_per_category(self):
        """Test comparing multiple measurements per category."""
        gt_measurements = [
            {"value": 10.0, "category": "size", "unit": "mm"},
            {"value": 20.0, "category": "size", "unit": "mm"},
        ]
        pred_measurements = [
            {"value": 12.0, "category": "size", "unit": "mm"},
            {"value": 18.0, "category": "size", "unit": "mm"},
        ]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "size")
        self.assertIsNotNone(result[0]["mre"])

    def test_compare_measurements_unequal_lengths(self):
        """Test comparing measurements with unequal lengths (takes minimum)."""
        gt_measurements = [
            {"value": 10.0, "category": "size"},
            {"value": 20.0, "category": "size"},
            {"value": 30.0, "category": "size"},
        ]
        pred_measurements = [
            {"value": 12.0, "category": "size"},
            {"value": 18.0, "category": "size"},
        ]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)

    def test_compare_measurements_missing_category(self):
        """Test comparing measurements with missing category (uses default)."""
        gt_measurements = [{"value": 10.0}]
        pred_measurements = [{"value": 12.0}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], constants.DEFAULT_MEASUREMENT_CATEGORY)

    def test_compare_measurements_invalid_value_types(self):
        """Test comparing measurements with invalid value types."""
        gt_measurements = [{"value": "not_a_number", "category": "size"}]
        pred_measurements = [{"value": 12.0, "category": "size"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(result, [])

    def test_compare_measurements_zero_gt_value(self):
        """Test comparing measurements when GT value is zero (MRE should be None or handled)."""
        gt_measurements = [{"value": 0.0, "category": "size", "unit": "mm"}]
        pred_measurements = [{"value": 5.0, "category": "size", "unit": "mm"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["gt_value"], 0.0)
        self.assertEqual(result[0]["pred_value"], 5.0)
        self.assertIsNone(result[0]["mre"])

    def test_compare_measurements_mre_calculation(self):
        """Test MRE calculation is correct."""
        gt_measurements = [{"value": 100.0, "category": "size", "unit": "mm"}]
        pred_measurements = [{"value": 120.0, "category": "size", "unit": "mm"}]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 1)
        expected_mre = abs(120.0 - 100.0) / 100.0
        self.assertAlmostEqual(result[0]["mre"], expected_mre, places=5)

    def test_compare_measurements_multiple_categories(self):
        """Test comparing measurements across multiple categories."""
        gt_measurements = [
            {"value": 10.0, "category": "size", "unit": "mm"},
            {"value": 50.0, "category": "attenuation", "unit": "hu"},
        ]
        pred_measurements = [
            {"value": 12.0, "category": "size", "unit": "mm"},
            {"value": 55.0, "category": "attenuation", "unit": "hu"},
        ]

        result = eval_utils.compare_measurements(gt_measurements, pred_measurements)

        self.assertEqual(len(result), 2)
        categories = {r["category"] for r in result}
        self.assertEqual(categories, {"size", "attenuation"})
