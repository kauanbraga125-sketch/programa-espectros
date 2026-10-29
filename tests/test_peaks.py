"""Scientific checks of model definitions, recovery, robust fitting and comparisons."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.integrate import trapezoid
from imespec_app.peaks import (
    BANDS,
    Band,
    Peak,
    profile,
    window_area,
    fit_band,
    primary,
    relative_shift,
    area_ratio,
    analyze_series,
    export_csv,
    export_json,
    export_comparisons_csv,
)
from imespec_app.spectra import Spectrum


class PeakTests(unittest.TestCase):
    def synthetic(self, model="lorentzian", noise=0.8):
        x = np.linspace(1780, 1940, 650)
        rng = np.random.default_rng(7)
        y = (
            50
            + 0.1 * (x - 1860)
            + profile(x, 1800, 1836, 18, model, 0.35)
            + profile(x, 13000, 1864.3, 13, model, 0.35)
            + rng.normal(0, noise, len(x))
        )
        return x, y

    def test_profiles_have_declared_area_and_fwhm(self):
        for model in ("lorentzian", "gaussian", "pseudo_voigt"):
            c, w, A = 1850.0, 12.0, 200.0
            vals = profile(np.array([c - w / 2, c, c + w / 2]), A, c, w, model, 0.3)
            np.testing.assert_allclose(vals[[0, 2]], vals[1] / 2)
            xx = np.linspace(c - 200, c + 200, 100001)
            yy = profile(xx, A, c, w, model, 0.3)
            self.assertAlmostEqual(
                trapezoid(yy, xx),
                window_area(A, c, w, xx[0], xx[-1], model, 0.3),
                places=5,
            )

    def test_recovers_two_components_and_preserves_arrays(self):
        for model in ("lorentzian", "gaussian", "pseudo_voigt"):
            x, y = self.synthetic(model)
            original = y.copy()
            r = fit_band(x, y, BANDS[0], model=model)
            self.assertTrue(r["usable"], r["review_reasons"])
            self.assertAlmostEqual(primary(r)["center_cm1"], 1864.3, delta=0.05)
            self.assertAlmostEqual(primary(r)["fwhm_cm1"], 13, delta=0.2)
            np.testing.assert_array_equal(y, original)
            np.testing.assert_allclose(
                np.array(r["model_y"]) + r["residual"], r["observed"]
            )

    def test_robust_loss_resists_isolated_spike_without_deleting_it(self):
        x, y = self.synthetic()
        y[380] += 30000
        r = fit_band(x, y, BANDS[0])
        ordinary = fit_band(x, y, BANDS[0], robust=False)
        self.assertAlmostEqual(primary(r)["center_cm1"], 1864.3, delta=0.1)
        self.assertGreater(
            abs(primary(ordinary)["center_cm1"] - 1864.3),
            abs(primary(r)["center_cm1"] - 1864.3),
        )
        self.assertEqual(len(r["observed"]), len(y))
        self.assertEqual(max(r["observed"]), max(y))

    def test_noise_only_is_flagged(self):
        x = np.linspace(3570, 3830, 450)
        y = 50 + 0.03 * (x - 3700) + np.random.default_rng(3).normal(0, 2, len(x))
        r = fit_band(x, y, BANDS[1])
        self.assertFalse(r["usable"])

    def test_conditional_bootstrap_is_reproducible(self):
        x, y = self.synthetic()
        a = fit_band(x, y, BANDS[0], bootstrap=15, seed=51)
        b = fit_band(x, y, BANDS[0], bootstrap=15, seed=51)
        self.assertEqual(a["bootstrap_successful"], 15)
        self.assertEqual(primary(a)["center_se_cm1"], primary(b)["center_se_cm1"])
        self.assertTrue(a["uncertainty_excludes_calibration_and_model_systematics"])
        self.assertGreater(primary(a)["center_se_cm1"], 0)

    def test_validation_and_descending_axis(self):
        x, y = self.synthetic()
        r = fit_band(x[::-1], y[::-1], BANDS[0])
        self.assertAlmostEqual(primary(r)["center_cm1"], 1864.3, delta=0.05)
        with self.assertRaises(ValueError):
            fit_band(x[:100], y[:100], BANDS[0])
        with self.assertRaises(ValueError):
            fit_band(x, np.full(len(x), np.nan), BANDS[0])
        with self.assertRaises(ValueError):
            fit_band(x, y, BANDS[0], bootstrap=-1)

    @staticmethod
    def result(order, center, area=100.0, se=0.2, tentative=False):
        return {
            "band": {"order": order, "tentative": tentative},
            "usable": True,
            "primary_index": 0,
            "components": [
                {
                    "center_cm1": center,
                    "center_se_cm1": se,
                    "area_model_au_cm1": area,
                    "area_se_au_cm1": 1.0,
                }
            ],
        }

    def test_overtone_definition_and_error_propagation(self):
        f = self.result(1, 1860)
        a = self.result(2, 3700)
        b = self.result(3, 5500)
        r = relative_shift(f, a)
        self.assertAlmostEqual(r["relative_redshift_percent"], 100 * (2 - 3700 / 1860))
        self.assertAlmostEqual(
            r["statistical_se_percent"],
            100 * np.sqrt((3700 / 1860**2 * 0.2) ** 2 + (0.2 / 1860) ** 2),
        )
        self.assertAlmostEqual(
            relative_shift(f, b, a)["relative_redshift_percent"],
            100 * (1 - 1800 / 1860),
        )
        with self.assertRaises(ValueError):
            relative_shift(f, b)
        with self.assertRaises(ValueError):
            relative_shift(f, self.result(4, 7280, tentative=True), b)

    def test_area_divisors_and_zero_reference(self):
        f = self.result(1, 1860, area=100)
        a = self.result(2, 3700, area=40)
        self.assertAlmostEqual(area_ratio(a, f)["ratio"], 0.4)
        self.assertAlmostEqual(area_ratio(a, f, 2, 1)["ratio"], 0.2)
        f["components"][0]["area_model_au_cm1"] = 0
        with self.assertRaises(ValueError):
            area_ratio(a, f)

    def test_series_exports_unknown_temperatures_and_cycles(self):
        x = np.linspace(1700, 3900, 3000)
        y = 20 + profile(x, 15000, 1864, 12) + profile(x, 10000, 3704, 30)
        s = Spectrum(x, y, "sample_A_15K.txt", temperature=15)
        r = analyze_series([s], bands=(BANDS[0].single(), BANDS[1]), bootstrap=0)
        self.assertEqual(len(r["fits"]), 2)
        self.assertEqual(r["comparisons"][0]["status"], "preliminar")
        r2 = analyze_series([s, s], bands=(BANDS[0].single(), BANDS[1]))
        self.assertIn("ambígua", r2["comparisons"][0]["reason"])
        s.temperature = None
        r3 = analyze_series([s], bands=(BANDS[0].single(), BANDS[1]))
        self.assertIsNone(r3["comparisons"][0]["relative_shift"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            export_json(p / "report.json", r)
            export_csv(p / "parameters.csv", r)
            export_comparisons_csv(p / "comparison.csv", r)
            self.assertIn(
                "center_cm1", (p / "parameters.csv").read_text(encoding="utf-8-sig")
            )
            self.assertIn(
                "relative_redshift_percent",
                (p / "comparison.csv").read_text(encoding="utf-8-sig"),
            )


if __name__ == "__main__":
    unittest.main()
