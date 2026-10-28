"""Numerical checks: python -m unittest discover -s tests -v."""

from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imespec_analysis import area_ratio, integration_trace
import imespec_bib1 as core


class AreaRatioTests(unittest.TestCase):
    def test_corresponding_pixels_and_common_scale(self):
        a = np.array([[100.0, 200.0], [200.0, 150.0]])
        b = np.array([[50.0, 100.0], [50.0, 50.0]])
        expected = np.array([[2.0, 2.0], [4.0, 3.0]])
        result = area_ratio(a, b)
        np.testing.assert_array_equal(result.values, expected)
        np.testing.assert_allclose(area_ratio(7 * a, 7 * b).values, expected)
        np.testing.assert_array_equal(a, [[100.0, 200.0], [200.0, 150.0]])
        np.testing.assert_array_equal(b, [[50.0, 100.0], [50.0, 50.0]])

    def test_invalid_pixels_are_missing_with_reasons(self):
        a = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, np.nan]])
        b = np.array([[0.0, -1.0, 0.0001], [100.0, 100.0, 100.0]])
        result = area_ratio(a, b)
        np.testing.assert_array_equal(result.reasons, [[2, 2, 3], [4, 0, 1]])
        self.assertEqual(result.values[1, 1], 0.0)
        self.assertEqual(result.summary()["valid_pixels"], 1)
        self.assertTrue(np.isnan(result.values[0, :]).all())

    def test_reference_floors_and_signed_option(self):
        a = np.array([[-2.0, 10.0, 20.0]])
        b = np.array([[10.0, 20.0, 100.0]])
        result = area_ratio(a, b, absolute_floor=20.0, relative_floor_percent=0)
        np.testing.assert_array_equal(result.valid, [[False, False, True]])
        signed = area_ratio(
            a, b, relative_floor_percent=0, exclude_negative_numerator=False
        )
        self.assertEqual(signed.values[0, 0], -0.2)

    def test_all_excluded_and_overflow(self):
        result = area_ratio(np.ones((2, 2)), np.zeros((2, 2)))
        self.assertIsNone(result.summary()["median"])
        self.assertEqual(result.summary()["valid_percent"], 0.0)
        over = area_ratio([[1e308]], [[1e-308]], relative_floor_percent=0)
        self.assertEqual(over.reasons[0, 0], 5)
        self.assertTrue(np.isnan(over.values[0, 0]))

    def test_geometry_and_parameter_validation(self):
        for a, b in [([], []), ([1.0], [1.0]), ([[1.0, 2.0]], [[1.0], [2.0]])]:
            with self.assertRaises(ValueError):
                area_ratio(a, b)
        for params in [
            dict(absolute_floor=-1),
            dict(absolute_floor=np.nan),
            dict(relative_floor_percent=101),
        ]:
            with self.assertRaises(ValueError):
                area_ratio([[1.0]], [[1.0]], **params)

    def test_large_finite_statistics_do_not_overflow(self):
        result = area_ratio([[1e308, 1e308]], [[1.0, 1.0]])
        self.assertEqual(result.summary()["median"], 1e308)
        reference = area_ratio([[1e308, 1e308]], [[1e308, 1e308]])
        np.testing.assert_array_equal(reference.values, [[1.0, 1.0]])
        self.assertTrue(np.isfinite(reference.floor))
        strict = area_ratio(
            [[1e308, 1e308]], [[1e308, 1e308]], relative_floor_percent=100.0
        )
        self.assertEqual(strict.floor, 1e308)
        self.assertFalse(strict.valid.any())


class IntegrationReviewTests(unittest.TestCase):
    def test_review_matches_existing_integration_on_irregular_axes(self):
        x = np.linspace(1200.0, 1500.0, 303) ** 1.0001
        peak = np.exp(-0.5 * ((x - 1350.0) / 13.0) ** 2)
        matrix = np.column_stack(
            [x, 15.0 + 0.2 * x + 70.0 * peak, 30.0 + 0.04 * x + 180.0 * peak]
        )
        for data in [matrix, matrix[::-1]]:
            start, stop = 30, 270
            areas = core._calcular_area_raman(data, start, stop, 2, 1)
            for i in range(2):
                trace = integration_trace(data[:, 0], data[:, i + 1], start, stop)
                self.assertAlmostEqual(trace["area"], areas[0, i], places=9)

    def test_linear_background_integrates_to_zero(self):
        x = np.linspace(1.0, 100.0, 100)
        trace = integration_trace(x, 3 * x + 7, 10, 80)
        np.testing.assert_allclose(trace["corrected"], 0.0, atol=1e-13)

    def test_invalid_band_rejected(self):
        with self.assertRaises(ValueError):
            integration_trace(np.arange(10.0), np.ones(10), 0, 5)


if __name__ == "__main__":
    unittest.main()
