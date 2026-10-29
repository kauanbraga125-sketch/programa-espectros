"""Actual native dialog, background jobs, inspection and exports."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile, time, unittest, json
import numpy as np
from PySide6.QtWidgets import QApplication
from imespec_app.window import MainWindow
from imespec_app.spectra import Spectrum
from imespec_app.peaks import profile


class PeakDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        x = np.linspace(1700, 3900, 2600)
        y = (
            30
            + 0.002 * (x - 1700)
            + profile(x, 12000, 1864, 14)
            + profile(x, 8000, 3704, 30)
        )
        self.source = Spectrum(x, y, "sample_A_15K.txt", temperature=15)
        self.window = MainWindow()
        self.window.spectra = [self.source]
        self.window.show()
        self.window.open_peak_analysis()
        self.d = self.window._peak_analysis
        self.d.components.setValue(1)
        self.app.processEvents()

    def wait(self):
        end = time.monotonic() + 40
        while self.d.running and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(self.d.running)

    def tearDown(self):
        if self.d.running:
            self.d.cancel()
            self.wait()
        self.d.close()
        self.app.processEvents()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_fits_inspects_and_exports_without_changing_source(self):
        original = self.source.fingerprint
        self.d.run_analysis()
        self.wait()
        self.assertEqual(self.d.table.rowCount(), 2)
        self.assertEqual(self.source.fingerprint, original)
        self.assertIsNotNone(self.d.report)
        self.assertTrue(self.d.export_button.isEnabled())
        self.d.table.selectRow(1)
        self.app.processEvents()
        self.assertEqual(len(self.d.figure.axes), 2)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "analysis.v1.json"
            self.assertTrue(self.d.export_results(path=p))
            saved = json.loads(p.read_text())
            self.assertEqual(len(saved["fits"]), 2)
            self.assertTrue((p.parent / "analysis.v1.csv").exists())
            self.assertTrue((p.parent / "analysis.v1_sobretons.csv").exists())

    def test_custom_two_component_configuration(self):
        self.d.preset.setCurrentIndex(self.d.preset.findData("custom"))
        self.d.components.setValue(2)
        band = self.d.selected_bands()[0]
        self.assertEqual(len(band.peaks), 2)
        self.assertEqual(band.order, 0)

    def test_cancellation_ends_thread_safely(self):
        self.d.bootstrap.setValue(300)
        self.d.run_analysis()
        self.d.cancel()
        self.wait()
        self.assertTrue(self.d.report["cancelled"])
        self.assertTrue(self.d.run_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
