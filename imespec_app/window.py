"""Qt workspace for spectrum series, inspired by Origin's plot organization.

The retained Raman Map runs in a separate process because Qt and Tk have
different event loops. Only one workspace window is visible; returning from
the map restores this window and its in-memory series unchanged.
"""

from pathlib import Path
import csv
import json
import os
import sys
import tempfile

import numpy as np
from PySide6.QtCore import (
    Qt,
    QObject,
    Signal,
    Slot,
    QThread,
    QTimer,
    QProcess,
    QProcessEnvironment,
    QSize,
)
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap, QKeySequence, QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QStackedWidget,
    QDockWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QLineEdit,
    QFileDialog,
    QColorDialog,
    QMessageBox,
    QFrame,
    QDialog,
    QTextBrowser,
    QDialogButtonBox,
    QProgressBar,
    QButtonGroup,
    QScrollArea,
    QSizePolicy,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from . import __version__
from .spectra import (
    COLORS,
    DEFAULT_SETTINGS,
    Spectrum,
    automatic_spacing,
    common_range,
    display_curves,
    load_project,
    natural_key,
    read_spectrum,
    save_project,
    sort_by_temperature,
    spectral_groups,
)

ROOT = Path(__file__).resolve().parents[1]
BLUE, INK, MUTED = "#2563EB", "#172B4D", "#64748B"
STYLE = """
QMainWindow, QWidget#workspace { background: #F4F7FB; color: #172B4D; }
QWidget { font-family: 'Segoe UI', 'DejaVu Sans'; font-size: 10pt; color: #172B4D; }
QMenuBar, QMenu, QStatusBar { background: white; }
QMenu::item { padding: 7px 24px; } QMenu::item:selected { background: #EAF1FF; }
QFrame#sidebar { background: #12213B; border: 0; }
QFrame#sidebar QLabel { color: #CFDAEB; background: transparent; }
QFrame#sidebar QPushButton { color: #DDE7F6; background: transparent; border: 0;
    border-radius: 7px; text-align: left; padding: 11px 13px; }
QFrame#sidebar QPushButton:hover { background: #213858; }
QFrame#sidebar QPushButton:checked { background: #2563EB; color: white; font-weight: 600; }
QPushButton, QToolButton { background: white; border: 1px solid #D9E2EE; border-radius: 6px;
    padding: 7px 11px; min-height: 18px; }
QPushButton:hover, QToolButton:hover { background: #EFF5FF; border-color: #A6BFF4; }
QPushButton:disabled { color: #94A3B8; background: #F8FAFC; }
QPushButton#primary { background: #2563EB; color: white; border: 1px solid #2563EB; font-weight: 600; }
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#mode:checked { background: #E8F0FF; color: #1D4ED8; border-color: #87ACFA; font-weight: 600; }
QLineEdit, QDoubleSpinBox, QComboBox { background: white; border: 1px solid #D7E0ED;
    border-radius: 5px; padding: 6px; min-height: 18px; selection-background-color: #DBEAFE; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #2563EB; }
QComboBox::drop-down { border: none; width: 22px; }
QDockWidget { background: white; titlebar-close-icon: none; }
QDockWidget::title { background: #F8FAFC; padding: 9px 12px; font-weight: 600; border-bottom: 1px solid #E2E8F0; }
QListWidget { background: white; border: 0; outline: 0; }
QListWidget::item { padding: 8px 6px; border-radius: 5px; }
QListWidget::item:selected { background: #EAF1FF; color: #172B4D; }
QListWidget::item:hover { background: #F3F7FE; }
QCheckBox { spacing: 7px; padding: 3px 0; }
QCheckBox::indicator { width: 15px; height: 15px; }
QLabel#muted { color: #64748B; } QLabel#eyebrow { color: #2563EB; font-weight: 600; font-size: 9pt; }
QLabel#title { font-size: 21pt; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #DFE7F2; border-radius: 12px; }
QToolBar { background: white; border: none; spacing: 4px; }
QScrollArea { border: 0; background: white; }
QWidget#propertiesPanel { background: white; }
QProgressBar { border: 0; background: #E9EFF8; max-height: 4px; }
QProgressBar::chunk { background: #2563EB; }
"""


def label(text, muted=False, wrap=True):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if muted:
        widget.setObjectName("muted")
    return widget


