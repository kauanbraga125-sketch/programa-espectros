"""Native, reviewable peak analysis. Original series data are never edited."""

from dataclasses import replace
from pathlib import Path
import threading
import numpy as np
from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTabWidget,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QScrollArea,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from .peaks import (
    BANDS,
    Band,
    Peak,
    analyze_series,
    primary,
    profile,
    export_csv,
    export_json,
    export_comparisons_csv,
)


class FitWorker(QObject):
    progress = Signal(int, int, str, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, spectra, bands, options):
        super().__init__()
        self.spectra = spectra
        self.bands = bands
        self.options = options
        self.cancel_event = threading.Event()

    def run(self):
        try:
            self.finished.emit(
                analyze_series(
                    self.spectra,
                    self.bands,
                    progress=self.progress.emit,
                    cancelled=self.cancel_event.is_set,
                    **self.options,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))


def note(text):
    w = QLabel(text)
    w.setWordWrap(True)
    w.setStyleSheet("color: #64748B;")
    return w


class PeakAnalysisDialog(QDialog):
    def __init__(self, spectra, parent=None):
        super().__init__(parent)
        self.spectra = list(spectra)
        self.report = None
        self._thread = None
        self._worker = None
        self._close_after = False
        self.setWindowTitle("IMESPEC - Análise de picos")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1440, 960)
        self.setMinimumSize(1100, 760)
        outer = QVBoxLayout(self)
        heading = QLabel("Análise de picos")
        heading.setStyleSheet("font-size: 21pt; font-weight: 600;")
        outer.addWidget(heading)
        outer.addWidget(
            note(
                "Ajuste perfis para estimar centros, larguras e áreas. Revise o modelo, o fundo e os resíduos antes de interpretar os resultados."
            )
        )
        split = QSplitter()
        outer.addWidget(split, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(290)
        scroll.setMaximumWidth(340)
        controls = QWidget()
        scroll.setWidget(controls)
        left = QVBoxLayout(controls)
        form = QFormLayout()
        left.addLayout(form)
        form.addRow(note(f"{len(self.spectra)} arquivos na série aberta."))
        self.visible_check = QCheckBox("Somente curvas visíveis")
        form.addRow(self.visible_check)
        self.preset = QComboBox()
        self.preset.addItem("Carbina e sobretons", "all")
        for b in BANDS:
            self.preset.addItem(b.label, b.key)
        self.preset.addItem("Personalizado", "custom")
        form.addRow("Região / objetivo", self.preset)
        self.model_combo = QComboBox()
        for text, key in [
            ("Lorentziana", "lorentzian"),
            ("Gaussiana", "gaussian"),
            ("Pseudo-Voigt", "pseudo_voigt"),
        ]:
            self.model_combo.addItem(text, key)
        form.addRow("Perfil", self.model_combo)
        self.components = QSpinBox()
        self.components.setRange(1, 2)
        self.components.setValue(2)
        form.addRow("Componentes CLC", self.components)
        form.addRow(
            note(
                "No preset CLC, duas componentes permitem representar o ombro e a banda principal; isso não confirma duas populações físicas."
            )
        )
        self.start_spin = self.number(0, 10000, 1780)
        self.stop_spin = self.number(0, 10000, 1940)
        form.addRow("Início (cm⁻¹)", self.start_spin)
        form.addRow("Fim (cm⁻¹)", self.stop_spin)
        self.baseline_combo = QComboBox()
        for text, degree in [("Linear", 1), ("Constante", 0), ("Quadrático", 2)]:
            self.baseline_combo.addItem(text, degree)
        form.addRow("Fundo simultâneo", self.baseline_combo)
        self.robust_check = QCheckBox("Reduzir influência de resíduos extremos")
        self.robust_check.setChecked(True)
        self.robust_check.setToolTip(
            "Perda soft_l1. Não remove pontos nem identifica raios cósmicos automaticamente."
        )
        form.addRow(self.robust_check)
        advanced_button = QPushButton("Mais opções")
        advanced_button.setCheckable(True)
        form.addRow(advanced_button)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced.setVisible(False)
        advanced_button.toggled.connect(advanced.setVisible)
        left.addWidget(advanced)
        self.bootstrap = QSpinBox()
        self.bootstrap.setRange(0, 300)
        self.bootstrap.setSingleStep(25)
        advanced_form.addRow("Reamostragens", self.bootstrap)
        advanced_form.addRow(
            note(
                "0: estimativa local rápida. Para revisar a incerteza estatística, use 100 ou mais reamostragens. Calibração e escolha do modelo não estão incluídas."
            )
        )
        advanced_form.addRow(QLabel("Divisores de área (1 = sem correção)"))
        self.factor_spins = {}
        for b in BANDS:
            spin = self.number(0.000001, 1e12, 1)
            spin.setDecimals(6)
            self.factor_spins[b.order] = spin
            advanced_form.addRow(b.key, spin)
        advanced_form.addRow(
            note(
                "Fatores definidos pelo usuário, por exemplo exposição. A resposta instrumental não é corrigida automaticamente."
            )
        )
        self.run_button = QPushButton("Ajustar série")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_analysis)
        self.cancel_button = QPushButton("Cancelar análise")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.export_button = QPushButton("Exportar resultados…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_results)
        left.addStretch()
        split.addWidget(scroll)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.figure = Figure(figsize=(9, 5), facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        right_layout.addWidget(self.canvas, 3)
        right_layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Arquivo / região",
                "T (K)",
                "Centro (cm⁻¹)",
                "± estat. (cm⁻¹)",
                "FWHM (cm⁻¹)",
                "Área (a.u.·cm⁻¹)",
                "Altura/ruído",
                "Situação",
                "Modelo",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self.draw_selected)
        self.tabs.addTab(self.table, "Parâmetros")
        comp = QWidget()
        comp_layout = QVBoxLayout(comp)
        comp_layout.addWidget(
            note(
                "Desvio relativo: 100 × [ν₁ − (νₙ − νₙ₋₁)] / ν₁. C=ordem 1; 2C, 3C e 4C=ordens 2, 3 e 4. Razões de área são dos sinais exportados; atribuições e resposta instrumental exigem revisão."
            )
        )
        self.comparison_table = QTableWidget(0, 6)
        self.comparison_table.setHorizontalHeaderLabels(
            [
                "T (K)",
                "Ordem",
                "Ciclo",
                "Desvio (%) ± estat.",
                "Área / C ± estat.",
                "Situação",
            ]
        )
        self.comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.comparison_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        comp_layout.addWidget(self.comparison_table)
        self.tabs.addTab(comp, "Sobretons e razões")
        right_layout.addWidget(self.tabs, 2)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.progress = QProgressBar()
        self.progress.hide()
        outer.addWidget(self.progress)
        actions = QHBoxLayout()
        actions.addWidget(self.run_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.export_button)
        outer.addLayout(actions)
        self.status = note(
            "Escolha a região e clique em Ajustar série. Serão usados somente arquivos que cobrem a janela inteira."
        )
        outer.addWidget(self.status)
        self.preset.currentIndexChanged.connect(self.update_preset)
        self.update_preset()
        self.draw_empty()

    @staticmethod
    def number(low, high, value):
        s = QDoubleSpinBox()
        s.setRange(low, high)
        s.setDecimals(2)
        s.setValue(value)
        return s

    @property
    def running(self):
        return self._thread is not None

    def update_preset(self):
        key = self.preset.currentData()
        custom = key == "custom"
        self.start_spin.setEnabled(custom)
        self.stop_spin.setEnabled(custom)
        if key not in ("all", "custom"):
            b = next(b for b in BANDS if b.key == key)
            self.start_spin.setValue(b.start)
            self.stop_spin.setValue(b.stop)
        self.components.setEnabled(key in ("all", "C", "custom"))

    def selected_bands(self):
        key = self.preset.currentData()
        if key == "custom":
            lo, hi = self.start_spin.value(), self.stop_spin.value()
            if hi - lo < 5:
                raise ValueError("Defina uma janela com largura maior que 5 cm⁻¹.")
            w = (hi - lo) / 8
            c = (lo + hi) / 2
            if self.components.value() == 1:
                peaks = (
                    Peak(
                        "Pico",
                        c,
                        lo + 0.05 * (hi - lo),
                        hi - 0.05 * (hi - lo),
                        w,
                        0.1,
                        0.7 * (hi - lo),
                    ),
                )
            else:
                peaks = (
                    Peak(
                        "Pico 1",
                        lo + 0.35 * (hi - lo),
                        lo + 0.05 * (hi - lo),
                        c,
                        w,
                        0.1,
                        0.7 * (hi - lo),
                    ),
                    Peak(
                        "Pico 2",
                        lo + 0.65 * (hi - lo),
                        c,
                        hi - 0.05 * (hi - lo),
                        w,
                        0.1,
                        0.7 * (hi - lo),
                    ),
                )
            return (Band("custom", "Personalizado", 0, lo, hi, peaks, primary=-1),)
        return tuple(
            b.single() if b.key == "C" and self.components.value() == 1 else b
            for b in BANDS
            if key in ("all", b.key)
        )

    def run_analysis(self):
        if self.running:
            return
        try:
            bands = self.selected_bands()
        except ValueError as exc:
            QMessageBox.information(self, "Análise de picos", str(exc))
            return
        spectra = [
            s for s in self.spectra if s.visible or not self.visible_check.isChecked()
        ]
        if not spectra:
            QMessageBox.information(
                self, "Análise de picos", "Não há curvas para analisar."
            )
            return
        options = {
            "model": self.model_combo.currentData(),
            "baseline_degree": self.baseline_combo.currentData(),
            "robust": self.robust_check.isChecked(),
            "bootstrap": self.bootstrap.value(),
            "area_factors": {k: v.value() for k, v in self.factor_spins.items()},
        }
        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.show()
        self.progress.setValue(0)
        self._thread = QThread(self)
        self._worker = FitWorker(spectra, bands, options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.on_progress)
        self._worker.finished.connect(self.on_result)
        self._worker.failed.connect(self.on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self.on_stopped)
        self.status.setText(
            "Ajustando dados originais; a visualização permanece disponível."
        )
        self._thread.start()

    def on_progress(self, i, n, name, band):
        self.progress.setRange(0, max(n, 1))
        self.progress.setValue(i)
        self.status.setText(f"{i}/{n} · {name} · {band}")

    def cancel(self):
        if self._worker:
            self._worker.cancel_event.set()
            self.status.setText("Cancelando após a etapa atual…")

    def on_stopped(self):
        self._thread = None
        self._worker = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.hide()
        if self._close_after:
            self.close()

    def on_error(self, text):
        self.status.setText("A análise foi interrompida.")
        QMessageBox.warning(self, "Análise de picos", text)

    def on_result(self, report):
        self.report = report
        self.fill_tables()
        self.export_button.setEnabled(True)
        valid = sum(r["usable"] for r in report["fits"])
        self.status.setText(
            f"{len(report['fits'])} ajustes · {valid} sem sinalização numérica · {len(report['failures'])} falhas. Revise resíduos e atribuições; erros são estatísticos condicionais."
        )
        if report["fits"]:
            self.table.selectRow(0)

    def fill_tables(self):
        rows = self.report["fits"]
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            c = primary(r)
            state = (
                "Revisar: " + ", ".join(r["review_reasons"])
                if r["review_reasons"]
                else (
                    "Atribuição candidata"
                    if r["band"]["tentative"]
                    else "Revisar atribuição física"
                )
            )
            values = [
                f"{r['source_name']} · {r['band']['key']}",
                "-" if r["temperature_K"] is None else f"{r['temperature_K']:g}",
                f"{c['center_cm1']:.3f}",
                f"{c['center_se_cm1']:.3f}",
                f"{c['fwhm_cm1']:.2f}",
                f"{c['area_model_au_cm1']:.4g}",
                f"{c['height_to_noise']:.1f}",
                state,
                r["model"],
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setToolTip(
                    state + "\nÁrea: a.u.·cm⁻¹; integral do perfil ajustado."
                )
                self.table.setItem(i, j, item)
                if not r["usable"]:
                    item.setForeground(QColor("#A65A00"))
        comps = self.report["comparisons"]
        self.comparison_table.setRowCount(len(comps))
        for i, c in enumerate(comps):
            shift = c["relative_shift"]
            ratio = c["area_ratio"]
            values = [
                "-" if c["temperature_K"] is None else f"{c['temperature_K']:g}",
                str(c["order"]),
                "volta" if c["return_label"] else "série",
                (
                    f"{shift['relative_redshift_percent']:.3f} ± {shift['statistical_se_percent']:.3f}"
                    if shift
                    else "-"
                ),
                (
                    f"{ratio['ratio']:.4g} ± {ratio['statistical_se']:.2g}"
                    if ratio
                    else "-"
                ),
                c["reason"],
            ]
            for j, v in enumerate(values):
                self.comparison_table.setItem(i, j, QTableWidgetItem(v))

    def draw_empty(self):
        self.figure.clear()
        ax = self.figure.add_subplot()
        ax.text(
            0.5,
            0.5,
            "O ajuste e seus resíduos aparecerão aqui.",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="#64748B",
        )
        ax.set_axis_off()
        self.canvas.draw_idle()

    def draw_selected(self):
        row = self.table.currentRow()
        if not self.report or not 0 <= row < len(self.report["fits"]):
            return
        r = self.report["fits"][row]
        x = np.asarray(r["x"])
        self.figure.clear()
        gs = self.figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.1)
        ax = self.figure.add_subplot(gs[0])
        res = self.figure.add_subplot(gs[1], sharex=ax)
        ax.plot(x, r["observed"], color="#8391A4", lw=0.8, label="Dados do arquivo")
        ax.plot(x, r["model_y"], color="#2563EB", lw=1.6, label="Ajuste")
        ax.plot(x, r["background"], color="#64748B", lw=1, ls="--", label="Fundo")
        for c in r["components"]:
            y = (
                profile(
                    x,
                    c["area_model_au_cm1"],
                    c["center_cm1"],
                    c["fwhm_cm1"],
                    r["model"],
                    c["fraction_lorentzian"],
                )
                + r["background"]
            )
            ax.plot(x, y, lw=0.8, ls=":", label=c["label"])
        ax.set_ylabel("Intensidade (a.u.)")
        ax.set_title(f"{r['source_name']} · {r['band']['label']}", fontsize=10)
        ax.legend(frameon=False, fontsize=8, ncol=3)
        ax.tick_params(labelbottom=False)
        res.plot(x, r["residual"], lw=0.7, color="#52657B")
        res.axhline(0, color="#A9B8CC", lw=0.7)
        res.set_ylabel("Resíduo (a.u.)")
        res.set_xlabel("Deslocamento Raman (cm⁻¹)")
        for a in (ax, res):
            a.spines[["top", "right"]].set_visible(False)
        self.figure.subplots_adjust(left=0.095, right=0.98, top=0.9, bottom=0.13)
        self.canvas.draw_idle()

    def export_results(self, checked=False, path=None):
        if self.report is None:
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar análise de picos",
                "analise_picos.json",
                "Análise JSON (*.json)",
            )
        if not path:
            return False
        base = str(Path(path).with_suffix(""))
        try:
            export_json(base + ".json", self.report)
            export_csv(base + ".csv", self.report)
            export_comparisons_csv(base + "_sobretons.csv", self.report)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Exportar análise",
                f"Não foi possível salvar todos os arquivos: {exc}",
            )
            return False
        self.status.setText(
            "JSON, parâmetros CSV e comparações CSV exportados. Os arquivos originais foram preservados."
        )
        return True

    def closeEvent(self, event):
        if self.running:
            self._close_after = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
