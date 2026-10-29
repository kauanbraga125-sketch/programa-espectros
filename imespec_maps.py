"""Raman map comparison and linked inspection, independent of the application shell."""

import copy
import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
from matplotlib.figure import Figure
from matplotlib import colormaps
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import imespec_bib1 as _imespec_core
from imespec_bib1 import fazer_imagem
from imespec_analysis import (
    area_ratio,
    integration_trace,
    array_hash,
    finite_limits,
    REASONS,
    AREA_UNIT,
)
from imespec_theme import PALETTE
from imespec_quality import QualityWorkspace


class RamanMapCollection(ttk.Frame):
    """Compare bands from one acquisition, retaining each map's review state.

    Band integration uses the existing scientific routine. Unedited maps share
    the imported spectra; a private working matrix is allocated only when a
    map's Data Quality editor is opened. Independent editors cannot restore or
    overwrite the corrections made in another band.
    """

    COLORS = ("#2563EB", "#D97706", "#059669", "#9333EA", "#DC2626", "#0891B2")

    def __init__(
        self,
        master,
        matrix,
        quality_notebook,
        *,
        add_band,
        show_quality,
        show_spectrum,
        source_path,
        software_version,
        dependency_handler=None,
        status_callback=None,
        quality_selector=None,
    ):
        super().__init__(master, padding=10, style="Surface.TFrame")
        self.matrix = matrix
        self.quality_notebook = quality_notebook
        self.add_band_callback = add_band
        self.show_quality_callback = show_quality
        self.show_spectrum_callback = show_spectrum
        self.source_path = source_path
        self.software_version = software_version
        self.dependency_handler = dependency_handler
        self.status_callback = status_callback or (lambda text: None)
        self.quality_selector = quality_selector
        self._opening_quality = False
        self.records = []
        self.active_id = None
        self.selected_cell = None
        self._next_id = 1
        self.loaded_matrix_hash = array_hash(matrix)
        self.show_integration = tk.BooleanVar(value=True)
        self._ratio_dialog = None
        self._refresh_job = None
        self._reveal_job = None
        self._columns = 2
        self._closed = False
        self._layout_mode = None
        self._layout_job = None
        self._settle_job = None
        self._sash_initialized = False
        self.layout_var = tk.StringVar(value="Auto")
        self.focus_band = tk.BooleanVar(value=False)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        primary = ttk.Frame(self, style="Surface.TFrame")
        primary.grid(row=0, column=0, sticky="ew", pady=(2, 10))
        ttk.Label(primary, text="Map collection", style="Section.TLabel").pack(
            side="left", padx=(0, 16)
        )
        ttk.Button(primary, text="+ Add band", command=add_band).pack(
            side="left", padx=(0, 6)
        )
        self.ratio_button = ttk.Button(
            primary,
            text="Create ratio A/B",
            style="Accent.TButton",
            command=self.open_ratio_dialog,
            state="disabled",
        )
        self.ratio_button.pack(side="left")
        layout_selector = ttk.Combobox(
            primary,
            textvariable=self.layout_var,
            state="readonly",
            values=("Auto", "Side by side", "Stacked"),
            width=12,
        )
        layout_selector.pack(side="right")
        layout_selector.bind("<<ComboboxSelected>>", lambda event: self._apply_layout())
        ttk.Label(primary, text="Layout", style="Caption.TLabel").pack(
            side="right", padx=(8, 6)
        )
        actions = ttk.Frame(self, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(actions, text="Active map", style="Caption.TLabel").pack(
            side="left", padx=(0, 8)
        )
        self.map_name = tk.StringVar()
        self.selector = ttk.Combobox(
            actions, textvariable=self.map_name, state="readonly", width=21
        )
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self._select_from_list)
        self.remove_button = ttk.Button(
            actions, text="Remove", style="Danger.TButton", command=self.remove_active
        )
        self.remove_button.pack(side="right")
        self.export_button = ttk.Button(
            actions, text="Export…", command=self.export_selected
        )
        self.export_button.pack(side="right", padx=6)
        self.quality_button = ttk.Button(
            actions, text="Data Quality", command=self.open_quality
        )
        self.quality_button.pack(side="right")
        self.count_var = tk.StringVar(value="0 maps")
        self.summary_var = tk.StringVar(
            value="Add two bands from this acquisition to create an area ratio."
        )
        hint_row = ttk.Frame(self, style="Surface.TFrame")
        hint_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        hint_row.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(
            hint_row,
            textvariable=self.summary_var,
            style="Caption.TLabel",
            wraplength=600,
        )
        self.summary_label.grid(row=0, column=0, sticky="w")
        ttk.Label(hint_row, textvariable=self.count_var, style="Caption.TLabel").grid(
            row=0, column=1, sticky="e", padx=(12, 0)
        )
        hint_row.bind(
            "<Configure>",
            lambda event: self.summary_label.configure(
                wraplength=max(240, event.width - 110)
            ),
        )

        self.panels = tk.PanedWindow(
            self,
            orient="horizontal",
            background=PALETTE["border"],
            borderwidth=0,
            sashwidth=7,
            sashpad=1,
            opaqueresize=True,
        )
        self.panels.grid(row=3, column=0, sticky="nsew")
        self.maps_host = ttk.Frame(
            self.panels, style="Surface.TFrame", padding=(4, 6, 6, 2)
        )
        self.panels.add(self.maps_host, minsize=300, stretch="always")
        self.maps_host.rowconfigure(1, weight=1)
        self.maps_host.columnconfigure(0, weight=1)
        ttk.Label(
            self.maps_host,
            text="SPATIAL MAPS  ·  gray = excluded pixels",
            foreground=PALETTE["muted"],
            style="Caption.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.scroller = tk.Canvas(
            self.maps_host, background="white", highlightthickness=0, height=340
        )
        self.scroller.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            self.maps_host, orient="vertical", command=self.scroller.yview
        )
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.scroller.configure(yscrollcommand=scrollbar.set)
        self.figure = Figure(figsize=(10, 3.3), dpi=100, facecolor="white")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.scroller)
        self.canvas.get_tk_widget().bind("<Map>", self._schedule_canvas_settle, add="+")
        self._window = self.scroller.create_window(
            (0, 0),
            window=self.canvas.get_tk_widget(),
            anchor="nw",
            width=1000,
            height=330,
        )
        self.scroller.bind("<Configure>", self._resize_maps)
        self.canvas.mpl_connect("button_press_event", self._click_map)
        self.canvas.mpl_connect("scroll_event", self._scroll_maps)

        self.spectrum_host = ttk.Frame(
            self.panels, style="Surface.TFrame", padding=(12, 8, 4, 2)
        )
        self.panels.add(self.spectrum_host, minsize=260, stretch="always")
        self.spectrum_host.rowconfigure(2, weight=1)
        self.spectrum_host.columnconfigure(0, weight=1)
        spectrum_header = ttk.Frame(self.spectrum_host, style="Surface.TFrame")
        spectrum_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(spectrum_header, text="Pixel spectrum", style="Section.TLabel").pack(
            side="left"
        )
        self.full_spectrum_button = ttk.Button(
            spectrum_header,
            text="Open spectrum",
            command=self._open_selected_spectrum,
            state="disabled",
        )
        self.full_spectrum_button.pack(side="right")
        spectrum_controls = ttk.Frame(self.spectrum_host, style="Surface.TFrame")
        spectrum_controls.grid(row=1, column=0, sticky="ew", pady=(5, 5))
        self.pixel_info = tk.StringVar(value="No pixel selected")
        ttk.Label(
            spectrum_controls, textvariable=self.pixel_info, style="Caption.TLabel"
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            spectrum_controls,
            text="Focus band",
            variable=self.focus_band,
            command=self._draw_spectrum,
        ).grid(row=1, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(
            spectrum_controls,
            text="Show integration",
            variable=self.show_integration,
            command=self._draw_spectrum,
        ).grid(row=1, column=1, sticky="w")

        self.details_body = ttk.Frame(self.spectrum_host, style="Surface.TFrame")
        self.details_body.grid(row=2, column=0, sticky="nsew")
        self.plot_frame = ttk.Frame(self.details_body, style="Surface.TFrame")
        self.plot_frame.rowconfigure(0, weight=1)
        self.plot_frame.columnconfigure(0, weight=1)
        self.spectrum_figure = Figure(figsize=(5, 3.7), dpi=100, facecolor="white")
        self.spectrum_ax = self.spectrum_figure.add_subplot(111)
        self.spectrum_canvas = FigureCanvasTkAgg(
            self.spectrum_figure, master=self.plot_frame
        )
        self.spectrum_canvas.get_tk_widget().bind(
            "<Map>", self._schedule_canvas_settle, add="+"
        )
        self.spectrum_canvas.mpl_connect("resize_event", self._fit_spectrum_axes)
        self.spectrum_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar_frame = ttk.Frame(self.plot_frame, style="Surface.TFrame")
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        self.spectrum_toolbar = NavigationToolbar2Tk(
            self.spectrum_canvas, toolbar_frame, pack_toolbar=False
        )
        self.spectrum_toolbar.pack(fill="x")
        self.metrics_frame = ttk.LabelFrame(
            self.details_body, text="Band areas at selected pixel", padding=8
        )
        self.metrics_frame.rowconfigure(0, weight=1)
        self.metrics_frame.columnconfigure(0, weight=1)
        self.band_table = ttk.Treeview(
            self.metrics_frame,
            columns=("band", "range", "area", "unit"),
            show="headings",
            height=2,
            selectmode="browse",
        )
        for key, title, width in [
            ("band", "Map", 80),
            ("range", "Band / inputs", 105),
            ("area", "Value", 90),
            ("unit", "Unit", 65),
        ]:
            self.band_table.heading(key, text=title)
            self.band_table.column(
                key, width=width, minwidth=50, anchor="e" if key == "area" else "w"
            )
        self.band_table.grid(row=0, column=0, sticky="nsew")
        table_scroll = ttk.Scrollbar(
            self.metrics_frame, orient="vertical", command=self.band_table.yview
        )
        table_scroll.grid(row=0, column=1, sticky="ns")
        self.band_table.configure(yscrollcommand=table_scroll.set)
        self.band_table.bind("<<TreeviewSelect>>", self._select_from_table)
        self.band_table.bind("<Configure>", self._fit_table_columns, add="+")
        self.panels.bind("<Configure>", self._apply_layout, add="+")
        self._apply_layout()
        self._draw_maps()
        self._draw_spectrum()

    def _record(self, map_id=None):
        target = self.active_id if map_id is None else map_id
        return next((record for record in self.records if record["id"] == target), None)

    def _resize_maps(self, event=None):
        width = max(1, self.scroller.winfo_width())
        ratio = (
            float(np.median([r["nx"] / r["ny"] for r in self.records]))
            if self.records
            else 1.0
        )
        minimum = max(225, min(370, 220 * ratio + 100))
        columns = min(3, max(1, len(self.records)), max(1, int(width // minimum)))
        if columns != self._columns:
            self._columns = columns
            self._draw_maps()
        else:
            self._position_map_canvas()

    def _position_map_canvas(self):
        width = max(1, self.scroller.winfo_width())
        height = self._map_canvas_height()
        columns = min(self._columns, max(1, len(self.records)))
        ratios = [record["nx"] / record["ny"] for record in self.records]
        ratio = float(np.median(ratios)) if ratios else 1.0
        rows = max(1, math.ceil(len(self.records) / columns))
        image_height = max(120, height / rows - 105)
        preferred_width = columns * (image_height * ratio + 115) + 20
        canvas_width = min(width, max(260, int(preferred_width)))
        self.scroller.itemconfigure(self._window, width=canvas_width, height=height)
        self.scroller.coords(self._window, max(0, (width - canvas_width) // 2), 0)
        self.scroller.configure(scrollregion=(0, 0, width, height))
        self._fit_map_axes(canvas_width, height)

    def _fit_map_axes(self, width, height):
        if width > 160 and height > 140:
            spacing = 0.72 if width / max(1, self._columns) < 300 else 0.42
            self.figure.subplots_adjust(
                left=55 / width,
                right=1 - 70 / width,
                bottom=45 / height,
                top=1 - 52 / height,
                wspace=spacing,
                hspace=0.70,
            )

    def _fit_spectrum_axes(self, event=None):
        width, height = (
            self.spectrum_figure.get_size_inches() * self.spectrum_figure.dpi
        )
        if width > 120 and height > 60:
            compact = height < 180
            self.spectrum_figure.subplots_adjust(
                left=min(0.34, 58 / width),
                right=1 - 18 / width,
                bottom=min(0.70, 45 / height),
                top=1 - (8 if compact else 30) / height,
            )
            self.spectrum_ax.set_ylabel(
                "Intensity (a.u.)", fontsize=7 if compact else 9
            )
            self.spectrum_ax.yaxis.set_label_coords(
                15 / width, 0.5, transform=self.spectrum_figure.transFigure
            )
            self.spectrum_ax.xaxis.label.set_fontsize(8 if compact else 9)
            self.spectrum_ax.title.set_visible(not compact)

    def _schedule_canvas_settle(self, event=None):
        if not self._closed and self._settle_job is None:
            self._settle_job = self.after_idle(self._settle_canvas_sizes)

    def _settle_canvas_sizes(self):
        """Finish the first display after Tk has applied its DPI and pane sizes."""
        self._settle_job = None
        if self._closed:
            return
        for canvas in (self.canvas, self.spectrum_canvas):
            widget = canvas.get_tk_widget()
            if not widget.winfo_ismapped():
                continue
            width, height = widget.winfo_width(), widget.winfo_height()
            if width < 100 or height < 100:
                continue
            if (
                abs(canvas.figure.bbox.width - width) > 1
                or abs(canvas.figure.bbox.height - height) > 1
            ):
                resize_event = tk.Event()
                resize_event.width, resize_event.height = width, height
                canvas.resize(resize_event)

    def _apply_layout(self, event=None):
        if self._closed:
            return
        choice = self.layout_var.get()
        ratios = [record["nx"] / record["ny"] for record in self.records]
        tall_maps = bool(ratios) and float(np.median(ratios)) < 0.9
        horizontal = choice == "Side by side" or (
            choice == "Auto" and self.panels.winfo_width() >= 820 and tall_maps
        )
        mode = "horizontal" if horizontal else "vertical"
        if mode == self._layout_mode:
            if horizontal and self.panels.winfo_width() >= 700:
                sash_x = self.panels.sash_coord(0)[0]
                if sash_x < 320 or sash_x > self.panels.winfo_width() - 375:
                    if self._layout_job is None:
                        self._layout_job = self.after_idle(self._place_sash)
                    return
            if not self._sash_initialized and self._layout_job is None:
                self._layout_job = self.after_idle(self._place_sash)
            return
        self._layout_mode = mode
        self._sash_initialized = False
        self.panels.configure(orient=mode)
        self.panels.paneconfigure(self.maps_host, minsize=320 if horizontal else 200)
        self.panels.paneconfigure(
            self.spectrum_host, minsize=370 if horizontal else 230
        )
        self.plot_frame.grid(row=0, column=0, sticky="nsew")
        self.details_body.rowconfigure(0, weight=1)
        self.details_body.columnconfigure(0, weight=1)
        if horizontal:
            self.metrics_frame.grid_propagate(True)
            self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0), padx=0)
            self.details_body.columnconfigure(1, weight=0, minsize=0)
        else:
            self.metrics_frame.configure(width=350)
            self.metrics_frame.grid_propagate(False)
            self.metrics_frame.grid(
                row=0, column=1, sticky="nsew", padx=(12, 0), pady=0
            )
            self.details_body.columnconfigure(1, weight=0, minsize=350)
        self._fit_table_columns()
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after_idle(self._place_sash)

    def _place_sash(self):
        self._layout_job = None
        if self._closed:
            return
        horizontal = self._layout_mode == "horizontal"
        extent = self.panels.winfo_width() if horizontal else self.panels.winfo_height()
        if extent < 100:
            return
        horizontal_position = min(
            extent - 375,
            max(320, int(extent * (0.65 if len(self.records) >= 3 else 0.58))),
        )
        self.panels.sash_place(
            0,
            horizontal_position if horizontal else 0,
            0 if horizontal else int(extent * 0.57),
        )
        self._sash_initialized = True
        self._schedule_canvas_settle()

    def _open_selected_spectrum(self):
        if self.active_id is not None and self.selected_cell is not None:
            self.inspect_pixel(self.active_id, *self.selected_cell, open_full=True)

    def _select_from_table(self, event=None):
        selection = self.band_table.selection()
        if not selection:
            return
        map_id = int(selection[0])
        if map_id == self.active_id:
            return
        previous = self._record()
        record = self._record(map_id)
        if record is None:
            return
        if previous is None or (previous["nx"], previous["ny"]) != (
            record["nx"],
            record["ny"],
        ):
            self.selected_cell = None
        self.active_id = map_id
        self.map_name.set(record["name"])
        self._update_markers()
        self._draw_spectrum()
        self._reveal_active_map()

    def _sync_band_table(self):
        active = self._record()
        ids = {str(r["id"]) for r in self.records}
        for iid in self.band_table.get_children():
            if iid not in ids:
                self.band_table.delete(iid)
        for r in self.records:
            compatible = active and (r["nx"], r["ny"]) == (active["nx"], active["ny"])
            value = "—"
            if compatible and self.selected_cell is not None:
                v = float(r["area"][self.selected_cell])
                value = f"{v:.6g}" if np.isfinite(v) else "excluded"
            if r.get("kind") == "ratio":
                a, b = self._spectrum_sources(r)
                description = f"{a['name']} / {b['name']}"
                unit = "1"
            else:
                lo, hi = self._band_limits(r)
                description = f"{lo:.1f}–{hi:.1f}"
                unit = AREA_UNIT
            values = (r["name"], description, value, unit)
            if self.band_table.exists(str(r["id"])):
                self.band_table.item(str(r["id"]), values=values)
            else:
                self.band_table.insert("", "end", iid=str(r["id"]), values=values)
        self.band_table.configure(height=max(2, min(5, len(self.records))))
        if active:
            self.band_table.selection_set(str(active["id"]))
            self.band_table.see(str(active["id"]))
        self._update_summary()

    def _map_canvas_height(self):
        rows = max(1, math.ceil(len(self.records) / self._columns))
        # A single row fits the available pane, including both axis labels.
        # Additional rows retain a readable height and can be scrolled.
        return max(160, self.scroller.winfo_height()) if rows == 1 else rows * 310

    def _scroll_maps(self, event):
        if len(self.records) > self._columns:
            self.scroller.yview_scroll(-1 if event.step > 0 else 1, "units")

    def add_map(self, name, start, stop, nx, ny):
        start, stop = sorted((int(start), int(stop)))
        # This is the same local-background integration as the original map.
        area = _imespec_core._calcular_area_raman(self.matrix, start, stop, nx, ny)
        base_name = str(name).strip()[:60] or f"Band {self._next_id}"
        title = base_name
        suffix = 2
        existing = {record["name"] for record in self.records}
        while title in existing:
            title = f"{base_name} ({suffix})"
            suffix += 1
        record = {
            "id": self._next_id,
            "name": title,
            "start": start,
            "stop": stop,
            "nx": int(nx),
            "ny": int(ny),
            "area": area,
            "kind": "band",
            "color": self.COLORS[(self._next_id - 1) % len(self.COLORS)],
            "spectra": None,
            "quality_figure": None,
            "quality_frame": None,
        }
        self._next_id += 1
        self.records.append(record)
        self.active_id = record["id"]
        self.selected_cell = None
        self._apply_layout()
        self._draw_maps()
        self._draw_spectrum()
        self.status_callback(
            f"Saved {title}. {len(self.records)} band map(s) available for comparison."
        )
        self._sync_quality_selector()
        return record

    def _draw_maps(self):
        if self._closed:
            return
        width = max(1, self.scroller.winfo_width())
        aspect = (
            float(np.median([r["nx"] / r["ny"] for r in self.records]))
            if self.records
            else 1.0
        )
        minimum = max(225, min(370, 220 * aspect + 100))
        self._columns = min(3, max(1, len(self.records)), max(1, int(width // minimum)))
        self.figure.clear()
        self.selector["values"] = tuple(r["name"] for r in self.records)
        active = self._record()
        self.map_name.set(active["name"] if active else "")
        self.count_var.set(f"{len(self.records)} maps")
        state = "normal" if active else "disabled"
        for button in (self.quality_button, self.remove_button, self.export_button):
            button.configure(state=state)
        self.quality_button.configure(
            text=(
                "Ratio settings"
                if active and active.get("kind") == "ratio"
                else "Data Quality"
            )
        )
        bands = [r for r in self.records if r.get("kind") != "ratio"]
        compatible = any(
            (a["nx"], a["ny"]) == (b["nx"], b["ny"])
            for i, a in enumerate(bands)
            for b in bands[i + 1 :]
        )
        self.ratio_button.configure(state="normal" if compatible else "disabled")
        if not self.records:
            self.figure.text(
                0.5,
                0.55,
                "Build your first band map",
                ha="center",
                fontsize=16,
                color=PALETTE["text"],
            )
            self.figure.text(
                0.5,
                0.43,
                "Select a spectral interval in Spectrum & Band, then Generate Map.",
                ha="center",
                fontsize=10,
                color=PALETTE["muted"],
            )
        else:
            columns = min(self._columns, len(self.records))
            grid = self.figure.add_gridspec(
                math.ceil(len(self.records) / columns), columns
            )
            for index, r in enumerate(self.records):
                ax = self.figure.add_subplot(grid[index // columns, index % columns])
                is_ratio = r.get("kind") == "ratio"
                limits = (
                    finite_limits(r["area"])
                    if is_ratio
                    else (
                        _imespec_core._limites_exibicao(r["area"])[:2]
                        if r["quality_figure"] is None
                        else r["quality_figure"]._imespec_display_limits
                    )
                )
                cmap = copy.copy(colormaps["cividis" if is_ratio else "viridis"])
                cmap.set_bad(PALETTE["invalid"])
                img = ax.imshow(
                    np.ma.masked_invalid(r["area"]),
                    interpolation="nearest",
                    vmin=limits[0],
                    vmax=limits[1],
                    cmap=cmap,
                )
                ax.set_xlabel("X pixel", fontsize=8)
                ax.set_ylabel("Y pixel", fontsize=8)
                ax.tick_params(labelsize=8)
                self._set_title(ax, r)
                divider = make_axes_locatable(ax)
                color_axis = divider.append_axes("right", size="4.5%", pad=0.09)
                bar = self.figure.colorbar(img, cax=color_axis)
                bar.set_label(
                    "Area ratio (1)" if is_ratio else f"Area ({AREA_UNIT})", fontsize=8
                )
                bar.ax.tick_params(labelsize=7)
                bar.outline.set_edgecolor(PALETTE["border"])
                (marker,) = ax.plot(
                    [],
                    [],
                    marker="+",
                    color="white",
                    markersize=11,
                    mew=2,
                    linestyle="none",
                    visible=False,
                )
                if not np.isfinite(r["area"]).any():
                    ax.text(
                        0.5,
                        0.5,
                        "No valid pixels",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                        fontsize=9,
                        color=PALETTE["muted"],
                    )
                r.update(ax=ax, image=img, marker=marker)
        self._position_map_canvas()
        self._update_markers()
        self._update_summary()
        self.canvas.draw_idle()
        if self._reveal_job is None:
            self._reveal_job = self.after_idle(self._reveal_active_map)

    def _set_title(self, ax, record):
        if record.get("kind") == "ratio":
            a, b = self._spectrum_sources(record)
            subtitle = f"Area ratio · {record['analysis'].summary()['valid_percent']:.2f}% valid"
        else:
            lo, hi = self._band_limits(record)
            subtitle = f"{lo:.1f}–{hi:.1f} cm⁻¹"
        card_width = float(self.scroller.itemcget(self._window, "width")) / max(
            1, self._columns
        )
        title = (
            record["name"] if len(record["name"]) <= 28 else record["name"][:26] + "…"
        )
        subtitle = subtitle if len(subtitle) <= 44 else subtitle[:42] + "…"
        ax.set_title(
            f"{title}\n{subtitle}",
            fontsize=8.5 if card_width < 300 else 10,
            color=record["color"],
            fontweight="bold" if record["id"] == self.active_id else "normal",
        )
        for spine in ax.spines.values():
            spine.set_color(
                record["color"] if record["id"] == self.active_id else PALETTE["border"]
            )
            spine.set_linewidth(1.4 if record["id"] == self.active_id else 0.6)

    def _select_from_list(self, event=None):
        index = self.selector.current()
        if 0 <= index < len(self.records):
            previous = self._record()
            self.active_id = self.records[index]["id"]
            active = self._record()
            if previous is None or (previous["nx"], previous["ny"]) != (
                active["nx"],
                active["ny"],
            ):
                self.selected_cell = None
            self._update_markers()
            self._draw_spectrum()
            self._reveal_active_map()

    def _click_map(self, event):
        if event.button != 1 or event.xdata is None or event.ydata is None:
            return
        for record in self.records:
            if event.inaxes is record.get("ax"):
                row = _imespec_core._pixel_mais_proximo(event.ydata)
                column = _imespec_core._pixel_mais_proximo(event.xdata)
                self.inspect_pixel(
                    record["id"], row, column, open_full=bool(event.dblclick)
                )
                break

    def inspect_pixel(self, map_id, row, column, open_full=False):
        r = self._record(map_id)
        if r is None or not (0 <= row < r["ny"] and 0 <= column < r["nx"]):
            return
        self.active_id = map_id
        self.map_name.set(r["name"])
        self.selected_cell = (int(row), int(column))
        self._update_markers()
        self._draw_spectrum()
        self._draw_maps_controls()
        self.status_callback(
            f"{r['name']} · X={column}, Y={row} · values shown in the table"
        )
        if open_full:
            sources = self._spectrum_sources(r)
            first = sources[0]
            matrix = self.matrix if first["spectra"] is None else first["spectra"]
            number = _imespec_core._indice_espectro(r["nx"], row, column)
            kwargs = {
                "band_indices": (first["start"], first["stop"]),
                "map_name": r["name"],
            }
            if r.get("kind") == "ratio":
                kwargs["bands"] = [
                    {
                        "indices": (b["start"], b["stop"]),
                        "name": b["name"],
                        "color": b["color"],
                    }
                    for b in sources
                ]
                other = sources[1]
                other_matrix = (
                    self.matrix if other["spectra"] is None else other["spectra"]
                )
                if not np.array_equal(matrix[:, number], other_matrix[:, number]):
                    kwargs["extra_spectra"] = [
                        (
                            other_matrix[:, 0],
                            other_matrix[:, number],
                            other["name"],
                            other["color"],
                        )
                    ]
            self.show_spectrum_callback(
                number, matrix[:, 0], matrix[:, number], row, column, **kwargs
            )

    def _update_markers(self):
        active = self._record()
        for record in self.records:
            if "marker" not in record:
                continue
            same_geometry = active and (record["nx"], record["ny"]) == (
                active["nx"],
                active["ny"],
            )
            visible = bool(same_geometry and self.selected_cell is not None)
            record["marker"].set_visible(visible)
            if visible:
                row, column = self.selected_cell
                record["marker"].set_data([column], [row])
            self._set_title(record["ax"], record)
        self.canvas.draw_idle()

    def _draw_spectrum(self):
        if self._closed:
            return
        ax = self.spectrum_ax
        ax.clear()
        ax.set_xlabel("Raman shift (cm⁻¹)", fontsize=9)
        ax.set_ylabel("Raman intensity (a.u.)", fontsize=9)
        ax.tick_params(labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#E5EAF2", linewidth=0.6)
        r = self._record()
        selected = r is not None and self.selected_cell is not None
        self.full_spectrum_button.configure(state="normal" if selected else "disabled")
        if not selected:
            ax.set_title(
                "Click a map to inspect its spectrum",
                fontsize=10,
                color=PALETTE["muted"],
            )
            self.pixel_info.set("No pixel selected")
        else:
            row, column = self.selected_cell
            number = _imespec_core._indice_espectro(r["nx"], row, column)
            sources = self._spectrum_sources(r)
            first = sources[0]
            matrix = self.matrix if first["spectra"] is None else first["spectra"]
            x, y = matrix[:, 0], matrix[:, number]
            ax.plot(x, y, color="#334B6B", linewidth=1.1)
            messages = []
            traces = []
            for index, b in enumerate(sources):
                data = self.matrix if b["spectra"] is None else b["spectra"]
                bx, by = data[:, 0], data[:, number]
                if index and not np.array_equal(y, by):
                    ax.plot(
                        bx,
                        by,
                        color=b["color"],
                        linewidth=0.9,
                        alpha=0.8,
                        label=b["name"] + " spectrum",
                    )
                lo, hi = self._band_limits(b)
                ax.axvspan(lo, hi, color=b["color"], alpha=0.07, label=b["name"])
                if self.show_integration.get():
                    trace = integration_trace(bx, by, b["start"], b["stop"])
                    traces.append(trace)
                    ax.plot(
                        trace["x"],
                        trace["background"],
                        color=b["color"],
                        linestyle="--",
                        linewidth=1.0,
                    )
                    ax.fill_between(
                        trace["x"],
                        trace["background"],
                        trace["y"],
                        color=b["color"],
                        alpha=0.28,
                    )
                    if not np.isclose(
                        trace["area"],
                        float(b["area"][row, column]),
                        rtol=1e-5,
                        atol=1e-6,
                    ):
                        messages.append(b["name"] + ": map-only repair")
            if self.focus_band.get():
                bounds = [self._band_limits(b) for b in sources]
                lo, hi = min(v[0] for v in bounds), max(v[1] for v in bounds)
                margin = max(0.25 * (hi - lo), 3 * float(np.median(np.abs(np.diff(x)))))
                left, right = max(float(x.min()), lo - margin), min(
                    float(x.max()), hi + margin
                )
                ax.set_xlim(left, right)
                ys = []
                for b in sources:
                    m = self.matrix if b["spectra"] is None else b["spectra"]
                    ys.append(m[(m[:, 0] >= left) & (m[:, 0] <= right), number])
                if ys and any(v.size for v in ys):
                    visible = np.concatenate([v for v in ys if v.size])
                    pad = max(float(np.ptp(visible)) * 0.09, 1.0)
                    ax.set_ylim(float(visible.min()) - pad, float(visible.max()) + pad)
            else:
                ax.set_xlim(float(x.min()), float(x.max()))
            ax.set_title(
                (
                    "Local background and integrated area"
                    if self.show_integration.get()
                    else "Pixel spectrum"
                ),
                fontsize=10,
            )
            ax.legend(loc="best", fontsize=7, frameon=False, ncol=min(2, len(sources)))
            if r.get("kind") == "ratio" and not r["analysis"].valid[row, column]:
                messages.append(
                    REASONS[int(r["analysis"].reasons[row, column])].replace("_", " ")
                )
            suffix = " · " + "; ".join(messages) if messages else ""
            self.pixel_info.set(f"X={column} · Y={row} · Spectrum #{number}" + suffix)
        self._sync_band_table()
        self._draw_maps_controls()
        self._fit_spectrum_axes()
        self.spectrum_toolbar.update()
        self.spectrum_canvas.draw_idle()

    def open_quality(self, map_id=None):
        if self._opening_quality:
            return
        record = self._record(map_id)
        if record is None:
            return
        if record.get("kind") == "ratio":
            self.open_ratio_dialog(record["id"])
            return
        if record["quality_figure"] is None:
            self._opening_quality = True
            frame = ttk.Frame(self.quality_notebook, style="Surface.TFrame")
            spectra = self.matrix.copy()
            self.quality_notebook.add(frame, text=f"  {record['name']}  ")
            try:
                view = QualityWorkspace(
                    frame,
                    spectra,
                    record["start"],
                    record["stop"],
                    record["nx"],
                    record["ny"],
                    original_matrix=self.matrix,
                    name=record["name"],
                    dependency_handler=self.dependency_handler,
                    source_path=self.source_path,
                    software_version=self.software_version,
                    on_select=lambda row, col, mid=record["id"]: self.inspect_pixel(
                        mid, row, col, open_full=False
                    ),
                    on_full=lambda row, col, mid=record["id"]: self.inspect_pixel(
                        mid, row, col, open_full=True
                    ),
                )
                figure = view.figure
            except Exception as exc:
                frame.destroy()
                messagebox.showerror(
                    "Map Data Quality", str(exc), parent=self.winfo_toplevel()
                )
                self._opening_quality = False
                return
            record.update(
                spectra=spectra,
                quality_figure=figure,
                quality_frame=frame,
                quality_view=view,
                area=figure._imespec_area,
            )
            record["quality_cid"] = figure.canvas.mpl_connect(
                "draw_event",
                lambda event, mid=record["id"]: self._queue_quality_refresh(mid),
            )
            self._opening_quality = False
        previous = self._record()
        if previous is None or (previous["nx"], previous["ny"]) != (
            record["nx"],
            record["ny"],
        ):
            self.selected_cell = None
        self.active_id = record["id"]
        self.map_name.set(record["name"])
        self._update_markers()
        self._draw_spectrum()
        self.quality_notebook.select(record["quality_frame"])
        self.show_quality_callback()
        self._sync_quality_selector(record["id"])
        self.status_callback(
            f"Data Quality: {record['name']}. Corrections are retained individually for this map."
        )

    def _sync_quality_selector(self, active=None):
        if self.quality_selector is None:
            return
        bands = [r for r in self.records if r.get("kind") != "ratio"]
        self.quality_selector.configure(
            values=[r["name"] for r in bands], state="readonly" if bands else "disabled"
        )
        if not bands:
            self.quality_selector.set("")
        record = self._record(active) if active is not None else self._record()
        if record and record.get("kind") != "ratio":
            self.quality_selector.set(record["name"])

    def open_quality_from_selector(self, event=None):
        if self.quality_selector is None:
            return
        bands = [r for r in self.records if r.get("kind") != "ratio"]
        index = self.quality_selector.current()
        if 0 <= index < len(bands):
            self.open_quality(bands[index]["id"])

    def refresh_map(self, map_id):
        if self._closed:
            return
        r = self._record(map_id)
        if r is None or r.get("kind") == "ratio" or r["quality_figure"] is None:
            return
        r["area"] = r["quality_figure"]._imespec_area
        for other in self.records:
            if other.get("kind") == "ratio" and map_id in (
                other["numerator_id"],
                other["denominator_id"],
            ):
                self._calculate_ratio(other)
        self._draw_maps()
        self._draw_spectrum()

    def remove_active(self):
        record = self._record()
        if record is None:
            return
        dependents = [
            r
            for r in self.records
            if r.get("kind") == "ratio"
            and record["id"] in (r["numerator_id"], r["denominator_id"])
        ]
        detail = ""
        if dependents:
            detail = "\n\nDependent ratios will also be removed:\n" + "\n".join(
                r["name"] for r in dependents
            )
        if not messagebox.askyesno(
            "Remove map",
            f"Remove {record['name']} from this session?" + detail,
            parent=self.winfo_toplevel(),
        ):
            return
        for r in dependents + [record]:
            self._dispose_record(r)
            self.records.remove(r)
        self.active_id = self.records[-1]["id"] if self.records else None
        self.selected_cell = None
        self._apply_layout()
        self._draw_maps()
        self._draw_spectrum()
        self.status_callback(
            f"Removed {record['name']} and {len(dependents)} dependent ratio(s)."
        )
        self._sync_quality_selector()

    def _dispose_record(self, record):
        figure = record.get("quality_figure")
        if figure is not None:
            figure.canvas.mpl_disconnect(record["quality_cid"])
            figure.clear()
        frame = record.get("quality_frame")
        if frame is not None:
            frame.destroy()

    def destroy(self):
        self._closed = True
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        if self._reveal_job is not None:
            self.after_cancel(self._reveal_job)
        if self._ratio_dialog is not None and self._ratio_dialog.winfo_exists():
            self._ratio_dialog.destroy()
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        if self._settle_job is not None:
            self.after_cancel(self._settle_job)
        for record in self.records:
            self._dispose_record(record)
        self.records.clear()
        self.figure.clear()
        self.spectrum_figure.clear()
        super().destroy()

    def _band_limits(self, record):
        return tuple(
            sorted(
                (
                    float(self.matrix[record["start"], 0]),
                    float(self.matrix[record["stop"], 0]),
                )
            )
        )

    def _reveal_active_map(self):
        if self._reveal_job is not None:
            self.after_cancel(self._reveal_job)
            self._reveal_job = None
        active = self._record()
        if self._closed or active is None:
            return
        rows = max(1, math.ceil(len(self.records) / self._columns))
        if rows == 1:
            self.scroller.yview_moveto(0)
            return
        height = self._map_canvas_height()
        row = self.records.index(active) // self._columns
        top = row * height / rows
        bottom = (row + 1) * height / rows
        visible_top = self.scroller.canvasy(0)
        visible_bottom = visible_top + self.scroller.winfo_height()
        if top < visible_top:
            self.scroller.yview_moveto(top / height)
        elif bottom > visible_bottom:
            self.scroller.yview_moveto(
                max(0, (bottom - self.scroller.winfo_height()) / height)
            )

    def _fit_table_columns(self, event=None):
        width = self.band_table.winfo_width() - 6
        if width < 180:
            return
        widths = [int(width * 0.22), int(width * 0.32), int(width * 0.25)]
        widths.append(width - sum(widths))
        for key, value in zip(("band", "range", "area", "unit"), widths):
            self.band_table.column(
                key, width=max(40, value), minwidth=40, stretch=False
            )

    def _spectrum_sources(self, record):
        if record.get("kind") != "ratio":
            return [record]
        return [
            self._record(record["numerator_id"]),
            self._record(record["denominator_id"]),
        ]

    def _draw_maps_controls(self):
        active = self._record()
        self.quality_button.configure(
            text=(
                "Ratio settings"
                if active and active.get("kind") == "ratio"
                else "Data Quality"
            )
        )
        self._update_summary()

    def _update_summary(self):
        r = self._record()
        if r is None:
            self.summary_var.set(
                "Add two bands from this acquisition to create an area ratio."
            )
        elif r.get("kind") == "ratio":
            s = r["analysis"].summary()
            median = "—" if s["median"] is None else f"{s['median']:.4g}"
            self.summary_var.set(
                f"Area ratio · {s['valid_pixels']}/{s['total_pixels']} valid pixels · median {median} · B > {r['analysis'].floor:.4g} {AREA_UNIT}"
            )
        else:
            lo, hi = self._band_limits(r)
            self.summary_var.set(
                f"Integrated area · {lo:.1f}–{hi:.1f} cm⁻¹ · {r['nx']} × {r['ny']} pixels · click to inspect"
            )

    def _queue_quality_refresh(self, map_id):
        if self._closed:
            return
        if not hasattr(self, "_pending_quality_ids"):
            self._pending_quality_ids = set()
        self._pending_quality_ids.add(map_id)
        if self._refresh_job is None:
            self._refresh_job = self.after_idle(self._flush_quality_refresh)

    def _flush_quality_refresh(self):
        self._refresh_job = None
        pending = list(self._pending_quality_ids)
        self._pending_quality_ids.clear()
        for map_id in pending:
            self.refresh_map(map_id)

    def _calculate_ratio(self, record):
        a, b = self._spectrum_sources(record)
        result = area_ratio(a["area"], b["area"], **record["ratio_parameters"])
        record.update(analysis=result, area=result.values)
        return result

    def add_ratio(
        self,
        name,
        numerator_id,
        denominator_id,
        *,
        absolute_floor=0.0,
        relative_floor_percent=1.0,
        exclude_negative_numerator=True,
        record_id=None,
    ):
        a, b = self._record(numerator_id), self._record(denominator_id)
        if (
            a is None
            or b is None
            or a.get("kind") == "ratio"
            or b.get("kind") == "ratio"
        ):
            raise ValueError(
                "Select two existing band-area maps from this acquisition."
            )
        if a["id"] == b["id"]:
            raise ValueError("Choose a different band map for A and B.")
        if (a["nx"], a["ny"]) != (b["nx"], b["ny"]):
            raise ValueError(
                "Both maps must have exactly the same acquisition geometry."
            )
        parameters = {
            "absolute_floor": float(absolute_floor),
            "relative_floor_percent": float(relative_floor_percent),
            "exclude_negative_numerator": bool(exclude_negative_numerator),
        }
        result = area_ratio(a["area"], b["area"], **parameters)
        title = str(name).strip()[:60] or f"{a['name']} / {b['name']}"[:60]
        existing = self._record(record_id) if record_id is not None else None
        if existing is not None and existing.get("kind") != "ratio":
            raise ValueError("Only a ratio map can be edited here.")
        others = {r["name"] for r in self.records if r is not existing}
        base = title
        suffix = 2
        while title in others:
            title = f"{base} ({suffix})"
            suffix += 1
        record = existing or {
            "id": self._next_id,
            "color": "#0D877A",
            "spectra": None,
            "quality_figure": None,
            "quality_frame": None,
            "kind": "ratio",
        }
        record.update(
            name=title,
            numerator_id=a["id"],
            denominator_id=b["id"],
            nx=a["nx"],
            ny=a["ny"],
            ratio_parameters=parameters,
            analysis=result,
            area=result.values,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        if existing is None:
            self.records.append(record)
            self._next_id += 1
        self.active_id = record["id"]
        if self.selected_cell is not None and not (
            0 <= self.selected_cell[0] < record["ny"]
            and 0 <= self.selected_cell[1] < record["nx"]
        ):
            self.selected_cell = None
        self._sash_initialized = False
        self._apply_layout()
        self._resize_maps()
        self._draw_maps()
        self._draw_spectrum()
        self.status_callback(
            f"{title} · area ratio created · {result.summary()['valid_pixels']}/{result.values.size} valid pixels"
        )
        return record

    def open_ratio_dialog(self, record_id=None):
        if self._ratio_dialog is not None and self._ratio_dialog.winfo_exists():
            self._ratio_dialog.lift()
            self._ratio_dialog.focus_force()
            return
        bands = [r for r in self.records if r.get("kind") != "ratio"]
        if len(bands) < 2:
            return
        record = self._record(record_id) if record_id is not None else None
        dialog = tk.Toplevel(self.winfo_toplevel())
        self._ratio_dialog = dialog
        dialog.title("Area ratio · A / B")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        body = ttk.Frame(
            dialog, padding=24, style="Surface.TFrame", borderwidth=1, relief="solid"
        )
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Ratio between band areas", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            body,
            text="Divide corresponding pixels from the same acquisition.\nThe original band maps are preserved.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 18))
        names = [r["name"] for r in bands]
        active = self._record()
        a = next(
            (r for r in bands if record and r["id"] == record["numerator_id"]),
            active if active in bands else bands[0],
        )
        b = next(
            (r for r in bands if record and r["id"] == record["denominator_id"]),
            next(r for r in bands if r is not a),
        )
        av, bv = tk.StringVar(value=a["name"]), tk.StringVar(value=b["name"])
        title = tk.StringVar(
            value=record["name"] if record else f"{a['name']} / {b['name']}"
        )
        auto_name = [f"{a['name']} / {b['name']}"]
        params = (
            record["ratio_parameters"]
            if record
            else {
                "absolute_floor": 0.0,
                "relative_floor_percent": 1.0,
                "exclude_negative_numerator": True,
            }
        )
        absolute = tk.StringVar(value=f"{params['absolute_floor']:g}")
        relative = tk.StringVar(value=f"{params['relative_floor_percent']:g}")
        exclude = tk.BooleanVar(value=params["exclude_negative_numerator"])
        for row, label, var in [(2, "Numerator · A", av), (3, "Denominator · B", bv)]:
            ttk.Label(body, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 18), pady=5
            )
            ttk.Combobox(
                body, textvariable=var, values=names, state="readonly", width=32
            ).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(body, text="Map name").grid(row=4, column=0, sticky="w", pady=(5, 16))
        name_entry = ttk.Entry(body, textvariable=title, width=34)
        name_entry.grid(row=4, column=1, sticky="ew", pady=(5, 16))
        ttk.Separator(body).grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(body, text="Reference validity", style="Section.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        ttk.Label(body, text="Minimum B area (" + AREA_UNIT + ")").grid(
            row=7, column=0, sticky="w", padx=(0, 18), pady=5
        )
        ttk.Entry(body, textvariable=absolute, width=16).grid(
            row=7, column=1, sticky="w", pady=5
        )
        ttk.Label(body, text="Floor (% of median positive B)").grid(
            row=8, column=0, sticky="w", padx=(0, 18), pady=5
        )
        ttk.Entry(body, textvariable=relative, width=16).grid(
            row=8, column=1, sticky="w", pady=5
        )
        ttk.Checkbutton(
            body, text="Exclude negative numerator areas", variable=exclude
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 4))
        ttk.Label(
            body,
            text="B must exceed both limits. The 1% default is an editable\nreference-floor rule, not a noise or SNR estimate.\nExcluded pixels appear gray; no epsilon is added.",
            style="Caption.TLabel",
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(4, 12))
        preview = tk.StringVar()
        ttk.Label(
            body, textvariable=preview, style="Caption.TLabel", wraplength=470
        ).grid(row=11, column=0, columnspan=2, sticky="w")
        footer = ttk.Frame(body)
        footer.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        footer.columnconfigure(0, weight=1)

        def close():
            self._ratio_dialog = None
            dialog.destroy()

        def arguments():
            ar = next(
                (r for r in bands if r["name"] == av.get() and r in self.records), None
            )
            br = next(
                (r for r in bands if r["name"] == bv.get() and r in self.records), None
            )
            if ar is None or br is None:
                raise ValueError("A source map was removed. Reopen this dialog.")
            if ar is br:
                raise ValueError("A and B must be different maps.")
            if (ar["nx"], ar["ny"]) != (br["nx"], br["ny"]):
                raise ValueError("A and B must have the same geometry.")
            return (
                ar,
                br,
                {
                    "absolute_floor": float(absolute.get().replace(",", ".")),
                    "relative_floor_percent": float(relative.get().replace(",", ".")),
                    "exclude_negative_numerator": exclude.get(),
                },
            )

        def update(*args):
            proposed = f"{av.get()} / {bv.get()}"
            if title.get() == auto_name[0]:
                title.set(proposed)
            auto_name[0] = proposed
            try:
                ar, br, p = arguments()
                result = area_ratio(ar["area"], br["area"], **p)
                preview.set(
                    f"Preview: {result.summary()['valid_pixels']}/{result.values.size} valid pixels · effective B floor {result.floor:.6g} {AREA_UNIT}"
                )
                save.configure(state="normal")
            except ValueError as exc:
                preview.set(str(exc))
                save.configure(state="disabled")

        def commit():
            try:
                ar, br, p = arguments()
                self.add_ratio(
                    title.get(), ar["id"], br["id"], record_id=record_id, **p
                )
            except ValueError as exc:
                preview.set(str(exc))
                return
            close()

        ttk.Button(footer, text="Cancel", command=close).grid(
            row=0, column=1, padx=(0, 8)
        )
        save = ttk.Button(
            footer,
            text="Update ratio" if record else "Create ratio",
            style="Accent.TButton",
            command=commit,
        )
        save.grid(row=0, column=2)
        for var in (av, bv, absolute, relative, exclude):
            var.trace_add("write", update)
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda event: close())
        dialog.bind(
            "<Return>",
            lambda event: commit() if str(save["state"]) != "disabled" else None,
        )
        update()
        dialog.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(
            0, (root.winfo_width() - dialog.winfo_reqwidth()) // 2
        )
        y = root.winfo_rooty() + max(
            0, (root.winfo_height() - dialog.winfo_reqheight()) // 2
        )
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        name_entry.focus_set()
        return dialog

    def _export_metadata(self, record):
        def band_info(b):
            lo, hi = self._band_limits(b)
            data = self.matrix if b["spectra"] is None else b["spectra"]
            return {
                "id": b["id"],
                "name": b["name"],
                "band_cm-1": [lo, hi],
                "inclusive_sample_indices": [int(b["start"]), int(b["stop"])],
                "current_area_sha256": array_hash(b["area"]),
                "current_spectra_sha256": array_hash(data),
                "spectra_modified": array_hash(data) != self.loaded_matrix_hash,
                "quality_editor_opened": b["quality_figure"] is not None,
            }

        result = {
            "schema": "IMESPEC Map Analysis",
            "schema_version": 1,
            "software_version": self.software_version,
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_file": Path(self.source_path).name if self.source_path else None,
            "loaded_matrix_sha256": self.loaded_matrix_hash,
            "name": record["name"],
            "kind": record.get("kind", "band"),
            "geometry": {
                "nx": record["nx"],
                "ny": record["ny"],
                "spatial_unit": "pixel",
                "spectra_available": int(self.matrix.shape[1] - 1),
                "spectra_used": int(record["nx"] * record["ny"]),
                "spectra_outside_complete_rows": int(
                    self.matrix.shape[1] - 1 - record["nx"] * record["ny"]
                ),
                "spectrum_index": "1 + y * nx + x",
            },
            "integration": {
                "method": "trapezoidal signed area after local linear background subtraction",
                "left_anchor": "mean of samples start-2 through start, inclusive",
                "right_anchor": "mean of samples stop through stop+2, inclusive",
                "area_unit": "a.u. * cm^-1",
            },
            "notes": [
                "Ratios use current map areas, including any reviewed map-only pixel repairs.",
                "A map-only repair may differ from the area shown by the underlying spectrum.",
                "Display colors and limits do not alter numerical results.",
                "No spatial calibration is inferred from a spectrum count.",
            ],
        }
        if record.get("kind") == "ratio":
            a, b = self._spectrum_sources(record)
            result.update(
                unit="1",
                operation="numerator_area / denominator_area at corresponding pixels",
                numerator=band_info(a),
                denominator=band_info(b),
                parameters=record["ratio_parameters"],
                statistics=record["analysis"].summary(),
                validity_rule="finite A and B; B > max(absolute_floor, relative_floor_percent/100 * median(positive finite B)); optional A >= 0; finite quotient",
                reason_codes=REASONS,
                threshold_note="The relative floor is a user-selected heuristic, not an estimated noise threshold.",
            )
        else:
            result.update(unit="a.u. * cm^-1", band=band_info(record))
        return result

    def export_analysis(self, path, map_id=None):
        r = self._record(map_id)
        if r is None:
            raise ValueError("Select a map first.")
        if r.get("kind") == "ratio":
            self._calculate_ratio(r)
        metadata = self._export_metadata(r)
        data = io.StringIO(newline="")
        writer = csv.writer(data)
        ratio = r.get("kind") == "ratio"
        writer.writerow(
            [
                "x_pixel",
                "y_pixel",
                "ratio",
                "valid",
                "reason",
                "numerator_area",
                "denominator_area",
            ]
            if ratio
            else ["x_pixel", "y_pixel", "area_au_cm-1", "valid"]
        )
        sources = self._spectrum_sources(r)
        for y in range(r["ny"]):
            for x in range(r["nx"]):
                value = float(r["area"][y, x])
                valid = bool(np.isfinite(value))
                if ratio:
                    reason = REASONS[int(r["analysis"].reasons[y, x])]
                    av, bv = float(sources[0]["area"][y, x]), float(
                        sources[1]["area"][y, x]
                    )
                    writer.writerow(
                        [
                            x,
                            y,
                            value if valid else "",
                            int(valid),
                            reason,
                            av if np.isfinite(av) else "",
                            bv if np.isfinite(bv) else "",
                        ]
                    )
                else:
                    writer.writerow([x, y, value if valid else "", int(valid)])
        fig = Figure(figsize=(6.5, 5.2), dpi=160, facecolor="white")
        ax = fig.add_subplot(111)
        cmap = copy.copy(colormaps["cividis" if ratio else "viridis"])
        cmap.set_bad(PALETTE["invalid"])
        lo, hi = finite_limits(r["area"])
        metadata["display"] = {
            "limits": [lo, hi],
            "colormap": "cividis" if ratio else "viridis",
            "excluded_pixel_color": PALETTE["invalid"],
            "origin": "upper",
            "aspect": "equal",
        }
        image = ax.imshow(
            np.ma.masked_invalid(r["area"]),
            cmap=cmap,
            vmin=lo,
            vmax=hi,
            interpolation="nearest",
        )
        ax.set_xlabel("X pixel")
        ax.set_ylabel("Y pixel")
        ax.set_title(r["name"])
        fig.colorbar(
            image,
            ax=ax,
            label="Area ratio (dimensionless)" if ratio else f"Band area ({AREA_UNIT})",
        )
        fig.tight_layout()
        png = io.BytesIO()
        fig.savefig(png, format="png", dpi=160)
        fig.clear()
        readme = (
            "IMESPEC MAP ANALYSIS\n"
            "map.csv contains unscaled numerical values at X/Y pixel positions.\n"
            "metadata.json records source hashes, bands, calculation and validity parameters.\n"
            "map.png is a visualization; colors are not used for numerical analysis.\n"
            "For ratios, blank values mean excluded pixels; valid=0 and reason explain why.\n"
            "Numerator and denominator areas are included to reproduce every valid ratio.\n"
            "Spatial axes are pixels because no physical calibration was supplied.\n"
        )
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, suffix=".tmp", delete=False
            ) as temp:
                temporary = Path(temp.name)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr("map.csv", data.getvalue())
                z.writestr(
                    "metadata.json",
                    json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False),
                )
                z.writestr("map.png", png.getvalue())
                z.writestr("README.txt", readme)
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return metadata

    def export_selected(self):
        r = self._record()
        if r is None:
            return
        safe = re.sub(r"[^\w. -]+", "_", r["name"]).strip(" .") or "raman_map"
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title="Export map analysis",
            initialfile=safe + ".zip",
            defaultextension=".zip",
            filetypes=[("Map analysis package", "*.zip")],
        )
        if not path:
            return
        try:
            self.export_analysis(path)
        except Exception as exc:
            messagebox.showerror(
                "Export failed", str(exc), parent=self.winfo_toplevel()
            )
            return
        self.status_callback(
            "Exported "
            + Path(path).name
            + " · numerical CSV, analysis JSON and map PNG"
        )