def button(text, slot, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(slot)
    return widget


def separator():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #E2E8F0; margin: 6px 0;")
    return line


class ImportWorker(QObject):
    finished = Signal(object, object)
    progress = Signal(int, int)

    def __init__(self, paths, start_color=0):
        super().__init__()
        self.paths, self.start_color = paths, start_color

    @Slot()
    def run(self):
        spectra, errors = [], []
        for index, path in enumerate(self.paths):
            try:
                spectra.append(
                    read_spectrum(
                        path, COLORS[(index + self.start_color) % len(COLORS)]
                    )
                )
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
            self.progress.emit(index + 1, len(self.paths))
        self.finished.emit(spectra, errors)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.spectra = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.groups = []
        self.project_path = None
        self.dirty = False
        self._building = False
        self._busy = False
        self._thread = None
        self._worker = None
        self._legacy = None
        self._legacy_ready = False
        self._group_index = 0
        self._compact = False
        self._current_page = "home"
        self._last_curves = []
        self.ax = None
        self.setWindowTitle(f"IMESPEC {__version__}")
        self.setWindowIcon(QIcon(str(ROOT / "assets" / "imespec.svg")))
        self.resize(1500, 940)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self.render)
        self._make_menu()
        self._make_center()
        self._make_spectra_dock()
        self._make_settings_dock()
        self.statusBar().showMessage(
            "Pronto. Abra uma série de espectros ou uma aquisição Raman Map."
        )
        self.show_page("home")

    def _make_menu(self):
        file_menu = self.menuBar().addMenu("Arquivo")
        entries = [
            ("Abrir espectros…", self.open_spectra, "Ctrl+O"),
            ("Abrir projeto…", self.open_project, "Ctrl+Shift+O"),
            ("Salvar projeto…", self.save_session, "Ctrl+S"),
            ("Exportar figura…", self.export_figure, "Ctrl+E"),
            ("Exportar dados…", self.export_data, ""),
            ("Abrir Raman Map…", self.launch_map, "Ctrl+1"),
        ]
        for text, slot, shortcut in entries:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction("Sair", self.close)
        view = self.menuBar().addMenu("Exibir")
        view.addAction(
            "Cascata", lambda: self.show_page("multi"), QKeySequence("Ctrl+2")
        )
        view.addAction("Início", lambda: self.show_page("home"), QKeySequence("Ctrl+H"))
        analysis_menu = self.menuBar().addMenu("Análise")
        analysis_menu.addAction(
            "Ajustar picos e sobretons…",
            self.open_peak_analysis,
            QKeySequence("Ctrl+3"),
        )
        help_menu = self.menuBar().addMenu("Ajuda")
        help_menu.addAction("Como usar", self.show_help, QKeySequence("F1"))
        help_menu.addAction(
            "Sobre o IMESPEC",
            lambda: QMessageBox.about(
                self,
                "IMESPEC",
                f"IMESPEC {__version__}\nProjeto de iniciação científica de Kauan.\n"
                "Séries Raman, cascata e mapas de áreas.\nReferências de organização: Origin e WITec.",
            ),
        )

    def _make_center(self):
        outer = QWidget()
        outer.setObjectName("workspace")
        layout = QHBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(155)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 25, 12, 16)
        logo = label("IMESPEC")
        logo.setStyleSheet("font-size: 18pt; font-weight: 700; color: white;")
        nav.addWidget(logo)
        nav.addWidget(label("Raman workspace"))
        nav.addSpacing(30)
        self.home_button = button("Início", lambda: self.show_page("home"))
        self.multi_button = button("Espectros", lambda: self.show_page("multi"))
        self.home_button.setCheckable(True)
        self.multi_button.setCheckable(True)
        nav.addWidget(self.home_button)
        nav.addWidget(self.multi_button)
        nav.addWidget(button("Raman Map ↗", self.launch_map))
        nav.addStretch()
        nav.addWidget(button("Como usar", self.show_help))
        nav.addWidget(label(f"v{__version__}"))
        layout.addWidget(sidebar)
        self.workbench = QMainWindow()
        self.workbench.setObjectName("workbench")
        self.pages = QStackedWidget()
        self.workbench.setCentralWidget(self.pages)
        layout.addWidget(self.workbench, 1)
        self.setCentralWidget(outer)

        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(36, 35, 36, 35)
        eyebrow = label("ANÁLISE RAMAN")
        eyebrow.setObjectName("eyebrow")
        home_layout.addWidget(eyebrow)
        title = label("Dos espectros à comparação.")
        title.setObjectName("title")
        home_layout.addWidget(title)
        home_layout.addWidget(
            label(
                "Abra seus dados, organize a série e prepare as figuras do seu trabalho.",
                True,
            )
        )
        home_layout.addSpacing(25)
        cards = QHBoxLayout()
        for heading, description, action_text, slot in [
            (
                "Espectros em cascata",
                "Compare uma série por temperatura. Organize as curvas, ajuste o espaçamento e exporte a figura.",
                "Abrir espectros",
                self.open_spectra,
            ),
            (
                "Raman Map",
                "Gere mapas de bandas, consulte o espectro de cada ponto e compare áreas com a razão A/B.",
                "Abrir Raman Map",
                self.launch_map,
            ),
        ]:
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(25, 28, 25, 25)
            h = label(heading)
            h.setStyleSheet("font-size: 16pt; font-weight: 600;")
            box.addWidget(h)
            box.addSpacing(10)
            box.addWidget(label(description, True))
            box.addStretch()
            box.addSpacing(25)
            box.addWidget(
                button(action_text, slot, True), alignment=Qt.AlignmentFlag.AlignLeft
            )
            cards.addWidget(card, 1)
        home_layout.addLayout(cards, 1)
        home_layout.addSpacing(20)
        home_layout.addWidget(
            label(
                "Já salvou uma análise? Reabra o projeto para continuar com as mesmas curvas e configurações.",
                True,
            )
        )
        home_layout.addWidget(
            button("Abrir projeto salvo…", self.open_project),
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        home_layout.addStretch(1)
        self.pages.addWidget(home)

        multi = QWidget()
        body = QVBoxLayout(multi)
        body.setContentsMargins(18, 18, 18, 12)
        header = QHBoxLayout()
        heading = label("Espectros")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(button("Abrir…", self.open_spectra, True))
        self.add_button = button("+ Adicionar", lambda: self.open_spectra(append=True))
        header.addWidget(self.add_button)
        self.save_button = button("Salvar projeto", self.save_session)
        header.addWidget(self.save_button)
        self.export_button = button("Exportar figura", self.export_figure)
        header.addWidget(self.export_button)
        self.options_button = button("Opções", self.toggle_settings)
        self.options_button.setCheckable(True)
        self.options_button.setChecked(True)
        header.addWidget(self.options_button)
        body.addLayout(header)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        body.addWidget(self.progress_bar)
        self.subtitle = label(
            "Abra arquivos TXT ou CSV com Raman shift e intensidade.", True
        )
        body.addWidget(self.subtitle)
        view_bar = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, text in (
            ("overlay", "Sobrepor"),
            ("cascade", "Cascata 2D"),
            ("waterfall", "Waterfall 3D"),
        ):
            b = button(text, lambda checked=False, mode=key: self.set_mode(mode))
            b.setObjectName("mode")
            b.setMinimumWidth(120)
            b.setCheckable(True)
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            view_bar.addWidget(b)
        view_bar.addStretch()
        self.peak_button = button("Analisar picos…", self.open_peak_analysis)
        view_bar.addWidget(self.peak_button)
        self.fit_button = button("Enquadrar", lambda: self.render(reset_view=True))
        view_bar.addWidget(self.fit_button)
        body.addLayout(view_bar)
        self.plot_pages = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        hint = label("Sua série começa aqui")
        hint.setStyleSheet("font-size: 20pt; font-weight: 600;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint)
        hint2 = label(
            "Abra ou arraste os arquivos para esta janela.\nA cascata será organizada automaticamente.",
            True,
        )
        hint2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint2)
        empty_layout.addSpacing(16)
        empty_layout.addWidget(
            button("Abrir espectros", self.open_spectra, True),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        empty_layout.addStretch()
        self.plot_pages.addWidget(empty)
        plot_host = QWidget()
        plot_host.setStyleSheet("background: white; border-radius: 8px;")
        plot_layout = QVBoxLayout(plot_host)
        plot_layout.setContentsMargins(4, 4, 4, 0)
        self.figure = Figure(figsize=(9, 6), dpi=100, facecolor="white")
        self.canvas = FigureCanvasQTAgg(self.figure)
        plot_layout.addWidget(self.canvas, 1)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setStyleSheet("border-top: 1px solid #E2E8F0; padding: 2px;")
        plot_layout.addWidget(self.toolbar)
        self.plot_pages.addWidget(plot_host)
        body.addWidget(self.plot_pages, 1)
        self.caption = label("Os arquivos originais são preservados.", True)
        self.caption.setStyleSheet("font-size: 9pt; color: #64748B;")
        body.addWidget(self.caption)
        self.pages.addWidget(multi)

    def _dock(self, title, name, side):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setAllowedAreas(side)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setMinimumWidth(230)
        dock.setMaximumWidth(420)
        self.workbench.addDockWidget(side, dock)
        return dock

    def _make_spectra_dock(self):
        self.spectra_dock = self._dock(
            "Série de espectros", "spectraDock", Qt.DockWidgetArea.LeftDockWidgetArea
        )
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(9)
        box.addWidget(label("REGIÃO ESPECTRAL", True))
        self.region_combo = QComboBox()
        self.region_combo.setToolTip(
            "Janelas espectrais separadas são organizadas automaticamente em grupos."
        )
        self.region_combo.currentIndexChanged.connect(self.change_region)
        box.addWidget(self.region_combo)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.itemChanged.connect(self._visibility_changed)
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.list_widget.model().rowsMoved.connect(self._order_changed)
        box.addWidget(self.list_widget, 1)
        line = QHBoxLayout()
        line.addWidget(button("↑", lambda: self.move_selected(-1)))
        line.addWidget(button("↓", lambda: self.move_selected(1)))
        line.addWidget(button("Inverter", self.reverse_order))
        box.addLayout(line)
        box.addWidget(button("Ordenar por temperatura", self.sort_temperature))
        line2 = QHBoxLayout()
        line2.addWidget(button("Mostrar todos", lambda: self.set_all_visible(True)))
        line2.addWidget(button("Ocultar", lambda: self.set_all_visible(False)))
        box.addLayout(line2)
        box.addWidget(
            label(
                "Marque para exibir. Arraste para mudar a ordem. Selecione uma curva para editar seu rótulo.",
                True,
            )
        )
        self.spectra_dock.setWidget(host)
        self.workbench.resizeDocks(
            [self.spectra_dock], [255], Qt.Orientation.Horizontal
        )

    def _make_settings_dock(self):
        self.settings_dock = self._dock(
            "Visualização", "settingsDock", Qt.DockWidgetArea.RightDockWidgetArea
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("propertiesPanel")
        box = QVBoxLayout(host)
        box.setContentsMargins(16, 15, 16, 16)
        box.setSpacing(10)
        box.addWidget(label("ESPAÇAMENTO", True))
        self.auto_check = QCheckBox("Ajustar automaticamente")
        self.auto_check.setChecked(True)
        self.auto_check.toggled.connect(self._settings_changed)
        box.addWidget(self.auto_check)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0, 1e15)
        self.spacing_spin.setDecimals(3)
        self.spacing_spin.setSuffix(" a.u.")
        self.spacing_spin.setToolTip(
            "Deslocamento vertical entre curvas; altera somente a exibição."
        )
        self.spacing_spin.valueChanged.connect(self._settings_changed)
        box.addWidget(self.spacing_spin)
        self.spacing_help = label(
            "A cascata separa as curvas para facilitar a comparação dos picos.", True
        )
        box.addWidget(self.spacing_help)
        self.labels_check = QCheckBox("Identificar curvas no gráfico")
        self.labels_check.setChecked(True)
        self.labels_check.toggled.connect(self._settings_changed)
        box.addWidget(self.labels_check)
        self.temp_axis_check = QCheckBox("Usar temperatura no eixo 3D")
        self.temp_axis_check.setChecked(True)
        self.temp_axis_check.toggled.connect(self._settings_changed)
        box.addWidget(self.temp_axis_check)
        box.addWidget(separator())
        box.addWidget(label("CURVA SELECIONADA", True))
        self.selected_name = label("Selecione um espectro na lista.", True)
        self.selected_name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.selected_name.setMinimumWidth(0)
        self.selected_name.setStyleSheet("font-size: 9pt; color: #64748B;")
        box.addWidget(self.selected_name)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Rótulo automático")
        self.name_edit.editingFinished.connect(self._edit_label)
        self.temp_edit = QLineEdit()
        self.temp_edit.setPlaceholderText("Não informada")
        self.temp_edit.editingFinished.connect(self._edit_temperature)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow("Rótulo", self.name_edit)
        form.addRow("Temperatura (K)", self.temp_edit)
        box.addLayout(form)
        self.color_button = button("Cor da curva", self.choose_color)
        box.addWidget(self.color_button)
        box.addWidget(
            label(
                "Temperaturas são sugeridas quando o nome contém um valor em K. Confira e edite se necessário.",
                True,
            )
        )
        box.addWidget(separator())
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Mais opções")
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setCheckable(True)
        box.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 2, 0, 2)
        self.align_check = QCheckBox("Alinhar alturas em um ponto")
        self.align_check.setToolTip(
            "Iguala as intensidades no ponto escolhido antes de empilhar. Não desloca os picos no eixo Raman."
        )
        self.align_check.toggled.connect(self._settings_changed)
        advanced_layout.addWidget(self.align_check)
        self.xref_spin = QDoubleSpinBox()
        self.xref_spin.setRange(-1e8, 1e8)
        self.xref_spin.setDecimals(2)
        self.xref_spin.setSuffix(" cm⁻¹")
        self.xref_spin.valueChanged.connect(self._settings_changed)
        advanced_layout.addWidget(label("Ponto de referência", True))
        advanced_layout.addWidget(self.xref_spin)
        advanced_layout.addWidget(
            label(
                "Use uma região sem pico. Este ajuste soma uma constante a cada curva, somente na visualização.",
                True,
            )
        )
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.3, 4)
        self.width_spin.setSingleStep(0.1)
        self.width_spin.setValue(1.2)
        self.width_spin.valueChanged.connect(self._settings_changed)
        advanced_layout.addWidget(label("Espessura das linhas", True))
        advanced_layout.addWidget(self.width_spin)
        box.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        box.addStretch()
        box.addWidget(button("Restaurar visualização", self.reset_settings))
        scroll.setWidget(host)
        self.settings_dock.setWidget(scroll)
        self.workbench.resizeDocks(
            [self.settings_dock], [265], Qt.Orientation.Horizontal
        )

    def toggle_settings(self, checked=False):
        self.settings_dock.setVisible(checked and self._current_page == "multi")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "settings_dock") and self._current_page == "multi":
            compact = self.width() < 1300
            if compact != self._compact:
                self._compact = compact
                self.options_button.setChecked(not compact)
                self.settings_dock.setVisible(not compact)

    def _toggle_advanced(self, checked):
        self.advanced.setVisible(checked)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def show_page(self, page):
        self._current_page = page
        is_multi = page == "multi"
        self.pages.setCurrentIndex(1 if is_multi else 0)
        self.home_button.setChecked(not is_multi)
        self.multi_button.setChecked(is_multi)
        self.spectra_dock.setVisible(is_multi)
        self._compact = self.width() < 1300
        self.settings_dock.setVisible(is_multi and not self._compact)
        self.options_button.setChecked(not self._compact)
        self._update_enabled()

    def _update_enabled(self):
        has_data = bool(self.spectra)
        visible = bool(self.visible_spectra())
        for widget in (self.save_button,):
            widget.setEnabled(has_data and not self._busy)
        self.export_button.setEnabled(visible and not self._busy)
        self.add_button.setEnabled(has_data and not self._busy)
        self.fit_button.setEnabled(visible)
        self.list_widget.setEnabled(not self._busy)
        mode = self.settings["mode"]
        cascade = mode == "cascade"
        self.auto_check.setEnabled(cascade)
        self.spacing_spin.setEnabled(cascade and not self.auto_check.isChecked())
        self.temp_axis_check.setVisible(mode == "waterfall")
        self.align_check.setEnabled(mode != "overlay")
        self.xref_spin.setEnabled(mode != "overlay" and self.align_check.isChecked())
        self.mode_buttons[mode].setChecked(True)
        selected = self.selected_spectrum()
        for widget in (self.name_edit, self.temp_edit, self.color_button):
            widget.setEnabled(selected is not None)

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        name = Path(self.project_path).name if self.project_path else "Série sem título"
        suffix = f" — {name}{' *' if self.dirty else ''}" if self.spectra else ""
        self.setWindowTitle(f"IMESPEC {__version__}{suffix}")

    def _confirm_replace(self):
        if not self.dirty:
            return True
        result = QMessageBox.question(
            self,
            "Salvar seu projeto?",
            "A série atual tem alterações. Quer salvar antes de continuar?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return self.save_session()
        return result == QMessageBox.StandardButton.Discard

    def open_peak_analysis(self, checked=False):
        if not self.spectra:
            QMessageBox.information(
                self, "Análise de picos", "Abra os espectros que deseja analisar."
            )
            return
        current = getattr(self, "_peak_analysis", None)
        if current is not None:
            current.show()
            current.raise_()
            current.activateWindow()
            return
        from .peak_window import PeakAnalysisDialog

        dialog = PeakAnalysisDialog(self.spectra, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._peak_analysis = dialog
        dialog.destroyed.connect(lambda: setattr(self, "_peak_analysis", None))
        dialog.show()

    def open_spectra(self, checked=False, append=False):
        if self._busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Abrir espectros Raman",
            "",
            "Espectros de texto (*.txt *.csv *.tsv *.asc *.dat);;Todos os arquivos (*)",
        )
        if paths:
            self.import_paths(paths, append)

    def import_paths(self, paths, append=False):
        if self._busy or (not append and not self._confirm_replace()):
            return
        existing = (
            {str(Path(s.source).resolve()) for s in self.spectra if s.source}
            if append
            else set()
        )
        unique = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        paths = [p for p in unique if p not in existing]
        if not paths:
            self.statusBar().showMessage("Esses arquivos já estão na série.")
            return
        self._busy = True
        self.show_page("multi")
        self.progress_bar.setRange(0, len(paths))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.statusBar().showMessage("Lendo os espectros…")
        self._thread = QThread(self)
        self._import_append = append
        self._worker = ImportWorker(
            sorted(paths, key=natural_key), len(self.spectra) if append else 0
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._import_progress)
        self._worker.finished.connect(self._finish_import)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._import_thread_finished)
        self._thread.start()
        self._update_enabled()

    def _import_thread_finished(self):
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread, self._worker = None, None

    @Slot(int, int)
    def _import_progress(self, done, total):
        self.progress_bar.setValue(done)

    @Slot(object, object)
    def _finish_import(self, spectra, errors):
        self._busy = False
        self.progress_bar.hide()
        if spectra:
            if self._import_append:
                self.spectra.extend(sort_by_temperature(spectra))
            else:
                self.spectra = sort_by_temperature(spectra)
                self.project_path = None
                self.settings = dict(DEFAULT_SETTINGS)
                self._sync_controls()
            new_groups = spectral_groups(self.spectra)
            self._group_index = max(
                range(len(new_groups)), key=lambda i: len(new_groups[i][2])
            )
            self._rebuild_groups()
            self._mark_dirty()
            self.render(reset_view=True)
            self.statusBar().showMessage(
                f"{len(spectra)} espectros abertos. Você já pode ajustar ou exportar a figura."
            )
        self._update_enabled()
        if errors:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Alguns arquivos não foram abertos")
            dialog.setText(
                f"{len(spectra)} arquivo(s) aberto(s); {len(errors)} arquivo(s) com problema."
            )
            dialog.setInformativeText(
                "Abra os detalhes para consultar os arquivos. Os dados válidos continuam disponíveis."
            )
            dialog.setDetailedText("\n\n".join(errors))
            dialog.exec()

    def _rebuild_groups(self):
        self.groups = spectral_groups(self.spectra)
        self._building = True
        self.region_combo.clear()
        for lo, hi, uids in self.groups:
            self.region_combo.addItem(f"{lo:.0f}–{hi:.0f} cm⁻¹ · {len(uids)} curvas")
        self._group_index = min(self._group_index, max(0, len(self.groups) - 1))
        self.region_combo.setCurrentIndex(self._group_index)
        self._building = False
        self._rebuild_list()

    def active_spectra(self):
        if not self.groups:
            return []
        uids = set(self.groups[self._group_index][2])
        return [s for s in self.spectra if s.uid in uids]

    def visible_spectra(self):
        return [s for s in self.active_spectra() if s.visible]

    def selected_spectrum(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        uid = item.data(Qt.ItemDataRole.UserRole)
        return next((s for s in self.spectra if s.uid == uid), None)

    def _rebuild_list(self, select_uid=None):
        if select_uid is None and self.list_widget.currentItem():
            select_uid = self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole)
        self._building = True
        self.list_widget.clear()
        selected_index = 0
        for index, s in enumerate(self.active_spectra()):
            item = QListWidgetItem(s.title)
            item.setData(Qt.ItemDataRole.UserRole, s.uid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if s.visible else Qt.CheckState.Unchecked
            )
            item.setToolTip(
                f"{s.name}\n{s.bounds[0]:.2f}–{s.bounds[1]:.2f} cm⁻¹\n{s.x.size} pontos"
            )
            pixmap = QPixmap(14, 14)
            pixmap.fill(QColor(s.color))
            item.setIcon(QIcon(pixmap))
            self.list_widget.addItem(item)
            if s.uid == select_uid:
                selected_index = index
        if self.list_widget.count():
            self.list_widget.setCurrentRow(selected_index)
        self._building = False
        self._selection_changed()

    def change_region(self, index):
        if self._building or index < 0:
            return
        self._group_index = index
        self.settings["xref"] = None
        self._rebuild_list()
        self.render(reset_view=True)

    def _selection_changed(self, *args):
        if self._building:
            return
        s = self.selected_spectrum()
        self._building = True
        filename = s.name if s else "Selecione um espectro na lista."
        self.selected_name.setText(
            filename if len(filename) <= 32 else filename[:14] + "…" + filename[-16:]
        )
        self.selected_name.setToolTip(s.name if s else "")
        self.name_edit.setText(s.label if s else "")
        self.temp_edit.setText(
            f"{s.temperature:g}" if s and s.temperature is not None else ""
        )
        self.color_button.setStyleSheet(
            f"border-left: 6px solid {s.color};" if s else ""
        )
        self._building = False
        self._update_enabled()
        self._timer.start()

    def _visibility_changed(self, item):
        if self._building:
            return
        uid = item.data(Qt.ItemDataRole.UserRole)
        s = next(s for s in self.spectra if s.uid == uid)
        s.visible = item.checkState() == Qt.CheckState.Checked
        self._mark_dirty()
        self._timer.start()

    def _order_changed(self, *args):
        if self._building:
            return
        ids = [
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
        ]
        self._replace_active_order(ids)

    def _replace_active_order(self, ids):
        active = {s.uid: s for s in self.active_spectra()}
        ordered = iter(active[uid] for uid in ids)
        self.spectra = [next(ordered) if s.uid in active else s for s in self.spectra]
        self._mark_dirty()
        self._timer.start()

    def move_selected(self, direction):
        row = self.list_widget.currentRow()
        new = row + direction
        if row < 0 or not 0 <= new < self.list_widget.count():
            return
        uid = self.selected_spectrum().uid
        ids = [s.uid for s in self.active_spectra()]
        ids[row], ids[new] = ids[new], ids[row]
        self._replace_active_order(ids)
        self._rebuild_list(uid)

    def reverse_order(self):
        self._replace_active_order([s.uid for s in reversed(self.active_spectra())])
        self._rebuild_list()

    def sort_temperature(self):
        self._replace_active_order(
            [s.uid for s in sort_by_temperature(self.active_spectra())]
        )
        self._rebuild_list()

    def set_all_visible(self, visible):
        for s in self.active_spectra():
            s.visible = visible
        self._rebuild_list()
        self._mark_dirty()
        self._timer.start()

    def _edit_label(self):
        if self._building or self.selected_spectrum() is None:
            return
        s = self.selected_spectrum()
        text = self.name_edit.text().strip()
        if text != s.label:
            s.label = text
            self._rebuild_list(s.uid)
            self._mark_dirty()
            self._timer.start()

    def _edit_temperature(self):
        if self._building or self.selected_spectrum() is None:
            return
        s = self.selected_spectrum()
        text = self.temp_edit.text().strip().replace(",", ".")
        try:
            value = float(text) if text else None
            if value is not None and (not np.isfinite(value) or value < 0):
                raise ValueError()
        except ValueError:
            QMessageBox.warning(
                self,
                "Temperatura",
                "Informe uma temperatura em kelvin maior ou igual a zero, ou deixe em branco.",
            )
            self._selection_changed()
            return
        if value != s.temperature:
            s.temperature = value
            self._rebuild_list(s.uid)
            self._mark_dirty()
            self._timer.start()

    def choose_color(self):
        s = self.selected_spectrum()
        if s is None:
            return
        color = QColorDialog.getColor(QColor(s.color), self, "Cor da curva")
        if color.isValid():
            s.color = color.name()
            self._rebuild_list(s.uid)
            self._mark_dirty()
            self._timer.start()

    def _sync_controls(self):
        self._building = True
        self.auto_check.setChecked(self.settings["automatic"])
        self.spacing_spin.setValue(self.settings["spacing"])
        self.labels_check.setChecked(self.settings["labels"])
        self.align_check.setChecked(self.settings["align"])
        self.xref_spin.setValue(self.settings["xref"] or 0)
        self.width_spin.setValue(self.settings["linewidth"])
        self.temp_axis_check.setChecked(self.settings["temperature_axis"])
        self._building = False
        self._update_enabled()

    def set_mode(self, mode):
        if mode == self.settings["mode"]:
            return
        self.settings["mode"] = mode
        if self.spectra:
            self._mark_dirty()
        self._update_enabled()
        self.render(reset_view=True)

    def _settings_changed(self, *args):
        if self._building:
            return
        self.settings.update(
            automatic=self.auto_check.isChecked(),
            spacing=self.spacing_spin.value(),
            labels=self.labels_check.isChecked(),
            align=self.align_check.isChecked(),
            xref=self.xref_spin.value(),
            linewidth=self.width_spin.value(),
            temperature_axis=self.temp_axis_check.isChecked(),
        )
        if self.spectra:
            self._mark_dirty()
        self._update_enabled()
        self._timer.start()

    def reset_settings(self):
        self.settings = dict(DEFAULT_SETTINGS)
        self._sync_controls()
        if self.spectra:
            self._mark_dirty()
        self.render(reset_view=True)

    def render(self, reset_view=False):
        self._timer.stop()
        spectra = self.visible_spectra()
        self._update_enabled()
        if not spectra:
            self._last_curves = []
            self.figure.clear()
            self.ax = None
            self.plot_pages.setCurrentIndex(0)
            if self.spectra:
                self.caption.setText(
                    "Nenhuma curva visível. Marque os espectros na lista ou clique em Mostrar todos."
                )
            return
        self.plot_pages.setCurrentIndex(1)
        mode = self.settings["mode"]
        bounds = common_range(spectra)
        if self.settings["xref"] is None and bounds:
            self.settings["xref"] = bounds[0] + 0.9 * (bounds[1] - bounds[0])
            self._building = True
            self.xref_spin.setValue(self.settings["xref"])
            self._building = False
        align = self.settings["align"] and mode != "overlay"
        try:
            spacing = (
                automatic_spacing(spectra, align, self.settings["xref"])
                if self.settings["automatic"]
                else self.settings["spacing"]
            )
            curves = display_curves(
                spectra, mode, spacing, align, self.settings["xref"]
            )
        except ValueError as exc:
            self.caption.setText(str(exc))
            self.statusBar().showMessage(str(exc))
            self._last_curves = []
            self.figure.clear()
            self.ax = None
            self.canvas.draw_idle()
            self.export_button.setEnabled(False)
            return
        if self.settings["automatic"]:
            self._building = True
            self.spacing_spin.setValue(spacing)
            self.settings["spacing"] = spacing
            self._building = False
        old_view = None
        if self.ax is not None and hasattr(self.ax, "elev") and not reset_view:
            old_view = self.ax.elev, self.ax.azim
        self.figure.clear()
        is_3d = mode == "waterfall"
        self.ax = self.figure.add_subplot(111, projection="3d" if is_3d else None)
        ax = self.ax
        selected = self.selected_spectrum()
        temps = [s.temperature for s in spectra]
        temperature_axis = (
            is_3d
            and self.settings["temperature_axis"]
            and all(t is not None for t in temps)
            and len(set(temps)) == len(temps)
        )
        for index, (s, displayed, shift) in enumerate(curves):
            width = self.settings["linewidth"] + (
                0.4 if selected and selected.uid == s.uid else 0
            )
            if is_3d:
                position = s.temperature if temperature_axis else index + 1
                ax.plot(
                    s.x,
                    np.full(s.x.size, position),
                    displayed,
                    color=s.color,
                    linewidth=width,
                )
            else:
                ax.plot(s.x, displayed, color=s.color, linewidth=width, label=s.title)
                if self.settings["labels"] and mode == "cascade":
                    end = int(np.argmax(s.x))
                    text = s.title if len(s.title) < 29 else s.title[:26] + "…"
                    ax.annotate(
                        text,
                        (s.x[end], displayed[end]),
                        xytext=(6, 0),
                        textcoords="offset points",
                        va="center",
                        color=s.color,
                        fontsize=8,
                        annotation_clip=False,
                    )
        ax.set_xlabel("Raman shift (cm⁻¹)", labelpad=10, fontsize=10)
        if is_3d:
            ax.set_ylabel(
                "Temperatura (K)" if temperature_axis else "Ordem da série",
                labelpad=10,
                fontsize=10,
            )
            ax.set_zlabel(
                "Intensidade (a.u.)" + (" + alinhamento visual" if align else ""),
                labelpad=10,
                fontsize=10,
            )
            ax.view_init(*(old_view or (23, -65)))
            if not temperature_axis and len(spectra) <= 20:
                ax.set_yticks(np.arange(1, len(spectra) + 1))
                if self.settings["labels"]:
                    ax.set_yticklabels([s.title[:18] for s in spectra], fontsize=7)
            self.figure.subplots_adjust(left=0.03, right=0.92, bottom=0.07, top=0.98)
        else:
            ax.set_ylabel(
                "Intensidade (a.u.)"
                + (" + deslocamento visual" if mode == "cascade" else ""),
                fontsize=10,
            )
            ax.spines[["top", "right"]].set_visible(False)
            for side in ("bottom", "left"):
                ax.spines[side].set_color("#A9B8CC")
            ax.tick_params(colors="#64748B", labelsize=8)
            ax.margins(x=0.025, y=0.045)
            if mode == "overlay" and self.settings["labels"] and len(spectra) <= 18:
                ax.legend(
                    loc="upper right",
                    fontsize=8,
                    frameon=False,
                    ncols=2 if len(spectra) > 8 else 1,
                )
            if align:
                ax.axvline(
                    self.settings["xref"],
                    color="#94A3B8",
                    linestyle="--",
                    linewidth=0.8,
                    alpha=0.7,
                )
            self.figure.subplots_adjust(
                left=0.12,
                right=0.83 if self.settings["labels"] and mode == "cascade" else 0.96,
                bottom=0.13,
                top=0.96,
            )
        self._last_curves = curves
        self.toolbar.update()
        self.canvas.draw_idle()
        count = len(spectra)
        group_count = len(self.groups)
        self.subtitle.setText(
            f"{count} de {len(self.active_spectra())} curvas visíveis · {group_count} região(ões) espectral(is) · {len(self.spectra)} arquivos na série"
        )
        notes = []
        if mode == "cascade":
            notes.append(f"Espaçamento: {spacing:.4g} a.u.")
        if align:
            notes.append(f"Alinhamento visual em {self.settings['xref']:.2f} cm⁻¹")
        if is_3d:
            notes.append("Arraste o gráfico para girar")
            if not temperature_axis:
                notes.append("Profundidade = ordem da série")
        unequal = len({tuple(round(v, 5) for v in s.bounds) for s in spectra}) > 1
        if unequal:
            notes.append("Faixas medidas diferentes; confira a cobertura de cada curva")
        notes.append("Dados originais preservados")
        self.caption.setText(" · ".join(notes))

    def save_session(self, checked=False, path=None):
        if not self.spectra:
            self.statusBar().showMessage("Abra espectros antes de salvar um projeto.")
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar projeto IMESPEC",
                self.project_path or "Minha_serie.imespec",
                "Projeto IMESPEC (*.imespec)",
            )
        if not path:
            return False
        if not str(path).lower().endswith(".imespec"):
            path = str(path) + ".imespec"
        try:
            save_project(path, self.spectra, self.settings)
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível salvar", str(exc))
            return False
        self.project_path = str(path)
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(
            "Projeto salvo com os espectros originais, rótulos, ordem e configurações."
        )
        return True

    def open_project(self, checked=False, path=None):
        if self._busy:
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Abrir projeto IMESPEC", "", "Projeto IMESPEC (*.imespec)"
            )
        if not path or not self._confirm_replace():
            return
        try:
            spectra, settings = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível abrir o projeto", str(exc))
            return
        self.spectra, self.settings = spectra, settings
        self.project_path = str(path)
        self._group_index = 0
        self._rebuild_groups()
        self._sync_controls()
        self.show_page("multi")
        self.render(reset_view=True)
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage("Projeto aberto. Você pode continuar a análise.")

    def export_figure(self, checked=False, path=None):
        self.render()
        if not self._last_curves:
            self.statusBar().showMessage(
                "Exiba ao menos um espectro válido antes de exportar."
            )
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar figura",
                "IMESPEC_cascata.png",
                "Imagem PNG (*.png);;Figura vetorial PDF (*.pdf);;Figura vetorial SVG (*.svg)",
            )
        if not path:
            return False
        if Path(path).suffix.lower() not in (".png", ".pdf", ".svg"):
            path = str(path) + ".png"
        try:
            self.figure.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível exportar", str(exc))
            return False
        self.statusBar().showMessage(f"Figura exportada: {Path(path).name}")
        return True

    def export_data(self, checked=False, path=None):
        self.render()
        if not self._last_curves:
            self.statusBar().showMessage(
                "Exiba ao menos um espectro válido antes de exportar."
            )
            return False
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar dados das curvas visíveis",
                "IMESPEC_espectros.csv",
                "Tabela CSV (*.csv)",
            )
        if not path:
            return False
        if not str(path).lower().endswith(".csv"):
            path = str(path) + ".csv"
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "spectrum",
                        "label",
                        "temperature_K",
                        "raman_shift_cm-1",
                        "raw_intensity_au",
                        "display_intensity_au",
                        "display_shift_au",
                    ]
                )
                for s, plotted, shift in self._last_curves:
                    for x, raw, shown in zip(s.x, s.y, plotted):
                        writer.writerow(
                            [
                                s.name,
                                s.title,
                                "" if s.temperature is None else s.temperature,
                                format(float(x), ".17g"),
                                format(float(raw), ".17g"),
                                format(float(shown), ".17g"),
                                format(float(shift), ".17g"),
                            ]
                        )
        except Exception as exc:
            QMessageBox.critical(self, "Não foi possível exportar os dados", str(exc))
            return False
        self.statusBar().showMessage(
            "Dados exportados com intensidade original e deslocamento visual em colunas separadas."
        )
        return True

    def launch_map(self, checked=False):
        if self._legacy is not None or self._busy:
            return
        self.statusBar().showMessage(
            "Abrindo Raman Map… Sua série continua guardada nesta sessão."
        )
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        # Offscreen is only for automated checks of the Qt branch; Tk uses its own display.
        process.setProcessEnvironment(environment)
        process.setProgram(sys.executable)
        process.setArguments(
            ["--raman-map"]
            if getattr(sys, "frozen", False)
            else [str(ROOT / "IMESPEC.py"), "--raman-map"]
        )
        process.setWorkingDirectory(str(ROOT))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._legacy = process
        self._legacy_ready = False
        self._legacy_log = ""
        process.readyReadStandardOutput.connect(self._read_legacy_output)
        process.finished.connect(self._map_finished)
        process.errorOccurred.connect(self._map_error)
        process.start()

    def _read_legacy_output(self):
        if self._legacy is None:
            return
        text = bytes(self._legacy.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._legacy_log = (self._legacy_log + text)[-12000:]
        if "IMESPEC_MAP_READY" in self._legacy_log and not self._legacy_ready:
            self._legacy_ready = True
            self.hide()

    def _map_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            process, self._legacy = self._legacy, None
            if process:
                process.deleteLater()
            self.show()
            QMessageBox.critical(
                self, "Raman Map", "Não foi possível iniciar o módulo de mapas."
            )

    def _map_finished(self, code, status):
        self._read_legacy_output()
        process, self._legacy = self._legacy, None
        if process:
            process.deleteLater()
        self.show()
        self.raise_()
        self.activateWindow()
        if code == 42:
            self.show_page("multi")
        elif code == 43:
            self.show_page("home")
        elif code != 0:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Raman Map")
            dialog.setText(
                "O módulo de mapas foi encerrado com um erro. Sua série de espectros foi preservada."
            )
            dialog.setDetailedText(self._legacy_log)
            dialog.exec()
        self.statusBar().showMessage(
            "De volta ao IMESPEC. Sua série de espectros está preservada."
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self._busy:
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if len(paths) == 1 and paths[0].lower().endswith(".imespec"):
            self.open_project(path=paths[0])
        elif paths:
            self.import_paths(paths, append=bool(self.spectra))
        event.acceptProposedAction()

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Como usar o IMESPEC")
        dialog.resize(650, 570)
        box = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml("""
        <h2>Uma série em poucos passos</h2>
        <p><b>1. Abra os espectros.</b> Selecione arquivos TXT/CSV com duas colunas:
        Raman shift (cm⁻¹) e intensidade (a.u.). Também pode arrastar os arquivos para a janela.</p>
        <p><b>2. Confira a lista.</b> A temperatura é sugerida apenas quando o nome contém
        um número seguido de K. Selecione a curva para conferir ou editar esse valor.</p>
        <p><b>3. Compare.</b> Cascata 2D separa as curvas verticalmente. Sobrepor mostra as
        intensidades originais no mesmo eixo. Waterfall 3D distribui as curvas por
        temperatura, quando todas são conhecidas e distintas; caso contrário, usa a ordem da série.</p>
        <p>O espaçamento automático mantém as curvas separadas. Desmarque a opção para ajustar
        manualmente. Arraste os nomes para mudar a ordem e desmarque para ocultar uma curva.</p>
        <p><b>4. Salve e exporte.</b> Salvar projeto guarda os próprios dados, a ordem, cores,
        rótulos e opções. Exportar figura salva PNG em 300 dpi ou PDF/SVG vetorial.
        Arquivo → Exportar dados inclui valores originais e exibidos, com seus deslocamentos.</p>
        <h3>O que muda nos dados?</h3>
        <p>A cascata soma constantes apenas à visualização. O alinhamento opcional em
        Mais opções iguala a intensidade no ponto Raman escolhido, usando o ponto medido mais
        próximo de cada curva. Isso não é correção de fundo nem normalização.</p>
        <p>Janelas espectrais separadas aparecem no seletor Região espectral.
        Faixas parcialmente diferentes continuam com seus próprios pontos medidos;
        não são completadas por interpolação.</p>
        <h3>Raman Map</h3>
        <p>O módulo validado de mapas continua disponível e mantém a interface anterior nesta
        etapa da migração. Ao voltar por Início ou Multi-Spectra, a série da nova tela continua
        aberta. Exporte os mapas antes de sair do módulo; a sessão de mapas ainda é temporária.</p>
        <p>O Waterfall 3D representa a série de espectros. Ele não mede a altura física da amostra.</p>
        <h3>Análise de picos</h3>
        <p>Análise → Ajustar picos e sobretons (Ctrl+3) estima centros, larguras e áreas.
        Escolha o perfil e o fundo, ajuste a série e revise dados, componentes e resíduos.
        Mais opções permite estimar erros estatísticos por reamostragem e informar divisores de área.
        Exporte os parâmetros e as comparações em JSON/CSV. Ajustes não confirmam atribuições físicas;
        os erros não incluem calibração ou escolha do modelo. Os espectros originais são preservados.</p>
        <p><b>Atalhos:</b> Ctrl+O abrir espectros; Ctrl+S salvar projeto; Ctrl+E exportar figura;
        Ctrl+1 Raman Map; Ctrl+2 espectros; Ctrl+H início.</p>
        """)
        box.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event):
        analysis = getattr(self, "_peak_analysis", None)
        if analysis is not None and analysis.running:
            analysis.cancel()
            analysis._thread.finished.connect(self.close)
            event.ignore()
            return

        if self._busy or self._thread is not None:
            self.statusBar().showMessage(
                "Aguarde a leitura dos arquivos terminar antes de fechar."
            )
            event.ignore()
            return
        if self._legacy is not None:
            self.statusBar().showMessage(
                "Feche o módulo Raman Map antes de encerrar o programa."
            )
            event.ignore()
            return
        if self._confirm_replace():
            event.accept()
        else:
            event.ignore()


def run(argv=None):
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("IMESPEC")
    app.setOrganizationName("IMESPEC")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    font = QFont("Segoe UI" if os.name == "nt" else "DejaVu Sans", 10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    if argv:
        projects = [p for p in argv[1:] if str(p).lower().endswith(".imespec")]
        if projects:
            QTimer.singleShot(0, lambda: window.open_project(path=projects[0]))
    if "--smoke-test" in (argv or []):

        def check():
            try:
                # Exercise packaged SciPy and the actual native analysis dialog.
                import numpy as np
                from .spectra import Spectrum
                from .peaks import BANDS, analyze_series, primary, profile

                x = np.linspace(1750, 1980, 500)
                y = 30 + profile(x, 12000, 1864, 14)
                window.spectra = [Spectrum(x, y, "smoke_A_15K.txt", temperature=15)]
                report = analyze_series(window.spectra, (BANDS[0].single(),))
                assert len(report["fits"]) == 1
                assert abs(primary(report["fits"][0])["center_cm1"] - 1864) < 0.1
                window.open_peak_analysis()
                dialog = window._peak_analysis
                dialog.on_result(report)
                dialog.canvas.draw()
                dialog.close()
                window.dirty = False
                window.close()
            except Exception:
                app.exit(1)

        QTimer.singleShot(700, check)
    return app.exec()
