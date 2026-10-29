"""Responsive Data Quality view around the existing correction callbacks.

All scientific detection, repair, restore and export operations still belong
to fazer_imagem. Native Tk controls invoke those same callbacks; the extra
spectrum panel is read-only. No detector thresholds or repair math change.
"""

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import numpy as np
from matplotlib.backend_bases import MouseButton
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from imespec_analysis import AREA_UNIT, integration_trace
from imespec_bib1 import fazer_imagem
from imespec_theme import PALETTE


class QualityWorkspace(ttk.Frame):
    def __init__(
        self,
        master,
        matrix,
        start,
        stop,
        nx,
        ny,
        *,
        original_matrix,
        name,
        on_select,
        on_full,
        dependency_handler=None,
        source_path=None,
        software_version="unknown",
    ):
        super().__init__(master, style="Surface.TFrame", padding=(8, 6))
        self.pack(fill="both", expand=True)
        self.matrix, self.original_matrix = matrix, original_matrix
        self.start, self.stop, self.nx, self.ny = start, stop, nx, ny
        self.on_select, self.on_full = on_select, on_full
        self.selected = None
        self._closed = False
        self._layout_job = None
        self._layout_mode = None
        self._status_cache = None
        self._spectrum_cache = None
        self._wrap_labels = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = ttk.Panedwindow(self, orient="horizontal")
        self.body = body
        body.grid(row=0, column=0, sticky="nsew")
        self.plots = tk.PanedWindow(
            body,
            orient="horizontal",
            background="white",
            borderwidth=0,
            sashwidth=6,
            sashrelief="flat",
            opaqueresize=True,
            width=1,
            height=1,
        )
        body.add(self.plots, weight=1)
        self.plots.bind("<Configure>", self._schedule_layout)
        body.bind("<Configure>", self._schedule_layout)
        self.map_host = ttk.Frame(self.plots, style="Surface.TFrame", width=400)
        self.spectrum_host = ttk.Frame(
            self.plots, style="Surface.TFrame", padding=(10, 0)
        )
        self.plots.add(self.map_host, stretch="always", minsize=170)
        self.plots.add(self.spectrum_host, stretch="always", minsize=200)
        tools = ttk.Frame(body, style="Surface.TFrame", width=335)
        body.add(tools, weight=0)
        self.tools_footer = ttk.Frame(tools, padding=(12, 8), style="Surface.TFrame")
        self.tools_footer.pack(side="bottom", fill="x")
        self.tools_canvas = tk.Canvas(
            tools, bg="white", bd=0, highlightthickness=0, width=325
        )
        self.tools_canvas.pack(side="left", fill="both", expand=True)
        sy = ttk.Scrollbar(tools, orient="vertical", command=self.tools_canvas.yview)
        sy.pack(side="right", fill="y")
        self.tools_canvas.configure(yscrollcommand=sy.set)
        self.controls = ttk.Frame(
            self.tools_canvas, style="Surface.TFrame", padding=(12, 6)
        )
        window = self.tools_canvas.create_window(
            (0, 0), window=self.controls, anchor="nw"
        )
        self.controls.bind(
            "<Configure>",
            lambda event: self.tools_canvas.configure(
                scrollregion=self.tools_canvas.bbox("all")
            ),
        )

        def fit_tools(event):
            self.tools_canvas.itemconfigure(window, width=event.width)
            for widget in self._wrap_labels:
                widget.configure(wraplength=max(150, event.width - 76))

        self.tools_canvas.bind("<Configure>", fit_tools)

        self.figure = fazer_imagem(
            matrix,
            start,
            stop,
            nx,
            ny,
            5759,
            dependency_handler=dependency_handler,
            source_path=source_path,
            software_version=software_version,
            embed_parent=self.map_host,
            spectrum_callback=self._core_selected,
        )
        self.image = self.figure._imespec_imagem
        self.figure.canvas.get_tk_widget().configure(width=1, height=1)
        self.map_ax = self.image.axes
        self.colorbar = self.figure._imespec_colorbar
        # Retain the original controls and their callbacks, but move interaction
        # to native widgets outside the scientific figure.
        self.core_status = self.figure.texts[-1]
        self.figure._imespec_radio.disconnect_events()
        self.figure._imespec_radio._useblit = False
        for text in self.figure.texts:
            text.set_visible(False)
        for ax in self.figure.axes:
            if ax not in (self.map_ax, self.colorbar.ax):
                ax.set_visible(False)
        self.map_ax.set_position([0.16, 0.12, 0.62, 0.80])
        self.colorbar.ax.set_position([0.81, 0.12, 0.035, 0.80])
        self.map_ax.set_title(
            f"{name}\n{min(matrix[start, 0], matrix[stop, 0]):.1f}–"
            f"{max(matrix[start, 0], matrix[stop, 0]):.1f} cm⁻¹",
            fontsize=10, fontweight="bold", color=PALETTE["text"]
        )
        self.map_ax.set_xlabel("X (pixel)", fontsize=9)
        self.map_ax.set_ylabel("Y (pixel)", fontsize=9)
        self.map_ax.tick_params(labelsize=8)
        self.colorbar.set_label(f"Área ({AREA_UNIT})", fontsize=8)
        self.colorbar.ax.tick_params(labelsize=8)
        (self.marker,) = self.map_ax.plot(
            [], [], "+", color="white", markersize=12, markeredgewidth=2
        )

        header = ttk.Frame(self.spectrum_host, style="Surface.TFrame")
        header.pack(fill="x", pady=(5, 8))
        ttk.Label(header, text="Espectro do ponto", style="Section.TLabel").pack(
            side="left"
        )
        ttk.Button(
            header, text="Ampliar", command=self._open_full, style="Ghost.TButton"
        ).pack(side="right")
        self.pixel_var = tk.StringVar(
            value="Clique em um ponto do mapa para inspecionar."
        )
        ttk.Label(
            self.spectrum_host,
            textvariable=self.pixel_var,
            style="Caption.TLabel",
            wraplength=490,
        ).pack(fill="x", pady=(0, 6))
        self.focus_band = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.spectrum_host,
            text="Focar banda selecionada",
            variable=self.focus_band,
            command=lambda: self._draw_spectrum(force=True),
        ).pack(anchor="w")
        self.spectrum_figure = Figure(figsize=(6, 5), dpi=100, facecolor="white")
        self.spectrum_ax = self.spectrum_figure.add_subplot(111)
        self.spectrum_canvas = FigureCanvasTkAgg(
            self.spectrum_figure, master=self.spectrum_host
        )
        self.spectrum_canvas.get_tk_widget().configure(width=1, height=1)
        self.spectrum_canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar_host = ttk.Frame(self.spectrum_host)
        toolbar_host.pack(fill="x")
        self.spectrum_toolbar = NavigationToolbar2Tk(
            self.spectrum_canvas, toolbar_host, pack_toolbar=False
        )
        self.spectrum_toolbar.pack(fill="x")
        self.area_var = tk.StringVar(
            value="As correções do mapa e do espectro são identificadas separadamente."
        )
        self.area_label = ttk.Label(
            self.spectrum_host,
            textvariable=self.area_var,
            style="Caption.TLabel",
            wraplength=490,
            padding=(0, 8),
        )
        self.spectrum_canvas.get_tk_widget().pack_forget()
        toolbar_host.pack_forget()
        self.area_label.pack(side="bottom", fill="x")
        toolbar_host.pack(side="bottom", fill="x")
        self.spectrum_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self._build_controls()
        self._draw_cid = self.figure.canvas.mpl_connect("draw_event", self._sync)
        self._click_cid = self.figure.canvas.mpl_connect(
            "button_press_event", self._clicked
        )
        self.show_pixel(ny // 2, nx // 2)
        self._sync()
        self.after_idle(
            lambda: (
                body.sashpos(0, max(440, self.winfo_width() - 350))
                if body.winfo_exists()
                else None
            )
        )
        self.figure.canvas.draw_idle()

    def _text(self, parent, text, **kwargs):
        widget = ttk.Label(
            parent,
            text=text,
            style="Caption.TLabel",
            wraplength=285,
            justify="left",
            **kwargs,
        )
        widget.pack(fill="x", pady=(0, 8))
        self._wrap_labels.append(widget)
        return widget

    def _build_controls(self):
        self._text(
            self.controls,
            "Clique esquerdo: inspecionar.\nClique direito: reparar o pixel no mapa.",
        )
        cosmic = ttk.LabelFrame(self.controls, text="1 · Raios cósmicos", padding=12)
        cosmic.pack(fill="x", pady=(2, 12))
        self._text(
            cosmic,
            "Revisa picos espúrios nos espectros e recalcula o mapa após a aplicação.",
        )
        self.cosmic_detect = ttk.Button(
            cosmic,
            text="Detectar candidatos",
            command=lambda: self._invoke("cosmic_detect"),
        )
        self.cosmic_detect.pack(fill="x", pady=(0, 6))
        self.cosmic_apply = ttk.Button(
            cosmic,
            text="Aplicar remoção",
            style="Accent.TButton",
            command=lambda: self._invoke("cosmic_apply"),
        )
        self.cosmic_apply.pack(fill="x")
        self._text(
            cosmic, "Revise as marcações antes de aplicar.", padding=(0, 8, 0, 0)
        )

        pixels = ttk.LabelFrame(
            self.controls, text="2 · Corrigir pixels do mapa", padding=12
        )
        pixels.pack(fill="x", pady=(0, 12))
        self._text(
            pixels,
            "Usa os vizinhos para reparar o valor do mapa. O espectro desse ponto é preservado.",
        )
        self.method_var = tk.IntVar(value=2)
        for index, text in enumerate(
            ("Média · 4 vizinhos", "Média · 8 vizinhos", "Mediana · 8 vizinhos")
        ):
            ttk.Radiobutton(
                pixels,
                text=text,
                variable=self.method_var,
                value=index,
                command=lambda: self.figure._imespec_radio.set_active(
                    self.method_var.get()
                ),
            ).pack(anchor="w", pady=2)
        ttk.Separator(pixels).pack(fill="x", pady=8)
        self.bad_detect = ttk.Button(
            pixels,
            text="Detectar candidatos",
            command=lambda: self._invoke("bad_detect"),
        )
        self.bad_detect.pack(fill="x", pady=(0, 6))
        self.bad_apply = ttk.Button(
            pixels,
            text="Aplicar correção",
            style="Accent.TButton",
            command=lambda: self._invoke("bad_apply"),
        )
        self.bad_apply.pack(fill="x")
        self._text(
            pixels,
            "Para um reparo manual, clique com o botão direito no ponto desejado.",
            padding=(0, 8, 0, 0),
        )
        commands = ttk.Frame(self.controls, style="Surface.TFrame")
        commands.pack(fill="x", pady=(0, 12))
        ttk.Button(
            commands, text="Limpar marcações", command=lambda: self._invoke("clear")
        ).pack(fill="x", pady=(0, 6))
        ttk.Button(
            commands, text="Restaurar tudo", command=lambda: self._invoke("restore")
        ).pack(fill="x")
        self.summary_var = tk.StringVar()
        ttk.Label(
            self.controls, textvariable=self.summary_var, style="Section.TLabel"
        ).pack(anchor="w", pady=(0, 7))
        self.status_var = tk.StringVar(value="Pronto.")
        status = ttk.Label(
            self.controls,
            textvariable=self.status_var,
            style="Caption.TLabel",
            wraplength=285,
            justify="left",
        )
        status.pack(fill="x", pady=(0, 12))
        self._wrap_labels.append(status)
        ttk.Button(
            self.tools_footer,
            text="Exportar análise…",
            style="Accent.TButton",
            command=lambda: self._invoke("export"),
        ).pack(fill="x", pady=(0, 8))

        def wheel(event):
            delta = -1 if getattr(event, "num", None) == 4 else 1
            if getattr(event, "delta", 0):
                delta = -1 if event.delta > 0 else 1
            self.tools_canvas.yview_scroll(delta, "units")
            return "break"

        def bind_tree(widget):
            for pattern in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(pattern, wheel)
            for child in widget.winfo_children():
                bind_tree(child)

        bind_tree(self.controls)

    def _invoke(self, name):
        control = getattr(self.figure, f"_imespec_botao_{name}")
        # A real event is required for Clear Marks to discard reviewed reports.
        control._observers.process(
            "clicked",
            SimpleNamespace(name="button_press_event", button=MouseButton.LEFT),
        )
        self._sync()
        self._draw_spectrum(force=True)

    def _core_selected(self, number, x, y, row, column):
        self.show_pixel(row, column)
        self.on_select(row, column)

    def _clicked(self, event):
        if (
            event.inaxes is not self.map_ax
            or event.xdata is None
            or event.ydata is None
        ):
            return
        if event.button is MouseButton.RIGHT:
            self.show_pixel(
                int(np.floor(event.ydata + 0.5)), int(np.floor(event.xdata + 0.5))
            )
            self._sync()
            self.on_select(*self.selected) if self.selected is not None else None

    def show_pixel(self, row, column):
        if not (0 <= row < self.ny and 0 <= column < self.nx):
            return
        self.selected = (row, column)
        self.marker.set_data([column], [row])
        self._draw_spectrum(force=True)
        self.figure.canvas.draw_idle()

    def _open_full(self):
        if self.selected is not None:
            self.on_full(*self.selected)

    def _draw_spectrum(self, force=False):
        if self.selected is None or self._closed:
            return
        row, column = self.selected
        number = row * self.nx + column + 1
        x = np.asarray(self.matrix[:, 0], dtype=float)
        y = np.asarray(self.matrix[:, number], dtype=float)
        raw = np.asarray(self.original_matrix[:, number], dtype=float)
        map_value = float(self.figure._imespec_area[row, column])
        key = (row, column, map_value, self.focus_band.get(), y.tobytes())
        if not force and key == self._spectrum_cache:
            return
        self._spectrum_cache = key
        ax = self.spectrum_ax
        ax.clear()
        if not np.array_equal(y, raw):
            ax.plot(x, raw, color="#A0ABBC", linewidth=1.0, label="Original")
            curve_label = "Atual"
        else:
            curve_label = "Espectro"
        ax.plot(x, y, color=PALETTE["primary"], linewidth=1.1, label=curve_label)
        trace = integration_trace(x, y, self.start, self.stop)
        ax.plot(
            trace["x"],
            trace["background"],
            "--",
            color="#D97706",
            linewidth=1,
            label="Fundo local",
        )
        ax.fill_between(
            trace["x"], trace["background"], trace["y"], color="#93B4FA", alpha=0.32
        )
        if self.focus_band.get():
            lo, hi = float(trace["x"].min()), float(trace["x"].max())
            pad = max((hi - lo) * 0.7, abs(float(x[1] - x[0])) * 5)
            lower, upper = max(float(x.min()), lo - pad), min(float(x.max()), hi + pad)
            ax.set_xlim(lower, upper)
            visible = y[(x >= lower) & (x <= upper)]
            if visible.size:
                minimum, maximum = float(visible.min()), float(visible.max())
                margin = max((maximum - minimum) * 0.12, abs(maximum) * 0.01, 1e-9)
                ax.set_ylim(minimum - margin, maximum + margin)
        ax.set_xlabel("Raman shift (cm⁻¹)", fontsize=9)
        ax.set_ylabel("Intensidade (a.u.)", fontsize=9)
        ax.tick_params(labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="best", frameon=False, fontsize=8)
        self.spectrum_figure.subplots_adjust(
            left=0.17, right=0.96, top=0.95, bottom=0.17
        )
        self.pixel_var.set(f"X={column} · Y={row} · espectro #{number}")
        note = (
            " · valor do mapa reparado; espectro preservado"
            if not np.isclose(map_value, trace["area"], rtol=1e-6, atol=1e-7)
            else ""
        )
        self.area_var.set(
            f"Área no mapa: {map_value:.6g} {AREA_UNIT}\nIntegral do espectro: {trace['area']:.6g} {AREA_UNIT}{note}"
        )
        self.spectrum_canvas.draw_idle()

    def _sync(self, event=None):
        if self._closed:
            return
        self.cosmic_apply.configure(
            state=(
                "normal"
                if self.figure._imespec_botao_cosmic_apply.get_active()
                else "disabled"
            )
        )
        bad_pending = any(
            line.get_marker() == "o" and line.get_markeredgecolor() == "red"
            for line in self.map_ax.lines
        )
        self.bad_apply.configure(state="normal" if bad_pending else "disabled")
        history = self.figure._imespec_export_history
        self.summary_var.set(
            f"{len(history['cosmic_reports'])} remoção(ões) · {len(history['bad_pixel_repairs'])} pixel(s) reparado(s)"
        )
        status = self.core_status.get_text()
        if status != self._status_cache:
            self._status_cache = status
            self.status_var.set(
                "Pronto. Inspecione os pontos e revise as marcações antes de aplicar."
                if status == "Ready."
                else status
            )
            if status.startswith("Map pixel (") and history["bad_pixel_repairs"]:
                last = history["bad_pixel_repairs"][-1]
                self.status_var.set(
                    f"Pixel ({last['x_pixel']}, {last['y_pixel']}): "
                    f"{last['old_value']:.5g} → {last['new_value']:.5g} {AREA_UNIT}. "
                    "O valor do mapa foi reparado. O espectro foi preservado."
                )
            elif status.startswith("Spectra and Raman map restored"):
                self.status_var.set(
                    "Mapa e espectros restaurados ao estado inicial desta banda."
                )
        self._draw_spectrum()

    def _schedule_layout(self, event=None):
        if self._closed:
            return
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(90, self._apply_layout)

    def _apply_layout(self):
        self._layout_job = None
        if self._closed or not self.plots.winfo_exists():
            return
        desired = max(300, self.body.winfo_width() - 350)
        if abs(self.body.sashpos(0) - desired) > 3:
            self.body.sashpos(0, desired)
            self.update_idletasks()
        mode = "horizontal" if self.plots.winfo_width() >= 800 else "vertical"
        if mode != self._layout_mode:
            self._layout_mode = mode
            self.plots.configure(orient=mode)
            self.update_idletasks()
            dimension = (
                self.plots.winfo_width()
                if mode == "horizontal"
                else self.plots.winfo_height()
            )
            position = int(dimension * (0.42 if mode == "horizontal" else 0.55))
            self.plots.sash_place(
                0,
                position if mode == "horizontal" else 0,
                0 if mode == "horizontal" else position,
            )

    def destroy(self):
        self._closed = True
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        if hasattr(self, "figure"):
            self.figure.canvas.mpl_disconnect(self._draw_cid)
            self.figure.canvas.mpl_disconnect(self._click_cid)
        super().destroy()
