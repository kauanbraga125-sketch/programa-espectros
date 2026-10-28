"""User-flow checks for the Qt workspace, using a real offscreen Qt window."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import csv
import tempfile
import time
import unittest

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from imespec_app.window import MainWindow


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.paths = []
        for temperature in [300, 15, 80]:
            x = np.linspace(1700.0, 2000.0, 250)
            y = 10 + temperature / 5 + 100 * np.exp(-(((x - 1850) / 12) ** 2))
            path = self.root / f"sample_{temperature}K.txt"
            np.savetxt(path, np.column_stack([x, y]), header="Raman shift intensity")
            self.paths.append(path)
        self.window = MainWindow()
        self.window.show()
        self.window.import_paths(self.paths)
        self.wait_import()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def wait_import(self):
        deadline = time.monotonic() + 20
        while (
            self.window._busy or self.window._thread is not None
        ) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window._busy)
        self.assertIsNone(self.window._thread)
        self.window.render()
        self.app.processEvents()

    def test_import_generates_cascade_and_preserves_raw_data(self):
        self.assertEqual([s.temperature for s in self.window.spectra], [15, 80, 300])
        self.assertEqual(len(self.window.ax.lines), 3)
        self.assertEqual(self.window.settings["mode"], "cascade")
        self.assertFalse(self.window.settings["align"])
        self.assertTrue(self.window.auto_check.isChecked())
        self.assertFalse(self.window.spacing_spin.isEnabled())
        self.assertIn("cm⁻¹", self.window.ax.get_xlabel())
        self.assertIn("deslocamento", self.window.ax.get_ylabel())

    def test_visibility_order_and_plot_modes(self):
        self.window.list_widget.item(0).setCheckState(Qt.CheckState.Unchecked)
        self.window.render()
        self.assertEqual(len(self.window._last_curves), 2)
        self.window.set_all_visible(True)
        self.window.reverse_order()
        self.window.render()
        self.assertEqual(
            [s.temperature for s in self.window.active_spectra()], [300, 80, 15]
        )
        self.window.sort_temperature()
        self.window.set_mode("overlay")
        for s, shown, shift in self.window._last_curves:
            np.testing.assert_array_equal(shown, s.y)
            self.assertEqual(shift, 0)
        self.window.set_mode("waterfall")
        self.assertEqual(self.window.ax.get_ylabel(), "Temperatura (K)")
        self.window.spectra[0].temperature = None
        self.window.render()
        self.assertEqual(self.window.ax.get_ylabel(), "Ordem da série")

    def test_manual_spacing_alignment_and_properties(self):
        self.window.auto_check.setChecked(False)
        self.window.spacing_spin.setValue(25)
        self.window.align_check.setChecked(True)
        self.window.xref_spin.setValue(1900)
        self.window.render()
        levels = []
        for s, shown, shift in self.window._last_curves:
            levels.append(shown[np.argmin(abs(s.x - 1900))])
        np.testing.assert_allclose(np.diff(levels), [25, 25])
        self.window.name_edit.setText("Amostra fria")
        self.window._edit_label()
        self.assertEqual(self.window.list_widget.currentItem().text(), "Amostra fria")
        self.window.temp_edit.setText("12,3")
        self.window._edit_temperature()
        self.assertEqual(self.window.selected_spectrum().temperature, 12.3)

    def test_project_and_exports_reproduce_visible_curves(self):
        hashes = [s.fingerprint for s in self.window.spectra]
        project = self.root / "series.imespec"
        self.assertTrue(self.window.save_session(path=project))
        self.assertTrue(self.window.export_figure(path=self.root / "figure.png"))
        self.assertTrue(self.window.export_figure(path=self.root / "figure.pdf"))
        self.assertTrue(self.window.export_figure(path=self.root / "figure.svg"))
        self.assertTrue(self.window.export_data(path=self.root / "data.csv"))
        with (self.root / "data.csv").open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 750)
        for row in rows:
            self.assertAlmostEqual(
                float(row["raw_intensity_au"]) + float(row["display_shift_au"]),
                float(row["display_intensity_au"]),
                places=10,
            )
        self.window.open_project(path=project)
        self.assertEqual(hashes, [s.fingerprint for s in self.window.spectra])
        self.assertFalse(self.window.dirty)
        self.assertGreater((self.root / "figure.png").stat().st_size, 1000)

    def test_multiple_windows_and_compact_layout(self):
        extra = self.root / "overtone_15K.txt"
        np.savetxt(extra, [[5400, 1], [5500, 3], [5600, 1]])
        self.window.import_paths([extra], append=True)
        self.wait_import()
        self.assertEqual(self.window.region_combo.count(), 2)
        self.window.region_combo.setCurrentIndex(1)
        self.window.render()
        self.assertEqual(len(self.window._last_curves), 1)
        self.window.resize(1120, 760)
        self.app.processEvents()
        self.assertFalse(self.window.settings_dock.isVisible())
        self.window.options_button.click()
        self.app.processEvents()
        self.assertTrue(self.window.settings_dock.isVisible())
        self.window.set_all_visible(False)
        self.window.render()
        self.assertFalse(self.window.export_figure(path=self.root / "empty.png"))
        self.window.set_all_visible(True)
        self.window.render()
        self.assertEqual(len(self.window._last_curves), 1)


if __name__ == "__main__":
    unittest.main()
