"""Data Quality navigation and native controls, with the existing science core."""

import os
from pathlib import Path
import runpy
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np
from matplotlib.backend_bases import MouseEvent
import imespec_bib1 as core


@unittest.skipUnless(
    os.name == "nt" or os.environ.get("DISPLAY"), "Tk display required"
)
class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        with patch.object(tk.Tk, "mainloop", lambda self: None), patch.dict(
            os.environ, {"IMESPEC_LEGACY_CHILD": "0"}
        ):
            loaded = runpy.run_path(
                str(Path(__file__).resolve().parents[1] / "Imespec1.py")
            )
        cls.ns = loaded["abrir_imagem_raman"].__globals__
        cls.window = cls.ns["janela"]
        cls.window.geometry("1480x900+0+0")
        cls.errors = []
        cls.window.report_callback_exception = (
            lambda kind, value, trace: cls.errors.append(str(value))
        )
        x = np.linspace(1100.0, 2100.0, 1001)
        ys = []
        for index in range(64):
            amplitude = 10000 if index == 27 else 100 + index
            ys.append(
                20
                + 0.01 * x
                + amplitude * np.exp(-0.5 * ((x - 1350) / 18) ** 2)
                + 180 * np.exp(-0.5 * ((x - 1582) / 23) ** 2)
            )
        cls.source = cls.root / "map.asc"
        np.savetxt(cls.source, np.column_stack([x] + ys))
        cls.ns["arquivo_memoria"] = str(cls.root / "last.txt")
        cls.ns["escolher_arquivo_imagem"] = lambda: str(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.window.destroy()
        cls.directory.cleanup()

    def drain(self):
        for _ in range(12):
            self.window.update_idletasks()
            self.window.update()
            time.sleep(0.01)

    def children(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.children(child)

    def setUp(self):
        self.errors.clear()
        with patch.object(self.ns["messagebox"], "askyesnocancel", return_value=True):
            self.ns["abrir_imagem_raman"]()
        self.drain()
        self.collection = next(
            w
            for w in self.children(self.window)
            if isinstance(w, self.ns["RamanMapCollection"])
        )
        self.a = self.collection.add_map("D", 180, 320, 8, 8)
        self.b = self.collection.add_map("G", 400, 560, 8, 8)
        self.ratio = self.collection.add_ratio("D/G", self.a["id"], self.b["id"])
        self.notebook = self.collection.master.master
        self.quality_tab = next(
            tab
            for tab in self.notebook.tabs()
            if "Data Quality" in self.notebook.tab(tab, "text")
        )
        self.notebook.select(self.quality_tab)
        self.drain()
        self.view = self.a["quality_view"]

    def tearDown(self):
        self.assertFalse(self.errors)

    def click(self, row, column, mouse_button):
        self.view.figure.canvas.draw()
        x, y = self.view.map_ax.transData.transform((column, row))
        event = MouseEvent(
            "button_press_event", self.view.figure.canvas, x, y, button=mouse_button
        )
        self.view.figure.canvas.callbacks.process("button_press_event", event)
        self.drain()

    def test_enter_tab_opens_active_band_and_inspection_stays_inline(self):
        self.assertEqual(self.collection.quality_selector.get(), "D")
        self.assertTrue(self.view.cosmic_apply.instate(["disabled"]))
        self.assertTrue(self.view.bad_apply.instate(["disabled"]))
        self.click(3, 3, 1)
        self.assertEqual(self.notebook.select(), self.quality_tab)
        self.assertEqual(self.view.selected, (3, 3))
        self.assertIn("X=3", self.view.pixel_var.get())
        self.assertIn("cm⁻¹", self.view.spectrum_ax.get_xlabel())
        self.collection.active_id = self.ratio["id"]
        with patch.object(self.collection, "open_ratio_dialog") as settings_dialog:
            self.collection.open_quality()
            settings_dialog.assert_called_once_with(self.ratio["id"])
        self.collection.active_id = self.a["id"]
        self.assertTrue(
            all(
                not axis.get_visible()
                for axis in self.view.figure.axes
                if axis not in (self.view.map_ax, self.view.colorbar.ax)
            )
        )

    def test_manual_repair_ratio_restore_and_independent_band_state(self):
        before = self.a["area"].copy()
        spectra = self.a["spectra"].copy()
        other = self.b["area"].copy()
        self.click(3, 3, 3)
        self.assertNotEqual(self.a["area"][3, 3], before[3, 3])
        np.testing.assert_array_equal(self.a["spectra"], spectra)
        np.testing.assert_array_equal(self.b["area"], other)
        self.assertAlmostEqual(
            self.ratio["area"][3, 3], self.a["area"][3, 3] / other[3, 3]
        )
        self.assertIn("espectro preservado", self.view.area_var.get())
        self.collection.quality_selector.current(1)
        self.collection.open_quality_from_selector()
        self.drain()
        self.collection.quality_selector.current(0)
        self.collection.open_quality_from_selector()
        self.drain()
        self.assertIs(self.a["quality_view"], self.view)
        self.view._invoke("restore")
        self.drain()
        np.testing.assert_allclose(self.a["area"], before)
        self.assertEqual(
            len(self.view.figure._imespec_export_history["bad_pixel_repairs"]), 0
        )

    def test_native_detect_clear_and_apply_delegate_to_existing_callbacks(self):
        candidates = [{"linha": 3, "coluna": 3}]
        with patch.object(
            core, "detectar_pixels_anomalos", return_value=(candidates, {})
        ):
            self.view._invoke("bad_detect")
            self.drain()
            self.assertFalse(self.view.bad_apply.instate(["disabled"]))
            self.view._invoke("clear")
            self.drain()
            self.assertTrue(self.view.bad_apply.instate(["disabled"]))
            self.view._invoke("bad_detect")
        with patch.object(core.messagebox, "askyesno", return_value=True):
            self.view._invoke("bad_apply")
        self.drain()
        self.assertEqual(
            len(self.view.figure._imespec_export_history["bad_pixel_repairs"]), 1
        )
        self.assertTrue(self.view.bad_apply.instate(["disabled"]))


if __name__ == "__main__":
    unittest.main()
