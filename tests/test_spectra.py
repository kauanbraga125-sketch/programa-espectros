"""Meaningful checks of data preservation, display math, import and persistence."""

from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from imespec_app.spectra import (
    Spectrum,
    automatic_spacing,
    common_range,
    display_curves,
    read_spectrum,
    load_project,
    save_project,
    spectral_groups,
    temperature_from_name,
    sort_by_temperature,
    DEFAULT_SETTINGS,
)


class SpectrumTests(unittest.TestCase):
    def setUp(self):
        self.x = np.array([1200.0, 1250.0, 1300.0, 1350.0])
        self.a = Spectrum(
            self.x, [10.0, 20.0, 80.0, 15.0], "a_300K.txt", temperature=300
        )
        self.b = Spectrum(
            self.x, [100.0, 120.0, 200.0, 160.0], "b_15K.txt", temperature=15
        )

    def test_constant_offset_preserves_signal_and_original_arrays(self):
        hashes = [s.fingerprint for s in (self.a, self.b)]
        result = display_curves([self.a, self.b], spacing=300)
        np.testing.assert_array_equal(result[0][1], self.a.y)
        np.testing.assert_array_equal(result[1][1], self.b.y + 300)
        np.testing.assert_allclose(np.diff(result[1][1]), np.diff(self.b.y))
        self.assertEqual(hashes, [s.fingerprint for s in (self.a, self.b)])
        with self.assertRaises(ValueError):
            self.a.y[0] = 9

    def test_reference_alignment_matches_teachers_convention(self):
        result = display_curves([self.a, self.b], spacing=50, align=True, xref=1251)
        # At nearest point 1250: B is shifted from 120 to A's 20, then +50.
        np.testing.assert_array_equal(result[1][1], self.b.y - 100 + 50)
        self.assertEqual(result[1][2], -50)
        overlay = display_curves(
            [self.a, self.b], mode="overlay", align=True, xref=1251
        )
        np.testing.assert_array_equal(overlay[1][1], self.b.y)

    def test_auto_spacing_keeps_curves_apart_without_rebasing(self):
        spectra = [self.b, self.a, self.b]
        gap = automatic_spacing(spectra)
        curves = display_curves(spectra, spacing=gap)
        for left, right in zip(curves, curves[1:]):
            self.assertLess(left[1].max(), right[1].min())

    def test_waterfall_has_no_cascade_offset(self):
        result = display_curves([self.a, self.b], mode="waterfall", spacing=1000)
        np.testing.assert_array_equal(result[1][1], self.b.y)
        self.assertEqual(result[1][2], 0)

    def test_temperature_parsing_is_limited_to_explicit_kelvin(self):
        self.assertEqual(temperature_from_name("sample_Lx20_12_3K.txt"), 12.3)
        self.assertEqual(temperature_from_name("Cn_A_514nm_20x_12.3K_volta.txt"), 12.3)
        self.assertEqual(temperature_from_name("sample_85K.txt"), 85)
        self.assertIsNone(temperature_from_name("sample_514nm_3x45s_Lx20.txt"))
        self.assertIsNone(temperature_from_name("sample_AGelad.txt"))
        self.assertEqual(
            [s.temperature for s in sort_by_temperature([self.a, self.b])], [15, 300]
        )

    def test_spectral_windows_stay_separate_and_axes_are_preserved(self):
        high = Spectrum([5400, 5500, 5600], [2, 3, 2], "high")
        groups = spectral_groups([self.a, self.b, high])
        self.assertEqual([len(g[2]) for g in groups], [2, 1])
        self.assertIsNone(common_range([self.a, high]))
        with self.assertRaises(ValueError):
            display_curves([self.a, high], align=True, xref=1250)
        descending = Spectrum([3, 2, 1], [10, 20, 30], "descending")
        np.testing.assert_array_equal(descending.x, [3, 2, 1])

    def test_import_headers_decimal_comma_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "amostra_20K.csv"
            path.write_text(
                "Laser 514 nm\nX;Y\n1200,0;2,5\n1201,0;3,7\n1202,0;2,9\n",
                encoding="utf-8",
            )
            s = read_spectrum(path)
            np.testing.assert_array_equal(s.y, [2.5, 3.7, 2.9])
            self.assertEqual(s.temperature, 20)
            for text in ("1 2 3\n2 3 4\n", "1 2\n2 nan\n3 4\n", "1 2\n1 3\n"):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_spectrum(path)

    def test_project_roundtrip_and_integrity_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "series.imespec"
            self.b.color = "#DC2626"
            self.b.visible = False
            self.b.label = "Resfriamento"
            settings = dict(DEFAULT_SETTINGS, spacing=321, automatic=False)
            save_project(path, [self.b, self.a], settings)
            restored, restored_settings = load_project(path)
            self.assertEqual([s.uid for s in restored], [self.b.uid, self.a.uid])
            self.assertEqual(restored[0].fingerprint, self.b.fingerprint)
            self.assertEqual(restored[0].label, "Resfriamento")
            self.assertFalse(restored[0].visible)
            self.assertEqual(restored_settings, settings)
            document = json.loads(path.read_text())
            document["spectra"][0]["y"][0] = 900
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "integridade"):
                load_project(path)

    def test_invalid_options_and_numerical_overflow_are_rejected(self):
        for spacing in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                display_curves([self.a, self.b], spacing=spacing)
        with self.assertRaises(ValueError):
            Spectrum([1, 2, 2], [1, 2, 3], "bad")
        with self.assertRaises(ValueError):
            Spectrum([1, 2], [1, float("inf")], "bad")


if __name__ == "__main__":
    unittest.main()
