"""
IMESPEC — Raman Analysis Suite
Projeto de iniciação científica de Kauan.

A ideia aqui é manter a análise científica separada da interface: o programa
sugere um fluxo inicial a partir dos dados, mas só altera resultados quando o
usuário confirma uma etapa. Assim o modo automático ajuda sem esconder o que
foi feito.
"""

__author__ = "Kauan"
import numpy as np
import matplotlib.pyplot as plt
import imespec_bib1 as _imespec_core
from imespec_maps import RamanMapCollection
from imespec_theme import PALETTE, apply_theme
import importlib
import importlib.util
from importlib import metadata as importlib_metadata
import queue
import subprocess
import sys
import threading
from matplotlib.widgets import SpanSelector, Slider, Button, TextBox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from imespec_bib1 import (
    carregar_multiespectros,
    copiar_multiespectros,
    distribuir,
    faixa_comum_multiespectros,
    fazer_imagem,
    ler_espectro_texto,
    ordenar_caminhos_natural,
    pedir_geometria_mapa,
    refresh_optional_dependencies,
    sugerir_banda_raman_mapa,
    sugerir_x_referencia_multiespectros,
)
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from tkinter import filedialog as fd
from tkinter import messagebox
from tkinter import simpledialog
import math
import os
import csv
import json

# ============================================================
# CONFIGURAÇÕES GERAIS
# ============================================================
pasta_programa = os.path.dirname(os.path.abspath(__file__))
pasta_estado = os.path.join(
    os.environ.get("LOCALAPPDATA")
    or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "IMESPEC",
)
os.makedirs(pasta_estado, exist_ok=True)
arquivo_memoria = os.path.join(pasta_estado, "ultimo_arquivo.txt")
IMESPEC_VERSION = "1.4.1"
IMESPEC_EDITION = "Raman Analysis Workspace"
_LEGACY_CHILD = os.environ.get("IMESPEC_LEGACY_CHILD") == "1"
_MODERN_RETURN_CODE = 0


def _retornar_moderno(module="home"):
    global _MODERN_RETURN_CODE
    _MODERN_RETURN_CODE = 42 if module == "multi" else 43
    janela.destroy()


# ============================================================
# DEPENDENCY / ENVIRONMENT MANAGER
# ============================================================
DEPENDENCIAS_IMESPEC = {
    "numpy": {
        "distribution": "numpy",
        "import_name": "numpy",
        "role": "Core numerical arrays and calculations",
        "startup": True,
    },
    "matplotlib": {
        "distribution": "matplotlib",
        "import_name": "matplotlib",
        "role": "Plots, Raman maps and interactive figures",
        "startup": True,
    },
    "scipy": {
        "distribution": "scipy",
        "import_name": "scipy",
        "role": "Cosmic Ray Removal, faster arPLS and MATLAB export",
        "startup": False,
    },
    "h5py": {
        "distribution": "h5py",
        "import_name": "h5py",
        "role": "HDF5 scientific export for Raman maps and Multi-Spectra",
        "startup": False,
    },
    "openpyxl": {
        "distribution": "openpyxl",
        "import_name": "openpyxl",
        "role": "Excel XLSX export",
        "startup": False,
    },
    "SPyC_Writer": {
        "distribution": "SPyC_Writer",
        "import_name": "SPyC_Writer",
        "role": "Galactic/Thermo SPC spectroscopy export",
        "startup": False,
    },
}


def _dependency_version(distribution):
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _dependency_importable(package):
    info = DEPENDENCIAS_IMESPEC[package]
    importlib.invalidate_caches()
    try:
        found = importlib.util.find_spec(info["import_name"]) is not None
    except Exception:
        found = False
    if package == "scipy" and found:
        # Refresh the references held by imespec_bib1. This matters when SciPy
        # was installed while IMESPEC was already open.
        found = bool(refresh_optional_dependencies())
    return bool(found)


def _dependency_snapshot(package):
    info = DEPENDENCIAS_IMESPEC[package]
    installed = _dependency_importable(package)
    version = _dependency_version(info["distribution"]) if installed else None
    return {
        "installed": installed,
        "version": version,
        "role": info["role"],
        "distribution": info["distribution"],
    }


def atualizar_indicador_dependencias():
    """Refresh the launcher indicator, separating required and optional packages."""
    try:
        required_missing = []
        optional_missing = []
        for package, info in DEPENDENCIAS_IMESPEC.items():
            if _dependency_importable(package):
                continue
            if info.get("startup"):
                required_missing.append(package)
            else:
                optional_missing.append(package)
        if required_missing:
            texto = "Environment ⚠ required missing: " + ", ".join(required_missing)
        elif optional_missing:
            texto = "Environment ✓ core ready · optional tools available on demand"
        else:
            texto = "Environment ✓ all dependencies available"
        dependencias_status_var.set(texto)
    except Exception:
        # The indicator may be called before its StringVar exists.
        pass


def abrir_gerenciador_dependencias(foco=None, recurso=None, parent=None):
    """
    Show an organized dependency panel and allow one-click installation.

    pip is executed through ``sys.executable -m pip`` so the package is
    installed into the same Python / virtual environment that is running
    IMESPEC, avoiding the common "installed in the wrong interpreter" problem.
    Installation runs in a worker thread and the Tk interface remains usable.
    """
    if parent is None:
        parent = globals().get("janela")
    if parent is None:
        return
    win = tk.Toplevel(parent)
    win.title("IMESPEC — Dependencies")
    win.geometry("850x585")
    win.minsize(760, 520)
    win.transient(parent)
    root = ttk.Frame(win, padding=16)
    root.pack(fill="both", expand=True)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(5, weight=1)
    ttk.Label(
        root, text="Environment / Dependencies", font=("TkDefaultFont", 15, "bold")
    ).grid(row=0, column=0, sticky="w")
    explanation = (
        "IMESPEC checks feature dependencies before using them. "
        "Missing packages can be installed into the active Python environment from here."
    )
    if getattr(sys, "frozen", False):
        explanation = (
            "This installed edition includes the dependencies required for Raman maps and spectra. "
            "Additional optional export formats require an installer built with those packages."
        )
    if recurso:
        explanation += f"\n\nRequested feature: {recurso}"
    ttk.Label(
        root, text=explanation, wraplength=790, justify="left", foreground="#555555"
    ).grid(row=1, column=0, sticky="ew", pady=(5, 8))
    ttk.Label(
        root,
        text=f"Active Python: {sys.executable}",
        wraplength=790,
        justify="left",
        foreground="#666666",
    ).grid(row=2, column=0, sticky="ew", pady=(0, 10))
    table = ttk.Frame(root)
    table.grid(row=3, column=0, sticky="ew")
    table.columnconfigure(2, weight=1)
    ttk.Label(table, text="Package", font=("TkDefaultFont", 9, "bold")).grid(
        row=0, column=0, sticky="w", padx=(0, 12)
    )
    ttk.Label(table, text="Status", font=("TkDefaultFont", 9, "bold")).grid(
        row=0, column=1, sticky="w", padx=(0, 12)
    )
    ttk.Label(table, text="Used by", font=("TkDefaultFont", 9, "bold")).grid(
        row=0, column=2, sticky="w", padx=(0, 12)
    )
    row_widgets = {}
    install_buttons = {}
    install_queue = queue.Queue()
    installing = {"package": None}
    for row_index, package in enumerate(DEPENDENCIAS_IMESPEC, start=1):
        info = DEPENDENCIAS_IMESPEC[package]
        name_text = info["distribution"]
        if package == foco:
            name_text += "  ← required now"
        ttk.Label(table, text=name_text).grid(
            row=row_index, column=0, sticky="w", padx=(0, 12), pady=4
        )
        status_var = tk.StringVar()
        status_label = ttk.Label(table, textvariable=status_var)
        status_label.grid(row=row_index, column=1, sticky="w", padx=(0, 12), pady=4)
        ttk.Label(table, text=info["role"], wraplength=410, justify="left").grid(
            row=row_index, column=2, sticky="w", padx=(0, 12), pady=4
        )
        button = ttk.Button(table, text="Install", width=12)
        button.grid(row=row_index, column=3, sticky="e", pady=4)
        row_widgets[package] = status_var
        install_buttons[package] = button
    ttk.Separator(root, orient="horizontal").grid(
        row=4, column=0, sticky="ew", pady=(12, 8)
    )
    log_frame = ttk.LabelFrame(root, text="Installation details", padding=8)
    log_frame.grid(row=5, column=0, sticky="nsew")
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    log = tk.Text(log_frame, height=9, wrap="word", state="disabled")
    log.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    log.configure(yscrollcommand=scroll.set)
    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.grid(row=6, column=0, sticky="ew", pady=(8, 0))
    footer = ttk.Frame(root)
    footer.grid(row=7, column=0, sticky="ew", pady=(10, 0))
    footer.columnconfigure(0, weight=1)
    footer_status = tk.StringVar(value="Ready.")
    ttk.Label(footer, textvariable=footer_status, foreground="#555555").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Button(footer, text="Close", command=win.destroy).grid(
        row=0, column=2, sticky="e", padx=(6, 0)
    )

    def append_log(text):
        log.configure(state="normal")
        log.insert("end", text)
        log.see("end")
        log.configure(state="disabled")

    def refresh_rows():
        for package in DEPENDENCIAS_IMESPEC:
            snap = _dependency_snapshot(package)
            if snap["installed"]:
                version_text = f" {snap['version']}" if snap["version"] else ""
                row_widgets[package].set("✓ Installed" + version_text)
                install_buttons[package].configure(state="disabled", text="Installed")
            else:
                row_widgets[package].set("⚠ Missing")
                frozen = getattr(sys, "frozen", False)
                state = "disabled" if installing["package"] or frozen else "normal"
                install_buttons[package].configure(
                    state=state, text="Not bundled" if frozen else "Install"
                )
        atualizar_indicador_dependencias()

    def set_install_buttons(enabled):
        for package, button in install_buttons.items():
            if _dependency_importable(package):
                button.configure(state="disabled")
            else:
                button.configure(state="normal" if enabled else "disabled")

    def installation_worker(package):
        distribution = DEPENDENCIAS_IMESPEC[package]["distribution"]
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--prefer-binary",
            distribution,
        ]
        install_queue.put(("log", "\n$ " + " ".join(command) + "\n"))
        try:
            creationflags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            if process.stdout is not None:
                for line in process.stdout:
                    install_queue.put(("log", line))
            return_code = process.wait()
            install_queue.put(("done", package, return_code, None))
        except Exception as exc:
            install_queue.put(("done", package, -1, str(exc)))

    def poll_install_queue():
        done = False
        try:
            while True:
                item = install_queue.get_nowait()
                if item[0] == "log":
                    append_log(item[1])
                    continue
                _, package, return_code, error = item
                done = True
                progress.stop()
                installing["package"] = None
                importlib.invalidate_caches()
                if package == "scipy":
                    refresh_optional_dependencies()
                refresh_rows()
                set_install_buttons(True)
                if return_code == 0 and _dependency_importable(package):
                    footer_status.set(
                        f"{package} installed successfully and is available now."
                    )
                    append_log(
                        f"\n✓ {package} is available in the active environment.\n"
                    )
                elif return_code == 0:
                    footer_status.set(
                        f"{package} installation finished. Restart IMESPEC if it is not detected yet."
                    )
                    append_log(
                        "\nInstallation finished, but the package could not be imported in this process. "
                        "A restart may be required.\n"
                    )
                else:
                    footer_status.set(f"Could not install {package}.")
                    details = error or "See the installation log above."
                    messagebox.showerror(
                        "Dependency Installation",
                        f"Could not install {package}.\n\n{details}\n\n"
                        "You can copy the command shown in Installation details and run it in the PyCharm Terminal.",
                        parent=win,
                    )
        except queue.Empty:
            pass
        if not done and installing["package"]:
            win.after(100, poll_install_queue)

    def install_package(package):
        if getattr(sys, "frozen", False):
            messagebox.showinfo(
                "Installed edition",
                "Optional packages are included when building IMESPEC. "
                "Use an updated installer to add an optional package.",
                parent=win,
            )
            return
        if installing["package"]:
            return
        if _dependency_importable(package):
            refresh_rows()
            return
        installing["package"] = package
        footer_status.set(f"Installing {package}... Keep IMESPEC open.")
        set_install_buttons(False)
        progress.start(12)
        threading.Thread(
            target=installation_worker,
            args=(package,),
            daemon=True,
        ).start()
        win.after(100, poll_install_queue)

    for package, button in install_buttons.items():
        button.configure(command=lambda p=package: install_package(p))
    ttk.Button(footer, text="Check Again", command=refresh_rows).grid(
        row=0, column=1, sticky="e"
    )
    refresh_rows()
    win.protocol("WM_DELETE_WINDOW", win.destroy)


def garantir_dependencia(package, recurso, parent=None):
    """Return True if available; otherwise open the organized installer."""
    if package not in DEPENDENCIAS_IMESPEC:
        raise ValueError(f"Unknown dependency: {package}")
    if _dependency_importable(package):
        return True
    abrir_gerenciador_dependencias(foco=package, recurso=recurso, parent=parent)
    return False


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================


def atualizar_status(texto):
    status_var.set(texto)


def _validar_eixo_raman(x):
    """Validate a finite strictly monotonic Raman-shift axis."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.size < 2:
        raise ValueError("The Raman-shift axis must contain at least two points.")
    if not np.all(np.isfinite(x)):
        raise ValueError("The Raman-shift axis contains non-finite values.")
    dx = np.diff(x)
    if np.all(dx > 0):
        return "ascending"
    if np.all(dx < 0):
        return "descending"
    raise ValueError(
        "The Raman-shift axis must be strictly monotonic. "
        "Repeated or unordered Raman-shift values are not supported."
    )


def _indices_intervalo_raman(x, xmin, xmax):
    """
    Return inclusive sample indices inside a selected Raman-shift interval.

    Unlike ``np.searchsorted``, this works for both ascending and descending
    Raman axes and avoids the previous off-by-one mismatch between the preview
    and the integrated map.
    """
    x = np.asarray(x, dtype=float)
    _validar_eixo_raman(x)
    lo, hi = sorted((float(xmin), float(xmax)))
    indices = np.flatnonzero((x >= lo) & (x <= hi))
    if indices.size < 2:
        return None
    return int(indices.min()), int(indices.max())


# ============================================================
# SINGLE-WINDOW WORKSPACE / PROFESSIONAL SHELL
# ============================================================


class EmbeddedWindow(ttk.Frame):
    """
    Compatibility host for modules that used to live in ``tk.Toplevel``.

    The scientific modules can keep their mature internal logic while their
    main workspace is docked inside the single IMESPEC application window.
    Short-lived configuration/export dialogs may still use modal dialogs,
    which is standard desktop-application behavior.
    """

    def __init__(self, master, module_id, title, subtitle=""):
        super().__init__(master, style="Workspace.TFrame")
        self.module_id = str(module_id)
        self._title_text = str(title)
        self._subtitle_text = str(subtitle)
        self.pack(fill="both", expand=True)
        # The global top bar owns the workspace title. Keeping module content
        # header-free avoids the duplicated "window inside a window" look.
        self._title_var = tk.StringVar(value=self._title_text)

    # Toplevel-compatible methods used by the legacy module builders.
    def title(self, value=None):
        if value is None:
            return self._title_text
        value = str(value)
        self._title_text = value
        cleaned = value.replace("IMESPEC — ", "").replace("IMESPEC - ", "")
        self._title_var.set(cleaned)
        try:
            workspace_title_var.set(cleaned)
        except Exception:
            pass

    def geometry(self, *args, **kwargs):
        return None

    def minsize(self, *args, **kwargs):
        return None

    def transient(self, *args, **kwargs):
        return None

    def resizable(self, *args, **kwargs):
        return None

    def grab_set(self, *args, **kwargs):
        return None

    def protocol(self, *args, **kwargs):
        return None

    def _really_destroy(self):
        try:
            super().destroy()
        except Exception:
            pass

    def destroy(self):
        # Closing a module returns to the dashboard instead of closing the app.
        mostrar_home()


def _limpar_workspace():
    host = globals().get("workspace_content")
    if host is None:
        return
    for child in list(host.winfo_children()):
        if isinstance(child, EmbeddedWindow):
            child._really_destroy()
        else:
            try:
                child.destroy()
            except Exception:
                pass


def _set_nav_active(module_id):
    for key, button in globals().get("nav_buttons", {}).items():
        try:
            if key == module_id:
                button.configure(
                    bg=PALETTE["sidebar_active"],
                    activebackground=PALETTE["sidebar_active"],
                    fg="white",
                    activeforeground="white",
                )
            else:
                button.configure(
                    bg=PALETTE["sidebar"],
                    activebackground=PALETTE["sidebar_hover"],
                    fg="#DCE6F2",
                    activeforeground="white",
                )
        except Exception:
            pass


def criar_workspace_module(module_id, title, subtitle=""):
    _limpar_workspace()
    _set_nav_active(module_id)
    try:
        workspace_title_var.set(title)
        workspace_context_var.set(subtitle or "Scientific analysis workspace")
    except Exception:
        pass
    atualizar_status(f"Opened {title} workspace.")
    return EmbeddedWindow(workspace_content, module_id, title, subtitle)


def criar_painel_rolavel(master, width=385, title=None, subtitle=None):
    """Painel lateral reutilizado nos módulos com muitas configurações."""
    container = ttk.Frame(master, width=width)
    container.grid_propagate(False)
    container.columnconfigure(0, weight=1)
    row_canvas = 0
    if title:
        head = ttk.Frame(container, padding=(8, 2, 8, 7))
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(head, text=title, font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        if subtitle:
            ttk.Label(head, text=subtitle, foreground="#666666").pack(
                anchor="w", pady=(2, 0)
            )
        row_canvas = 1
    container.rowconfigure(row_canvas, weight=1)
    canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0, width=width - 25)
    canvas.grid(row=row_canvas, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scroll.grid(row=row_canvas, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scroll.set)
    panel = ttk.Frame(canvas, padding=(8, 4))
    item = canvas.create_window((0, 0), window=panel, anchor="nw")
    panel.bind(
        "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))

    def wheel(event):
        step = (
            int(-event.delta / 120)
            if getattr(event, "delta", 0)
            else (-1 if getattr(event, "num", None) == 4 else 1)
        )
        canvas.yview_scroll(step, "units")

    def wheel_on(_):
        canvas.bind_all("<MouseWheel>", wheel)
        canvas.bind_all("<Button-4>", wheel)
        canvas.bind_all("<Button-5>", wheel)

    def wheel_off(_):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    for widget in (canvas, panel):
        widget.bind("<Enter>", wheel_on)
        widget.bind("<Leave>", wheel_off)
    return container, panel


def _dashboard_card(parent, column, title, description, action_text, command, badge):
    card = tk.Frame(
        parent,
        bg=PALETTE["surface"],
        highlightbackground=PALETTE["border"],
        highlightthickness=1,
        bd=0,
        padx=26,
        pady=26,
    )
    card.grid(
        row=0, column=column, sticky="nsew", padx=(0, 10) if column == 0 else (10, 0)
    )
    parent.columnconfigure(column, weight=1, uniform="cards")
    mark = tk.Canvas(card, width=42, height=42, bg="#EDF3FF", highlightthickness=0)
    mark.pack(anchor="w")
    if column == 0:
        for y in range(3):
            for x in range(3):
                color = ["#BBD2FF", "#7DA6F7", "#2463EB"][(x + y) % 3]
                mark.create_rectangle(
                    8 + x * 9, 8 + y * 9, 14 + x * 9, 14 + y * 9, fill=color, outline=""
                )
    else:
        for y in (12, 21, 30):
            mark.create_line(
                7, y, 15, y, 20, y - 5, 24, y, 35, y, fill=PALETTE["primary"], width=2
            )
    tk.Label(
        card,
        text=title,
        bg="white",
        fg=PALETTE["text"],
        font=(UI_FONT, 19, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(20, 10))
    description_label = tk.Label(
        card,
        text=description,
        bg="white",
        fg=PALETTE["muted"],
        font=(UI_FONT, 11),
        justify="left",
        wraplength=390,
        anchor="nw",
    )
    description_label.pack(fill="both", expand=True)
    card.bind(
        "<Configure>",
        lambda event: description_label.configure(
            wraplength=max(200, event.width - 55)
        ),
    )
    tk.Label(
        card,
        text="SPATIAL ANALYSIS" if column == 0 else "MEASUREMENT SERIES",
        bg="white",
        fg=PALETTE["muted"],
        font=(UI_FONT, 9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(20, 12))
    ttk.Button(
        card,
        text=action_text,
        style="Accent.TButton" if column == 0 else "TButton",
        command=command,
    ).pack(anchor="w")
    return card


def mostrar_home():
    if _LEGACY_CHILD:
        _retornar_moderno("home")
        return
    host = globals().get("workspace_content")
    if host is None:
        return
    _limpar_workspace()
    _set_nav_active("home")
    workspace_title_var.set("Home")
    workspace_context_var.set("Choose a workspace for your Raman data")
    page = ttk.Frame(host, style="Workspace.TFrame", padding=(30, 26))
    page.pack(fill="both", expand=True)
    hero = tk.Frame(page, bg=PALETTE["app_bg"])
    hero.pack(fill="x", pady=(0, 26))
    tk.Label(
        hero,
        text="YOUR ANALYSIS WORKSPACE",
        bg=PALETTE["app_bg"],
        fg=PALETTE["primary"],
        font=(UI_FONT, 9, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        hero,
        text="From spectra to spatial insight.",
        bg=PALETTE["app_bg"],
        fg=PALETTE["text"],
        font=(UI_FONT, 27, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(10, 8))
    introduction = tk.Label(
        hero,
        text="Explore band areas, inspect the spectrum behind each pixel and compare relative signals.",
        bg=PALETTE["app_bg"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 11),
        anchor="w",
        justify="left",
        wraplength=950,
    )
    introduction.pack(fill="x")
    hero.bind(
        "<Configure>",
        lambda event: introduction.configure(wraplength=max(300, event.width - 5)),
    )
    cards = ttk.Frame(page, style="Workspace.TFrame")
    cards.pack(fill="x")
    cards.rowconfigure(0, weight=1)
    _dashboard_card(
        cards,
        0,
        "Raman Map",
        "Select spectral bands, compare area maps and create A/B ratios. Review the local background, inspect linked pixels and export your analysis.",
        "Open Raman Map",
        abrir_imagem_raman,
        "MAP",
    )
    _dashboard_card(
        cards,
        1,
        "Multi-Spectra",
        "Open a temperature or measurement series and inspect its spectra. Adjust the vertical spacing for comparison while preserving the numerical data.",
        "Open Multi-Spectra",
        abrir_multiespectros,
        "SERIES",
    )
    lower = tk.Frame(page, bg=PALETTE["app_bg"])
    lower.pack(fill="x", pady=(22, 0))
    tk.Label(
        lower,
        text="TXT  ·  ASC  ·  CSV  ·  TSV",
        bg=PALETTE["app_bg"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 9),
    ).pack(side="left")
    tk.Label(
        lower,
        text="Select  →  Inspect  →  Compare  →  Export",
        bg=PALETTE["app_bg"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 9),
    ).pack(side="right")
    atualizar_status("Ready. Open a map acquisition or a measurement series.")


def escolher_arquivo_imagem():
    """
    Escolhe o arquivo .asc para o módulo de imagem Raman.

    O programa só pergunta pelo arquivo depois que o usuário
    escolhe 'Imagem Raman' na tela inicial.
    """
    name = ""
    if os.path.exists(arquivo_memoria):
        try:
            with open(arquivo_memoria, "r", encoding="utf-8") as memoria:
                ultimo_arquivo = memoria.read().strip()
        except OSError:
            ultimo_arquivo = ""
        if ultimo_arquivo and os.path.exists(ultimo_arquivo):
            usar_ultimo = messagebox.askyesno(
                "Last Used File",
                f"Open this file again?\n\n" f"{os.path.basename(ultimo_arquivo)}",
                parent=janela,
            )
            if usar_ultimo:
                name = ultimo_arquivo
    if not name or not os.path.exists(name):
        name = fd.askopenfilename(
            parent=janela,
            title="Select a Raman map",
            filetypes=[
                ("Raman text maps", "*.asc *.txt *.csv *.tsv"),
                ("ASC files", "*.asc"),
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("TSV files", "*.tsv"),
                ("All files", "*.*"),
            ],
        )
    return name


# ============================================================
# MÓDULO: IMAGEM RAMAN
# ============================================================


def abrir_imagem_raman():
    """
    Abre o módulo de imagem Raman somente depois
    da escolha do usuário na interface inicial.
    """
    name = escolher_arquivo_imagem()
    if not name:
        atualizar_status("Raman map opening canceled.")
        return
    try:
        # Uso o mesmo importador tolerante a cabeçalhos dos outros módulos.
        # Isso evita um comportamento diferente só porque o mapa veio com
        # nomes de colunas ou metadados antes da tabela numérica.
        b = ler_espectro_texto(name, dtype=np.float32)
    except Exception as erro:
        messagebox.showerror(
            "File Open Error", f"Could not load the file.\n\n{erro}", parent=janela
        )
        return
    if b.ndim != 2 or b.shape[1] < 2:
        messagebox.showerror(
            "Invalid File",
            "The file must contain one Raman shift column "
            "and at least one spectrum.",
            parent=janela,
        )
        return
    if not np.all(np.isfinite(b)):
        messagebox.showerror(
            "Invalid File",
            "The Raman file contains NaN or infinite values. "
            "Clean or export the data again before opening it in IMESPEC.",
            parent=janela,
        )
        return
    try:
        _validar_eixo_raman(b[:, 0])
    except ValueError as erro:
        messagebox.showerror("Invalid Raman Axis", str(erro), parent=janela)
        return
    try:
        with open(arquivo_memoria, "w", encoding="utf-8") as memoria:
            memoria.write(name)
    except OSError:
        pass
    total_espectros = b.shape[1] - 1

    # --------------------------------------------------------
    # FORMATO DO MAPA
    # --------------------------------------------------------
    # IMPORTANTE:
    # O arquivo .asc informa quantos espectros existem, mas não
    # informa, por si só, quantos pontos formavam cada linha da
    # varredura. Em mapas retangulares precisamos recuperar o X
    # que foi realmente configurado na aquisição.
    #
    # No programa original do professor, para mapas retangulares,
    # o valor informado recebe +1 por causa do comportamento do
    # Andor. Mantemos exatamente essa regra.
    mapa_quadrado = math.sqrt(total_espectros).is_integer()
    # Um total quadrado permite sugerir uma geometria, mas não prova que a
    # aquisição era quadrada (por exemplo, 1024 também pode ser 16×64).
    if mapa_quadrado:
        lado = int(math.sqrt(total_espectros))
        confirmar = messagebox.askyesnocancel(
            "Confirm Raman Map Geometry",
            f"The file contains {total_espectros} spectra.\n\n"
            f"Suggested geometry from the spectrum count: {lado} × {lado}.\n\n"
            "The spectrum count alone does not prove the spatial geometry. "
            "Does this match the actual acquisition?\n\n"
            "Yes = use the suggested square map\n"
            "No = enter the acquisition X manually\n"
            "Cancel = stop opening the map",
            parent=janela,
        )
        if confirmar is None:
            atualizar_status("Map geometry setup canceled.")
            return
        if confirmar:
            geometria = {
                "x_aquisicao": lado,
                "nx": lado,
                "ny": lado,
                "pixels_usados": total_espectros,
                "sobrando": 0,
                "quadrado": True,
                "andor_correction": False,
            }
        else:
            geometria = pedir_geometria_mapa(
                total_espectros=total_espectros,
                parent=janela,
                valor_inicial=max(1, lado - 1),
                andor_inicial=True,
            )
            if geometria is None:
                atualizar_status("Map geometry setup canceled.")
                return
    else:
        geometria = pedir_geometria_mapa(
            total_espectros=total_espectros, parent=janela, andor_inicial=True
        )
        if geometria is None:
            atualizar_status("Map geometry setup canceled.")
            return
    nx = geometria["nx"]
    ny = geometria["ny"]
    regra = "+1 Andor" if geometria.get("andor_correction") else "direct X"
    atualizar_status(
        f"Geometry confirmed: {nx} × {ny}; {regra}; "
        f"{geometria['sobrando']} spectrum/spectra outside complete rows."
    )

    # --------------------------------------------------------
    # SINGLE-WINDOW RAMAN MAP WORKSPACE
    # --------------------------------------------------------
    modulo_raman = criar_workspace_module(
        "raman",
        "Raman Map",
        f"{os.path.basename(name)} · {nx} × {ny} map · {total_espectros} spectra",
    )
    corpo_raman = ttk.Frame(
        modulo_raman, style="Workspace.TFrame", padding=(12, 8, 12, 12)
    )
    corpo_raman.pack(fill="both", expand=True)
    corpo_raman.columnconfigure(0, weight=1)
    corpo_raman.rowconfigure(0, weight=1)
    notebook_raman = ttk.Notebook(corpo_raman)
    notebook_raman.grid(row=0, column=0, sticky="nsew")
    aba_espectro = ttk.Frame(notebook_raman, style="Surface.TFrame")
    aba_comparacao = ttk.Frame(notebook_raman, style="Surface.TFrame")
    aba_mapa = ttk.Frame(notebook_raman, style="Surface.TFrame")
    aba_pixel = ttk.Frame(notebook_raman, style="Surface.TFrame")

    notebook_raman.add(aba_espectro, text="  Spectrum & Band  ")
    notebook_raman.add(aba_comparacao, text="  Compare Maps  ")
    notebook_raman.add(aba_mapa, text="  Data Quality  ")
    notebook_raman.add(aba_pixel, text="  Pixel Spectrum  ")

    quality_header = ttk.Frame(aba_mapa, padding=(12, 10), style="Surface.TFrame")
    quality_header.pack(fill="x")
    ttk.Label(quality_header, text="Mapa:", style="Section.TLabel").pack(
        side="left", padx=(0, 8)
    )
    quality_selector = ttk.Combobox(quality_header, state="disabled", width=24)
    quality_selector.pack(side="left", padx=(0, 14))
    quality_hint = tk.StringVar(
        value="Gere um mapa em Spectrum & Band para abrir as ferramentas."
    )
    ttk.Label(quality_header, textvariable=quality_hint, style="Caption.TLabel").pack(
        side="left"
    )
    quality_style = ttk.Style(aba_mapa)
    quality_style.layout("Quality.TNotebook.Tab", [])
    notebook_qualidade = ttk.Notebook(aba_mapa, style="Quality.TNotebook")
    notebook_qualidade.pack(fill="both", expand=True)

    # --------------------------------------------------------
    # ABA: PIXEL SPECTRUM
    # --------------------------------------------------------
    # Esta aba recebe o espectro correspondente ao pixel clicado no mapa.
    # Assim evitamos abrir uma Figure externa e mantemos toda a análise no
    # mesmo design/workspace do IMESPEC.
    pixel_root = ttk.Frame(aba_pixel, style="Surface.TFrame", padding=(18, 14))
    pixel_root.pack(fill="both", expand=True)
    pixel_root.columnconfigure(0, weight=1)
    pixel_root.rowconfigure(1, weight=1)

    pixel_header = ttk.Frame(pixel_root, style="Surface.TFrame")
    pixel_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    pixel_header.columnconfigure(0, weight=1)

    pixel_title_var = tk.StringVar(value="No map pixel selected")
    pixel_info_var = tk.StringVar(
        value="Double-click a pixel in Compare Maps, or click a pixel in Data Quality."
    )

    ttk.Label(
        pixel_header, textvariable=pixel_title_var, font=("TkDefaultFont", 14, "bold")
    ).grid(row=0, column=0, sticky="w")

    ttk.Label(pixel_header, textvariable=pixel_info_var, foreground="#666666").grid(
        row=1, column=0, sticky="w", pady=(2, 0)
    )

    pixel_actions = ttk.Frame(pixel_header, style="Surface.TFrame")
    pixel_actions.grid(row=0, column=1, rowspan=2, sticky="e")

    ttk.Button(
        pixel_actions,
        text="Back to Maps",
        command=lambda: notebook_raman.select(aba_comparacao),
    ).pack(side="left", padx=(0, 6))

    ttk.Button(
        pixel_actions,
        text="Spectrum & Band",
        command=lambda: notebook_raman.select(aba_espectro),
    ).pack(side="left")

    pixel_plot_host = ttk.Frame(pixel_root, style="Surface.TFrame")
    pixel_plot_host.grid(row=1, column=0, sticky="nsew")
    pixel_plot_host.columnconfigure(0, weight=1)
    pixel_plot_host.rowconfigure(0, weight=1)

    fig_pixel = Figure(figsize=(9.4, 5.7), dpi=100, facecolor="white")
    ax_pixel = fig_pixel.add_subplot(111)
    ax_pixel.set_xlabel(r"Raman shift (cm$^{-1}$)")
    ax_pixel.set_ylabel("Raman intensity (a.u.)")
    ax_pixel.set_title("Click a map pixel to display its spectrum")
    ax_pixel.grid(False)

    canvas_pixel = FigureCanvasTkAgg(fig_pixel, master=pixel_plot_host)
    canvas_pixel.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    toolbar_pixel_frame = ttk.Frame(pixel_plot_host, style="Surface.TFrame")
    toolbar_pixel_frame.grid(row=1, column=0, sticky="ew")
    toolbar_pixel = NavigationToolbar2Tk(
        canvas_pixel, toolbar_pixel_frame, pack_toolbar=False
    )
    toolbar_pixel.update()
    toolbar_pixel.pack(fill="x")

    band_controls = ttk.Frame(aba_espectro, padding=(14, 8), style="Surface.TFrame")
    band_controls.pack(fill="x")
    band_name_var = tk.StringVar(value="Band 1")
    band_range_var = tk.StringVar(value="Select a spectral interval below.")
    ttk.Label(band_controls, text="Map name:").pack(side="left", padx=(0, 6))
    ttk.Entry(band_controls, textvariable=band_name_var, width=22).pack(side="left")
    ttk.Label(
        band_controls, textvariable=band_range_var, foreground=PALETTE["muted"]
    ).pack(side="left", padx=14)
    ttk.Button(
        band_controls,
        text="Compare Maps",
        command=lambda: notebook_raman.select(aba_comparacao),
    ).pack(side="right")
    fig = Figure(figsize=(10.4, 7.6), dpi=100, facecolor="white")
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212)
    canvas_raman = FigureCanvasTkAgg(fig, master=aba_espectro)
    toolbar_raman_frame = ttk.Frame(aba_espectro, style="Surface.TFrame")
    toolbar_raman_frame.pack(fill="x", side="bottom")
    toolbar_raman = NavigationToolbar2Tk(
        canvas_raman, toolbar_raman_frame, pack_toolbar=False
    )
    toolbar_raman.update()
    toolbar_raman.pack(fill="x")
    canvas_raman.get_tk_widget().pack(fill="both", expand=True)
    ax1.set_position([0.125, 0.57, 0.775, 0.31])
    ax2.set_position([0.125, 0.20, 0.775, 0.27])
    estado = {
        "y": b[:, 1],
        "indmin": None,
        "indmax": None,
        # Each saved band has an individual, lazily created review state.
    }
    x = b[:, 0]
    # A sugestão automática só escolhe uma banda inicial. Ela não gera mapa
    # nem corrige dado nenhum sem uma ação explícita do usuário.
    try:
        smart_band = sugerir_banda_raman_mapa(b)
    except Exception:
        smart_band = None

    # --------------------------------------------------------
    # ESCALA DO ESPECTRO
    # --------------------------------------------------------
    # O arquivo usado nos testes, por exemplo, começa em cerca
    # de 639 cm^-1. Na versão original a primeira abertura podia
    # manter uma escala que começava em 0; depois de trocar de
    # espectro o autoscale corrigia a visualização.
    #
    # Para evitar essa diferença, usamos desde a primeira exibição
    # exatamente os limites de Raman shift presentes no arquivo.
    def configurar_eixo_espectro(ax):
        ax.set_xlabel(r"Raman shift (cm$^{-1}$)")
        ax.set_ylabel("Raman intensity (a.u.)")
        ax.set_title("Full spectrum · drag to select a Raman band")
        # Mantém a orientação do eixo tal como ela aparece
        # no arquivo, sem acrescentar uma margem artificial até 0.
        ax.set_xlim(float(x[0]), float(x[-1]))
        # Recalcula apenas a escala vertical para o espectro atual.
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)

    ax2.plot(x, estado["y"])
    configurar_eixo_espectro(ax2)
    (line1,) = ax1.plot([], [])

    # --------------------------------------------------------
    # SLIDER, CAMPO DE NÚMERO E SETAS
    # --------------------------------------------------------
    axframe = fig.add_axes([0.19, 0.085, 0.51, 0.03])
    ax_numero = fig.add_axes([0.76, 0.078, 0.07, 0.045])
    ax_anterior = fig.add_axes([0.08, 0.08, 0.05, 0.04])
    ax_proximo = fig.add_axes([0.87, 0.08, 0.05, 0.04])
    # Cada coluna depois da primeira é um espectro.
    # Portanto o limite correto é o número de colunas - 1.
    # No programa original havia um limite fixo em 1024, que neste
    # arquivo corresponde ao número de pontos do eixo Raman, e não
    # ao número de espectros.
    numero_espectros = b.shape[1] - 1
    sframe = Slider(
        axframe,
        "Spectrum",
        1,
        numero_espectros,
        valinit=1,
        valfmt="%d",
        valstep=1,
        color=PALETTE["primary"],
    )
    # O número mostrado pelo Slider não é editável. Ocultamos esse
    # texto e colocamos uma caixa editável no mesmo conjunto de
    # controles. Assim é possível digitar, por exemplo, 30 e Enter.
    sframe.valtext.set_visible(False)
    caixa_espectro = TextBox(ax_numero, "No.", initial="1")
    botao_anterior = Button(
        ax_anterior, r"$\leftarrow$", color="#E8EDF4", hovercolor="#DDE5EF"
    )
    botao_proximo = Button(
        ax_proximo, r"$\rightarrow$", color="#E8EDF4", hovercolor="#DDE5EF"
    )
    estado_entrada = {"sincronizando": False}

    def valor_atual_espectro():
        return int(round(sframe.val))

    def sincronizar_caixa(numero):
        texto = str(int(numero))
        if caixa_espectro.text == texto:
            return
        estado_entrada["sincronizando"] = True
        caixa_espectro.set_val(texto)
        estado_entrada["sincronizando"] = False

    def ir_para_espectro(numero):
        # Nunca faz looping: abaixo de 1 fica em 1 e acima do
        # último espectro fica no último.
        numero = max(1, min(numero_espectros, int(numero)))
        if numero == valor_atual_espectro():
            sincronizar_caixa(numero)
            return
        sframe.set_val(numero)

    def enviar_numero_digitado(texto):
        if estado_entrada["sincronizando"]:
            return
        try:
            numero = int(texto.strip())
        except (TypeError, ValueError):
            messagebox.showwarning(
                "Invalid Spectrum Number",
                f"Enter an integer between 1 and {numero_espectros}.",
                parent=janela,
            )
            sincronizar_caixa(valor_atual_espectro())
            return
        if not 1 <= numero <= numero_espectros:
            messagebox.showwarning(
                "Spectrum Out of Range",
                f"This file contains {numero_espectros} spectra.\n"
                f"Enter a number between 1 and {numero_espectros}.",
                parent=janela,
            )
            sincronizar_caixa(valor_atual_espectro())
            return
        ir_para_espectro(numero)

    caixa_espectro.on_submit(enviar_numero_digitado)

    def passo_espectro(direcao):
        ir_para_espectro(valor_atual_espectro() + direcao)

    # --------------------------------------------------------
    # CLIQUE OU SEGURE AS SETAS
    # --------------------------------------------------------
    # Um clique avança/volta uma posição. Se o botão ficar
    # pressionado, após uma pequena espera o programa passa os
    # espectros continuamente.
    direcao_segurada = {"valor": 0}
    timer_repeticao = fig.canvas.new_timer(interval=350)

    def repetir_espectro():
        direcao = direcao_segurada["valor"]
        if direcao == 0:
            timer_repeticao.stop()
            return False
        antes = valor_atual_espectro()
        passo_espectro(direcao)
        depois = valor_atual_espectro()
        # Se chegou à extremidade, para a repetição.
        if antes == depois:
            direcao_segurada["valor"] = 0
            timer_repeticao.stop()
            return False
        # Depois do primeiro avanço segurado, acelera.
        timer_repeticao.interval = 90
        return True

    timer_repeticao.add_callback(repetir_espectro)

    def ao_pressionar_seta(event):
        if event.button != 1:
            return
        if event.inaxes is ax_anterior:
            direcao = -1
        elif event.inaxes is ax_proximo:
            direcao = 1
        else:
            return
        direcao_segurada["valor"] = direcao
        # O primeiro passo acontece imediatamente, como num clique.
        passo_espectro(direcao)
        # Se ainda há para onde avançar, começa a repetição.
        if (direcao < 0 and valor_atual_espectro() > 1) or (
            direcao > 0 and valor_atual_espectro() < numero_espectros
        ):
            timer_repeticao.interval = 350
            timer_repeticao.start()

    def ao_soltar_seta(event):
        if direcao_segurada["valor"] != 0:
            direcao_segurada["valor"] = 0
            timer_repeticao.stop()

    cid_press_setas = fig.canvas.mpl_connect("button_press_event", ao_pressionar_seta)
    cid_release_setas = fig.canvas.mpl_connect("button_release_event", ao_soltar_seta)

    def atualizar(val):
        frame = int(round(sframe.val))
        # Segurança adicional: nunca acessa uma coluna fora do
        # intervalo real dos espectros.
        frame = max(1, min(numero_espectros, frame))
        estado["y"] = b[:, frame]
        ax2.clear()
        ax2.plot(x, estado["y"])
        configurar_eixo_espectro(ax2)
        # Keep the zoomed/selected preview synchronized with the spectrum that
        # is currently shown in the lower graph. Previously the top graph could
        # still display data from the preceding spectrum.
        indmin = estado.get("indmin")
        indmax = estado.get("indmax")
        if indmin is not None and indmax is not None and indmax >= indmin:
            region_x = x[indmin : indmax + 1]
            region_y = estado["y"][indmin : indmax + 1]
            if region_x.size >= 2:
                line1.set_data(region_x, region_y)
                ax1.set_xlim(float(region_x[0]), float(region_x[-1]))
                ymin = float(np.min(region_y))
                ymax = float(np.max(region_y))
                if ymin == ymax:
                    pad = max(abs(ymin) * 0.01, 1.0)
                    ymin -= pad
                    ymax += pad
                ax1.set_ylim(ymin, ymax)
        sincronizar_caixa(frame)
        fig.canvas.draw_idle()

    sframe.on_changed(atualizar)

    # --------------------------------------------------------
    # SELEÇÃO DE REGIÃO
    # --------------------------------------------------------
    def onselect_ax(xmin, xmax):
        intervalo = _indices_intervalo_raman(x, xmin, xmax)
        if intervalo is None:
            atualizar_status(
                "Selected Raman interval is smaller than two sampled points. "
                "Drag a slightly wider region."
            )
            return
        indmin, indmax = intervalo
        estado["indmin"] = indmin
        estado["indmax"] = indmax
        band_range_var.set(
            f"Band: {min(float(x[indmin]), float(x[indmax])):.1f}–"
            f"{max(float(x[indmin]), float(x[indmax])):.1f} cm⁻¹"
        )
        # Inclusive slicing is used consistently here and in map integration.
        region_x = x[indmin : indmax + 1]
        region_y = estado["y"][indmin : indmax + 1]
        if len(region_x) >= 2:
            line1.set_data(region_x, region_y)
            ax1.set_xlim(float(region_x[0]), float(region_x[-1]))
            ymin = float(np.min(region_y))
            ymax = float(np.max(region_y))
            if ymin == ymax:
                pad = max(abs(ymin) * 0.01, 1.0)
                ymin -= pad
                ymax += pad
            ax1.set_ylim(ymin, ymax)
            atualizar_status(
                f"Selected Raman band: {float(region_x[0]):.2f} to "
                f"{float(region_x[-1]):.2f} cm⁻¹ ({len(region_x)} sampled points)."
            )
            fig.canvas.draw_idle()

    span1 = SpanSelector(
        ax1,
        onselect_ax,
        "horizontal",
        useblit=True,
        props=dict(alpha=0.5, facecolor=PALETTE["primary"]),
        interactive=True,
        drag_from_anywhere=True,
    )
    span2 = SpanSelector(
        ax2,
        onselect_ax,
        "horizontal",
        useblit=True,
        props=dict(alpha=0.5, facecolor=PALETTE["primary"]),
        interactive=True,
        drag_from_anywhere=True,
    )

    def aplicar_banda_sugerida(event=None):
        if not smart_band:
            messagebox.showinfo(
                "Smart Band",
                "No stable common Raman peak was found for an automatic band suggestion.",
                parent=janela,
            )
            return
        onselect_ax(smart_band["start"], smart_band["end"])
        atualizar_status(
            f"Smart band suggestion applied around {smart_band['center']:.2f} cm⁻¹. "
            "Review the highlighted interval before generating the map."
        )

    # Deixo a sugestão já visível na primeira abertura. É uma seleção, não um
    # processamento; o usuário continua livre para arrastar outra faixa.
    if smart_band:
        onselect_ax(smart_band["start"], smart_band["end"])

    # --------------------------------------------------------
    # MAKE IMAGE
    # --------------------------------------------------------
    def mostrar_espectro_mapa(
        espectro,
        eixo_x,
        eixo_y,
        linha,
        coluna,
        band_indices=None,
        map_name=None,
        bands=None,
        extra_spectra=None,
    ):
        """
        Mostra, dentro do próprio workspace, o espectro do pixel clicado.

        O espectro selecionado também sincroniza o navegador da aba
        Spectrum & Band, mas a visualização imediata acontece na aba
        Pixel Spectrum para não abrir janelas Matplotlib separadas.
        """
        espectro = int(espectro)
        linha = int(linha)
        coluna = int(coluna)

        # Mantém o navegador principal sincronizado com o pixel selecionado.
        ir_para_espectro(espectro)

        eixo_x = np.asarray(eixo_x, dtype=float)
        eixo_y = np.asarray(eixo_y, dtype=float)

        ax_pixel.clear()
        ax_pixel.plot(eixo_x, eixo_y, linewidth=1.15, color="#334B6B")
        for extra_x, extra_y, extra_name, extra_color in extra_spectra or []:
            ax_pixel.plot(
                extra_x,
                extra_y,
                linewidth=1.0,
                color=extra_color,
                alpha=0.8,
                label=extra_name + " spectrum",
            )
        for band in bands or []:
            i0, i1 = band["indices"]
            lo, hi = sorted((float(eixo_x[i0]), float(eixo_x[i1])))
            ax_pixel.axvspan(
                lo, hi, color=band["color"], alpha=0.12, label=band["name"]
            )
        ax_pixel.set_xlabel(r"Raman shift (cm$^{-1}$)")
        ax_pixel.set_ylabel("Raman intensity (a.u.)")
        ax_pixel.set_title(f"Spectrum {espectro} · pixel X={coluna}, Y={linha}")
        ax_pixel.grid(False)

        # Mostra também, de forma discreta, a banda usada para gerar o mapa.
        if band_indices is None:
            indmin, indmax = estado.get("indmin"), estado.get("indmax")
        else:
            indmin, indmax = band_indices
        if (
            not bands
            and indmin is not None
            and indmax is not None
            and 0 <= int(indmin) < len(x)
            and 0 <= int(indmax) < len(x)
        ):
            xa = float(x[int(indmin)])
            xb = float(x[int(indmax)])
            lo, hi = sorted((xa, xb))
            ax_pixel.axvspan(
                lo,
                hi,
                alpha=0.12,
                color=PALETTE["primary"],
                label=map_name or "Map band",
            )
            ax_pixel.legend(loc="best", fontsize=8)

        if bands:
            ax_pixel.legend(loc="best", fontsize=8)
        if eixo_x.size:
            ax_pixel.set_xlim(float(np.min(eixo_x)), float(np.max(eixo_x)))

        ax_pixel.relim()
        ax_pixel.autoscale_view(scalex=False, scaley=True)
        fig_pixel.tight_layout()
        canvas_pixel.draw_idle()

        pixel_title_var.set(
            f"{map_name + ' · ' if map_name else ''}Pixel X={coluna}, Y={linha}  ·  Spectrum #{espectro}"
        )
        pixel_info_var.set(
            "Left-click another map pixel to update this spectrum. "
            "The highlighted interval is the Raman band used to generate the map."
        )

        notebook_raman.select(aba_pixel)

        atualizar_status(
            f"Map pixel ({coluna}, {linha}) → Spectrum {espectro}. "
            "Opened in Pixel Spectrum."
        )

    colecao_mapas = RamanMapCollection(
        aba_comparacao,
        b,
        notebook_qualidade,
        add_band=lambda: notebook_raman.select(aba_espectro),
        show_quality=lambda: notebook_raman.select(aba_mapa),
        show_spectrum=mostrar_espectro_mapa,
        source_path=name,
        software_version=IMESPEC_VERSION,
        dependency_handler=lambda package, feature: abrir_gerenciador_dependencias(
            foco=package, recurso=feature, parent=janela
        ),
        status_callback=atualizar_status,
        quality_selector=quality_selector,
    )
    colecao_mapas.pack(fill="both", expand=True)
    modulo_raman._imespec_maps = colecao_mapas
    quality_selector.bind(
        "<<ComboboxSelected>>", colecao_mapas.open_quality_from_selector
    )

    def abrir_qualidade_ao_selecionar(event=None):
        if str(notebook_raman.select()) != str(aba_mapa):
            return
        bands = [
            record for record in colecao_mapas.records if record.get("kind") != "ratio"
        ]
        if bands:
            quality_hint.set("Cada banda mantém suas próprias correções.")
            active = colecao_mapas._record()
            target = (
                active["numerator_id"]
                if active and active.get("kind") == "ratio"
                else None
            )
            colecao_mapas.open_quality(target)
        else:
            quality_hint.set(
                "Gere um mapa em Spectrum & Band para abrir as ferramentas."
            )

    notebook_raman.bind(
        "<<NotebookTabChanged>>", abrir_qualidade_ao_selecionar, add="+"
    )

    def faz_imagem(event):
        indmin = estado["indmin"]
        indmax = estado["indmax"]
        if indmin is None or indmax is None:
            messagebox.showwarning(
                "No Region Selected",
                "Select a spectral region " "before generating the map.",
                parent=janela,
            )
            return
        if indmin < 2 or indmax + 2 >= len(x):
            messagebox.showwarning(
                "Region Too Close to Edge",
                "Select a region slightly farther " "from the spectrum boundaries.",
                parent=janela,
            )
            return
        try:
            colecao_mapas.add_map(
                band_name_var.get(), indmin, indmax, geometria["nx"], geometria["ny"]
            )
            band_name_var.set(f"Band {colecao_mapas._next_id}")
            notebook_raman.select(aba_comparacao)
        except Exception as erro:
            messagebox.showerror("Map Generation Error", str(erro), parent=janela)

    band_actions = ttk.Frame(
        aba_espectro, padding=(14, 0, 14, 6), style="Surface.TFrame"
    )
    band_actions.pack(fill="x", before=canvas_raman.get_tk_widget())
    ttk.Button(
        band_actions,
        text="Generate Map",
        style="Accent.TButton",
        command=lambda: faz_imagem(None),
    ).pack(side="left", padx=(0, 8))
    ttk.Button(
        band_actions, text="Suggest band", command=lambda: aplicar_banda_sugerida(None)
    ).pack(side="left", padx=(0, 8))
    ttk.Button(
        band_actions, text="Map geometry", command=lambda: alterar_geometria(None)
    ).pack(side="left")
    ttk.Label(
        band_actions,
        text="Drag across a band in the full spectrum below.",
        style="Caption.TLabel",
    ).pack(side="right")
    aximg = fig.add_axes([0.125, 0.91, 0.16, 0.075])
    bimg = Button(
        aximg,
        "Generate Map",
        color=PALETTE["primary"],
        hovercolor=PALETTE["primary_hover"],
    )
    bimg.label.set_color("white")
    bimg.label.set_fontweight("bold")
    bimg.on_clicked(faz_imagem)

    # --------------------------------------------------------
    # REVISAR / ALTERAR GEOMETRIA DO MAPA
    # --------------------------------------------------------
    axgeom = fig.add_axes([0.31, 0.91, 0.19, 0.075])
    botao_geometria = Button(
        axgeom, "Map geometry", color="#E8EDF4", hovercolor="#DDE5EF"
    )
    axsmart = fig.add_axes([0.525, 0.91, 0.16, 0.075])
    botao_smart = Button(axsmart, "Smart band", color="#E8EDF4", hovercolor="#DDE5EF")
    botao_smart.on_clicked(aplicar_banda_sugerida)

    def alterar_geometria(event):
        nova_geometria = pedir_geometria_mapa(
            total_espectros=total_espectros,
            parent=janela,
            valor_inicial=geometria.get("x_aquisicao"),
            andor_inicial=geometria.get("andor_correction", True),
        )
        if nova_geometria is None:
            return
        geometria.update(nova_geometria)
        regra = "+1 Andor" if geometria.get("andor_correction") else "direct X"
        atualizar_status(
            f"New geometry: acquisition X = {geometria['x_aquisicao']}; "
            f"internal map = {geometria['nx']} × {geometria['ny']}; {regra}; "
            f"{geometria['sobrando']} spectrum/spectra outside complete rows. "
            "Click Generate Map to rebuild the map."
        )
        messagebox.showinfo(
            "Geometry Updated",
            f"X entered: {geometria['x_aquisicao']}\n"
            f"Andor correction: {'Yes (+1)' if geometria.get('andor_correction') else 'No'}\n"
            f"Internal X: {geometria['nx']}\n"
            f"Complete rows (Y): {geometria['ny']}\n"
            f"Pixels used: {geometria['pixels_usados']}\n"
            f"Remaining spectra: {geometria['sobrando']}\n\n"
            "The selected Raman region was preserved. Click Generate Map to rebuild the map.",
            parent=janela,
        )

    botao_geometria.on_clicked(alterar_geometria)
    for action_axes in (aximg, axgeom, axsmart):
        action_axes.set_visible(False)
    ax1.set_position([0.10, 0.58, 0.86, 0.32])
    ax2.set_position([0.10, 0.23, 0.86, 0.25])
    # Mantém os widgets vivos.
    fig.sframe = sframe
    fig.caixa_espectro = caixa_espectro
    fig.botao_anterior = botao_anterior
    fig.botao_proximo = botao_proximo
    fig.timer_repeticao = timer_repeticao
    fig.cid_press_setas = cid_press_setas
    fig.cid_release_setas = cid_release_setas
    fig.bimg = bimg
    fig.botao_geometria = botao_geometria
    fig.botao_smart = botao_smart
    fig.span1 = span1
    fig.span2 = span2
    if geometria.get("andor_correction"):
        texto_geometria = (
            f"acquisition X {geometria['x_aquisicao']} (+1 Andor) → "
            f"{geometria['nx']} × {geometria['ny']}"
        )
    else:
        texto_geometria = f"{geometria['nx']} × {geometria['ny']} (confirmed)"
    extra_smart = (
        f" | Smart band: {smart_band['start']:.1f}–{smart_band['end']:.1f} cm⁻¹"
        if smart_band
        else " | Smart band: no stable common peak found"
    )
    atualizar_status(
        f"Raman map opened: {os.path.basename(name)} | Geometry: {texto_geometria}{extra_smart}"
    )
    canvas_raman.draw_idle()
    notebook_raman.select(aba_espectro)


# ============================================================
# MÓDULO: MULTI SPECTRA
# ============================================================


def revisar_ordem_multiespectros(
    caminhos,
    parent=None,
    module_id="multi",
    module_title="Multi-Spectra",
):
    """
    Revisa a ordem dos espectros DENTRO do workspace principal.

    Esta tela substitui a antiga janela Toplevel de ordenação. O primeiro
    item continua sendo a referência da Vertical Distribution; a referência
    de normalização é escolhida separadamente no painel de processamento.

    ``wait_variable`` mantém o fluxo síncrono para preservar a lógica já
    validada do carregamento, sem criar uma segunda janela principal.
    """
    ordem_natural = ordenar_caminhos_natural(caminhos)
    estado = {"caminhos": list(ordem_natural), "resultado": None}
    usa_referencia = True
    host = criar_workspace_module(
        module_id,
        f"{module_title} · Import",
        f"Review {len(ordem_natural)} selected spectra before processing",
    )
    shell = ttk.Frame(host, style="Workspace.TFrame", padding=(26, 22))
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)
    # Page title / guidance.
    head = tk.Frame(
        shell,
        bg=PALETTE["surface"],
        highlightbackground=PALETTE["border"],
        highlightthickness=1,
        padx=22,
        pady=18,
    )
    head.grid(row=0, column=0, sticky="ew", pady=(0, 14))
    tk.Label(
        head,
        text="Review spectrum order",
        bg=PALETTE["surface"],
        fg=PALETTE["text"],
        font=(UI_FONT, 16, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        head,
        text=(
            "Files were arranged using natural sorting. You can reorder the series before continuing. "
            "Spectrum #1 will be the Vertical Distribution alignment reference."
        ),
        bg=PALETTE["surface"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 9),
        justify="left",
        anchor="w",
        wraplength=980,
    ).pack(fill="x", pady=(5, 0))
    body = tk.Frame(
        shell,
        bg=PALETTE["surface"],
        highlightbackground=PALETTE["border"],
        highlightthickness=1,
        padx=18,
        pady=18,
    )
    body.grid(row=1, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    list_panel = tk.Frame(body, bg=PALETTE["surface"])
    list_panel.grid(row=0, column=0, sticky="nsew")
    list_panel.columnconfigure(0, weight=1)
    list_panel.rowconfigure(1, weight=1)
    tk.Label(
        list_panel,
        text=f"Selected spectra  ·  {len(ordem_natural)} files",
        bg=PALETTE["surface"],
        fg=PALETTE["text"],
        font=(UI_FONT, 10, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", pady=(0, 8))
    lista = tk.Listbox(
        list_panel,
        selectmode="browse",
        exportselection=False,
        font=("Consolas", 10),
        bg="#FBFCFE",
        fg=PALETTE["text"],
        selectbackground="#DBEAFE",
        selectforeground=PALETTE["text"],
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=PALETTE["border"],
        activestyle="none",
    )
    lista.grid(row=1, column=0, sticky="nsew")
    sy = ttk.Scrollbar(list_panel, orient="vertical", command=lista.yview)
    sy.grid(row=1, column=1, sticky="ns")
    sx = ttk.Scrollbar(list_panel, orient="horizontal", command=lista.xview)
    sx.grid(row=2, column=0, sticky="ew")
    lista.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    actions = tk.Frame(body, bg=PALETTE["surface"], width=210)
    actions.grid(row=0, column=1, sticky="ns", padx=(18, 0))
    actions.grid_propagate(False)
    tk.Label(
        actions,
        text="ORDER",
        bg=PALETTE["surface"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 8, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 8))

    def action_button(texto, comando, accent=False):
        return tk.Button(
            actions,
            text=texto,
            command=comando,
            cursor="hand2",
            anchor="w",
            bg=PALETTE["primary"] if accent else "#F8FAFC",
            fg="white" if accent else PALETTE["text"],
            activebackground=PALETTE["primary_hover"] if accent else "#EEF2F7",
            activeforeground="white" if accent else PALETTE["text"],
            relief="flat",
            bd=0,
            highlightbackground=PALETTE["border"],
            highlightthickness=0 if accent else 1,
            font=(UI_FONT, 9, "bold" if accent else "normal"),
            padx=12,
            pady=9,
        )

    def atualizar_lista(selecionar=None):
        lista.delete(0, tk.END)
        for indice, caminho in enumerate(estado["caminhos"], start=1):
            ref = "   [REFERENCE]" if usa_referencia and indice == 1 else ""
            lista.insert(tk.END, f"{indice:02d}.  {os.path.basename(caminho)}{ref}")
        if estado["caminhos"]:
            if selecionar is None:
                selecionar = 0
            selecionar = max(0, min(int(selecionar), len(estado["caminhos"]) - 1))
            lista.selection_clear(0, tk.END)
            lista.selection_set(selecionar)
            lista.activate(selecionar)
            lista.see(selecionar)

    def indice_selecionado():
        s = lista.curselection()
        return None if not s else int(s[0])

    def mover(direcao):
        i = indice_selecionado()
        if i is None:
            return
        j = i + direcao
        if not 0 <= j < len(estado["caminhos"]):
            return
        estado["caminhos"][i], estado["caminhos"][j] = (
            estado["caminhos"][j],
            estado["caminhos"][i],
        )
        atualizar_lista(j)

    def definir_referencia():
        i = indice_selecionado()
        if i is None or i == 0:
            return
        caminho = estado["caminhos"].pop(i)
        estado["caminhos"].insert(0, caminho)
        atualizar_lista(0)

    def restaurar_natural():
        estado["caminhos"] = list(ordem_natural)
        atualizar_lista(0)

    action_button("Move up", lambda: mover(-1)).pack(fill="x", pady=(0, 6))
    action_button("Move down", lambda: mover(1)).pack(fill="x", pady=(0, 6))
    if usa_referencia:
        action_button("Set as reference", definir_referencia).pack(
            fill="x", pady=(8, 6)
        )
    action_button("Restore natural sort", restaurar_natural).pack(fill="x", pady=(0, 6))
    tk.Frame(actions, bg=PALETTE["border"], height=1).pack(fill="x", pady=14)
    tk.Label(
        actions,
        text="Spectrum #1 is used only as the Vertical Distribution alignment reference.",
        bg=PALETTE["surface"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 8),
        justify="left",
        wraplength=185,
        anchor="w",
    ).pack(fill="x")
    rodape = tk.Frame(shell, bg=PALETTE["app_bg"])
    rodape.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    rodape.columnconfigure(0, weight=1)
    done = tk.StringVar(value="")

    def confirmar():
        estado["resultado"] = list(estado["caminhos"])
        done.set("continue")

    def cancelar():
        estado["resultado"] = None
        done.set("cancel")

    tk.Label(
        rodape,
        text="Nothing has been modified yet.",
        bg=PALETTE["app_bg"],
        fg=PALETTE["muted"],
        font=(UI_FONT, 8),
    ).grid(row=0, column=0, sticky="w")
    footer_buttons = tk.Frame(rodape, bg=PALETTE["app_bg"])
    footer_buttons.grid(row=0, column=1, sticky="e")
    tk.Button(
        footer_buttons,
        text="Cancel",
        command=cancelar,
        cursor="hand2",
        bg="#F8FAFC",
        fg=PALETTE["text"],
        activebackground="#EEF2F7",
        relief="flat",
        bd=0,
        highlightbackground=PALETTE["border"],
        highlightthickness=1,
        font=(UI_FONT, 9),
        padx=16,
        pady=8,
    ).pack(side="left", padx=(0, 8))
    tk.Button(
        footer_buttons,
        text="Continue to Vertical Distribution  →",
        command=confirmar,
        cursor="hand2",
        bg=PALETTE["primary"],
        fg="white",
        activebackground=PALETTE["primary_hover"],
        activeforeground="white",
        relief="flat",
        bd=0,
        font=(UI_FONT, 9, "bold"),
        padx=18,
        pady=8,
    ).pack(side="left")
    atualizar_lista(0)
    atualizar_status(f"Reviewing order for {len(ordem_natural)} spectra.")
    # Nested Tk event loop, but still inside the single application window.
    janela.wait_variable(done)
    resultado = estado["resultado"]
    if resultado is None:
        mostrar_home()
    return resultado


def abrir_processamento_multiespectros(f3, caminhos_ordenados):
    """
    Multi-Spectra — etapa atual do projeto.

    Nesta versão, o único processamento disponível é Vertical Distribution
    (efeito cascata), usado apenas para visualização. Os espectros brutos são
    preservados e cada nova aplicação parte novamente dos dados originais.
    """
    janela_multi = criar_workspace_module(
        "multi",
        "Multi-Spectra",
        f"{len(caminhos_ordenados)} spectra · Vertical Distribution only",
    )
    janela_multi.title("IMESPEC — Multi-Spectra — Vertical Distribution")

    raiz = ttk.Frame(janela_multi, padding=10)
    raiz.pack(fill="both", expand=True)
    raiz.columnconfigure(0, weight=0)
    raiz.columnconfigure(1, weight=1)
    raiz.rowconfigure(0, weight=1)

    painel_container, painel = criar_painel_rolavel(raiz, width=385)
    painel_container.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

    # Área do gráfico.
    area_plot = ttk.Frame(raiz)
    area_plot.grid(row=0, column=1, sticky="nsew")
    area_plot.columnconfigure(0, weight=1)
    area_plot.rowconfigure(0, weight=1)

    figura = Figure(figsize=(8, 6), dpi=100)
    ax = figura.add_subplot(111)

    canvas = FigureCanvasTkAgg(figura, master=area_plot)
    canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    toolbar_frame = ttk.Frame(area_plot)
    toolbar_frame.grid(row=1, column=0, sticky="ew")
    toolbar = NavigationToolbar2Tk(canvas, toolbar_frame, pack_toolbar=False)
    toolbar.update()
    toolbar.pack(fill="x")

    # Sempre preservamos uma cópia dos dados carregados.
    dados_originais = copiar_multiespectros(f3)

    estado = {
        "pick_x": False,
        "display": None,
    }

    status_multi = tk.StringVar(
        value="Raw spectra loaded. Vertical Distribution changes display only."
    )

    # A única transformação disponível nesta etapa.
    usar_dist = tk.BooleanVar(value=True)

    try:
        dist_x_sugerido = sugerir_x_referencia_multiespectros(dados_originais)
    except Exception:
        comum_min, comum_max = faixa_comum_multiespectros(dados_originais)
        dist_x_sugerido = comum_min + 0.85 * (comum_max - comum_min)

    dist_xref = tk.StringVar(value=f"{dist_x_sugerido:.2f}")
    dist_delta = tk.StringVar(value="3000")

    def ler_float(variavel, nome):
        texto = variavel.get().strip().replace(",", ".")
        try:
            valor = float(texto)
        except ValueError:
            raise ValueError(f"{nome} must be a valid number.")
        if not np.isfinite(valor):
            raise ValueError(f"{nome} must be finite.")
        return valor

    def desenhar(dados, titulo, distribuido=False):
        ax.clear()

        numero = len(dados) // 2
        for p in range(numero):
            ax.plot(dados[2 * p], dados[2 * p + 1], linewidth=1.0)

        ax.set_xlabel(r"Raman shift (cm$^{-1}$)")

        if distribuido:
            ax.set_ylabel("Raman intensity (a.u.) + display offset")
        else:
            ax.set_ylabel("Raman intensity (a.u.)")

        ax.set_title(titulo)
        ax.grid(False)

        figura.tight_layout()
        canvas.draw_idle()

    # ========================================================
    # MULTI-SPECTRA — SOMENTE VERTICAL DISTRIBUTION
    # ========================================================
    ttk.Label(painel, text="Multi-Spectra", font=("TkDefaultFont", 14, "bold")).pack(
        anchor="w", pady=(0, 2)
    )

    ttk.Label(
        painel, text="Vertical Distribution / cascade display", foreground="#666666"
    ).pack(anchor="w", pady=(0, 10))

    # Informação mínima necessária da série.
    frame_spectra = ttk.LabelFrame(painel, text="Spectra", padding=9)
    frame_spectra.pack(fill="x", pady=(0, 9))

    ttk.Label(
        frame_spectra,
        text=f"{len(caminhos_ordenados)} spectra loaded",
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")

    ttk.Label(
        frame_spectra,
        text=(
            "Alignment reference: Spectrum #1 —\n"
            + os.path.basename(caminhos_ordenados[0])
        ),
        wraplength=325,
        justify="left",
        foreground="#555555",
    ).pack(anchor="w", pady=(4, 0))

    frame_dist = ttk.LabelFrame(
        painel, text="Vertical Distribution (display only)", padding=9
    )
    frame_dist.pack(fill="x", pady=(0, 9))

    ttk.Checkbutton(frame_dist, text="Enable distribution", variable=usar_dist).pack(
        anchor="w", pady=(0, 7)
    )

    linha_x = ttk.Frame(frame_dist)
    linha_x.pack(fill="x", pady=4)

    ttk.Label(linha_x, text="Reference X").pack(side="left")

    ttk.Entry(linha_x, textvariable=dist_xref, width=14).pack(side="right")

    linha_delta = ttk.Frame(frame_dist)
    linha_delta.pack(fill="x", pady=4)

    ttk.Label(linha_delta, text="Vertical offset").pack(side="left")

    ttk.Entry(linha_delta, textvariable=dist_delta, width=14).pack(side="right")

    ttk.Label(
        frame_dist,
        text=(
            "Display transformation only. The raw spectra are preserved and "
            "every application starts again from the original data."
        ),
        wraplength=325,
        justify="left",
        foreground="#666666",
    ).pack(anchor="w", pady=(8, 8))

    def ativar_pick_x():
        estado["pick_x"] = True
        status_multi.set("Click the graph at the Raman shift to use as Reference X.")

    ttk.Button(frame_dist, text="Pick X on Plot", command=ativar_pick_x).pack(
        fill="x", pady=(2, 7)
    )

    def aplicar_distribuicao():
        # Se o checkbox estiver desligado, voltamos aos dados crus.
        if not usar_dist.get():
            estado["display"] = None
            desenhar(dados_originais, "Multi-Spectra — Raw spectra", distribuido=False)
            status_multi.set("Distribution disabled. Showing raw spectra.")
            return

        try:
            xref = ler_float(dist_xref, "Reference X")
            delta = ler_float(dist_delta, "Vertical offset")

            if delta < 0:
                raise ValueError(
                    "Vertical offset must be greater than or equal to zero."
                )

            comum_min, comum_max = faixa_comum_multiespectros(dados_originais)

            if not comum_min <= xref <= comum_max:
                raise ValueError(
                    f"Reference X must lie in the common Raman range "
                    f"({comum_min:.2f} to {comum_max:.2f} cm⁻¹)."
                )

            # IMPORTANTE:
            # distribuir() altera os vetores que recebe.
            # Portanto usamos uma nova cópia a cada clique.
            display = distribuir(copiar_multiespectros(dados_originais), xref, delta)

            estado["display"] = display

            desenhar(
                display,
                (
                    "Multi-Spectra — Vertical Distribution · "
                    f"Reference X={xref:.2f} · offset={delta:g}"
                ),
                distribuido=True,
            )

            status_multi.set(
                "Vertical Distribution applied to display only: "
                f"X={xref:.2f} cm⁻¹; offset={delta:g}."
            )

        except Exception as erro:
            messagebox.showerror(
                "Vertical Distribution", str(erro), parent=janela_multi
            )
            status_multi.set("Could not apply Vertical Distribution.")

    def mostrar_bruto():
        estado["display"] = None
        desenhar(dados_originais, "Multi-Spectra — Raw spectra", distribuido=False)
        status_multi.set("Showing raw spectra. No display offset is applied.")

    ttk.Button(
        frame_dist, text="Apply Distribution", command=aplicar_distribuicao
    ).pack(fill="x", pady=(0, 5))

    ttk.Button(frame_dist, text="Show Raw", command=mostrar_bruto).pack(
        fill="x", pady=(0, 5)
    )

    ttk.Separator(painel, orient="horizontal").pack(fill="x", pady=(10, 7))

    ttk.Label(
        painel,
        textvariable=status_multi,
        wraplength=325,
        justify="left",
        foreground="#444444",
    ).pack(fill="x", pady=(0, 8))

    ttk.Button(painel, text="Back to Home", command=janela_multi.destroy).pack(fill="x")

    # --------------------------------------------------------
    # ESCOLHER REFERENCE X DIRETAMENTE NO GRÁFICO
    # --------------------------------------------------------
    def clique_plot(event):
        if not estado["pick_x"]:
            return

        if event.inaxes is not ax or event.xdata is None:
            return

        try:
            comum_min, comum_max = faixa_comum_multiespectros(dados_originais)

            xref = float(np.clip(float(event.xdata), comum_min, comum_max))

            dist_xref.set(f"{xref:.2f}")
            estado["pick_x"] = False

            status_multi.set(
                f"Reference X selected on plot: {xref:.2f} cm⁻¹. "
                "Click Apply Distribution."
            )

        except Exception as erro:
            estado["pick_x"] = False
            messagebox.showerror("Reference X", str(erro), parent=janela_multi)

    canvas.mpl_connect("button_press_event", clique_plot)

    # Abre mostrando os dados crus.
    desenhar(dados_originais, "Multi-Spectra — Raw spectra", distribuido=False)

    atualizar_status(
        f"Multi-Spectra opened: {len(caminhos_ordenados)} spectra · "
        "Vertical Distribution only."
    )


def abrir_multiespectros():
    """
    Seleciona vários espectros, permite revisar a ordem e abre a
    Vertical Distribution (efeito cascata) para visualização.
    """
    if _LEGACY_CHILD:
        _retornar_moderno("multi")
        return
    caminhos = fd.askopenfilenames(
        parent=janela,
        title="Select spectra files from the same measurement",
        filetypes=[
            ("Spectral text files", "*.txt *.csv *.tsv *.asc"),
            ("TXT files", "*.txt"),
            ("CSV files", "*.csv"),
            ("TSV files", "*.tsv"),
            ("All files", "*.*"),
        ],
    )
    if not caminhos:
        atualizar_status("Multi-Spectra opening canceled.")
        return
    caminhos_confirmados = revisar_ordem_multiespectros(
        caminhos, janela, module_id="multi", module_title="Multi-Spectra"
    )
    if not caminhos_confirmados:
        atualizar_status("Multi-Spectra order review canceled.")
        return
    try:
        # A ordem já foi revisada pelo usuário; não reordenar novamente.
        f3, caminhos_ordenados = carregar_multiespectros(
            caminhos_confirmados, ordenar=False
        )
    except Exception as erro:
        messagebox.showerror("Spectra Open Error", str(erro), parent=janela)
        return
    if not f3:
        return
    print("\nLoaded spectra order:")
    for numero, caminho in enumerate(caminhos_ordenados, start=1):
        marcador = " [REFERENCE]" if numero == 1 else ""
        print(numero, "-", os.path.basename(caminho) + marcador)
    abrir_processamento_multiespectros(f3, caminhos_ordenados)


# ============================================================
# INTERFACE PRINCIPAL — SINGLE-WINDOW PROFESSIONAL WORKSPACE
# ============================================================
janela = tk.Tk()
UI_FONT = apply_theme(janela)
janela.title(f"IMESPEC {IMESPEC_VERSION} — Raman Analysis")
janela.geometry("1480x900")
janela.minsize(1120, 700)
janela.configure(bg=PALETTE["app_bg"])
janela.option_add("*tearOff", False)
# Better Windows high-DPI behavior when Tk can provide it.
try:
    janela.tk.call("tk", "scaling", max(1.0, janela.winfo_fpixels("1i") / 72.0))
except Exception:
    pass
status_var = tk.StringVar(value="Starting IMESPEC...")
dependencias_status_var = tk.StringVar(value="Environment: checking dependencies...")
workspace_title_var = tk.StringVar(value="Home")
workspace_context_var = tk.StringVar(value="Raman spectroscopy analysis workspace")

# ------------------------------------------------------------
# THEME
# ------------------------------------------------------------
style = ttk.Style(janela)
# Make default Matplotlib figures visually coherent with the shell while
# preserving data colors chosen by Matplotlib itself.
try:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [UI_FONT, "Arial", "DejaVu Sans"],
            "axes.titleweight": "regular",
            "axes.edgecolor": "#94A3B8",
            "axes.labelcolor": "#334155",
            "xtick.color": "#475569",
            "ytick.color": "#475569",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
except Exception:
    pass

# ------------------------------------------------------------
# MENU BAR
# ------------------------------------------------------------
menu = tk.Menu(janela, bg="#FFFFFF", fg=PALETTE["text"], activebackground="#E8F0FE")
menu_file = tk.Menu(menu)
menu_file.add_command(label="Home", command=mostrar_home, accelerator="Ctrl+H")
menu_file.add_separator()
menu_file.add_command(
    label="Open Raman Map...", command=abrir_imagem_raman, accelerator="Ctrl+1"
)
menu_file.add_command(
    label="Open Multi-Spectra...", command=abrir_multiespectros, accelerator="Ctrl+2"
)
menu_file.add_separator()
menu_file.add_command(label="Exit", command=janela.destroy)
menu.add_cascade(label="File", menu=menu_file)
menu_tools = tk.Menu(menu)
menu_tools.add_command(
    label="Dependencies...",
    command=lambda: abrir_gerenciador_dependencias(parent=janela),
)
menu.add_cascade(label="Tools", menu=menu_tools)
menu_help = tk.Menu(menu)
menu_help.add_command(
    label="About IMESPEC",
    command=lambda: messagebox.showinfo(
        "About IMESPEC",
        f"IMESPEC {IMESPEC_VERSION}\n{IMESPEC_EDITION}\n\n"
        "Raman band-area maps, linked inspection and area ratios.\nMulti-Spectra visualization and scientific export.\n\n"
        f"Main script: {os.path.abspath(__file__)}\n"
        f"Scientific core: {os.path.abspath(getattr(_imespec_core, '__file__', 'unknown'))}",
        parent=janela,
    ),
)
menu.add_cascade(label="Help", menu=menu_help)
janela.config(menu=menu)

# ------------------------------------------------------------
# APP SHELL
# ------------------------------------------------------------
app_shell = tk.Frame(janela, bg=PALETTE["app_bg"])
app_shell.pack(fill="both", expand=True)
app_shell.grid_rowconfigure(0, weight=1)
app_shell.grid_columnconfigure(1, weight=1)
# Sidebar inspired by scientific suites and modern IDE activity/navigation bars.
sidebar = tk.Frame(app_shell, bg=PALETTE["sidebar"], width=198)
sidebar.grid(row=0, column=0, sticky="nsw")
sidebar.grid_propagate(False)
brand = tk.Frame(sidebar, bg=PALETTE["sidebar"], padx=18, pady=18)
brand.pack(fill="x")
brand_row = tk.Frame(brand, bg=PALETTE["sidebar"])
brand_row.pack(fill="x")
tk.Canvas(
    brand_row, width=12, height=12, bg=PALETTE["sidebar"], highlightthickness=0
).pack(side="left", padx=(0, 9))
# Draw brand indicator on the latest canvas.
try:
    dot = brand_row.winfo_children()[0]
    dot.create_oval(1, 1, 11, 11, fill="#60A5FA", outline="")
except Exception:
    pass
tk.Label(
    brand_row,
    text="IMESPEC",
    bg=PALETTE["sidebar"],
    fg="white",
    font=(UI_FONT, 17, "bold"),
).pack(side="left")
tk.Label(
    brand,
    text="Raman Analysis Suite",
    bg=PALETTE["sidebar"],
    fg="#94A3B8",
    font=(UI_FONT, 9),
).pack(anchor="w", pady=(4, 0))
tk.Label(
    brand,
    text=f"v{IMESPEC_VERSION}",
    bg=PALETTE["sidebar"],
    fg="#64748B",
    font=(UI_FONT, 8),
).pack(anchor="w", pady=(2, 0))
nav_label = tk.Label(
    sidebar,
    text="WORKSPACES",
    bg=PALETTE["sidebar"],
    fg="#64748B",
    font=(UI_FONT, 8, "bold"),
    anchor="w",
    padx=18,
)
nav_label.pack(fill="x", pady=(8, 6))
nav_buttons = {}


def _nav_button(key, text, command, shortcut=""):
    row = tk.Frame(sidebar, bg=PALETTE["sidebar"])
    row.pack(fill="x", padx=10, pady=2)
    label = text if not shortcut else f"{text}     {shortcut}"
    btn = tk.Button(
        row,
        text=label,
        command=command,
        cursor="hand2",
        anchor="w",
        bg=PALETTE["sidebar"],
        fg="#DCE6F2",
        activebackground=PALETTE["sidebar_hover"],
        activeforeground="white",
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=(UI_FONT, 10),
        padx=12,
        pady=10,
    )
    btn.pack(fill="x")
    nav_buttons[key] = btn
    return btn


_nav_button("home", "Home", mostrar_home, "")
_nav_button("raman", "Raman Map", abrir_imagem_raman, "Ctrl+1")
_nav_button("multi", "Multi-Spectra", abrir_multiespectros, "Ctrl+2")
side_sep = tk.Frame(sidebar, height=1, bg="#243247")
side_sep.pack(side="bottom", fill="x", padx=18, pady=16)
system_panel = tk.Frame(sidebar, bg=PALETTE["sidebar"])
system_panel.pack(side="bottom", fill="x", pady=(0, 12))
tk.Button(
    system_panel,
    text="Settings & dependencies",
    command=lambda: abrir_gerenciador_dependencias(parent=janela),
    cursor="hand2",
    anchor="w",
    bg=PALETTE["sidebar"],
    fg="#C0D1EB",
    activebackground=PALETTE["sidebar_hover"],
    activeforeground="white",
    relief="flat",
    bd=0,
    font=(UI_FONT, 9),
    padx=18,
    pady=8,
).pack(fill="x")
tk.Label(
    system_panel,
    text="Local analysis workspace",
    bg=PALETTE["sidebar"],
    fg="#7589A7",
    font=(UI_FONT, 8),
    anchor="w",
    padx=18,
).pack(fill="x")
# Right-hand application area.
main_area = tk.Frame(app_shell, bg=PALETTE["app_bg"])
main_area.grid(row=0, column=1, sticky="nsew")
main_area.grid_rowconfigure(1, weight=1)
main_area.grid_columnconfigure(0, weight=1)
# Compact top bar: breadcrumb/context rather than a second oversized title.
topbar = tk.Frame(
    main_area,
    bg=PALETTE["surface"],
    height=58,
    highlightbackground=PALETTE["border"],
    highlightthickness=1,
)
topbar.grid(row=0, column=0, sticky="ew")
topbar.grid_propagate(False)
topbar.grid_columnconfigure(0, weight=1)
crumb = tk.Frame(topbar, bg=PALETTE["surface"], padx=18, pady=9)
crumb.grid(row=0, column=0, sticky="w")
tk.Label(
    crumb,
    textvariable=workspace_title_var,
    bg=PALETTE["surface"],
    fg=PALETTE["text"],
    font=(UI_FONT, 11, "bold"),
).pack(anchor="w")
tk.Label(
    crumb,
    textvariable=workspace_context_var,
    bg=PALETTE["surface"],
    fg=PALETTE["muted"],
    font=(UI_FONT, 8),
).pack(anchor="w", pady=(1, 0))
quick = tk.Frame(topbar, bg=PALETTE["surface"], padx=14, pady=9)
quick.grid(row=0, column=1, sticky="e")
open_menu = tk.Menu(quick, tearoff=False)
open_menu.add_command(label="Raman map acquisition…", command=abrir_imagem_raman)
open_menu.add_command(label="Measurement series…", command=abrir_multiespectros)


def show_open_menu():
    open_menu.tk_popup(
        open_data_button.winfo_rootx(),
        open_data_button.winfo_rooty() + open_data_button.winfo_height(),
    )


open_data_button = ttk.Button(
    quick, text="Open data ▾", style="Ghost.TButton", command=show_open_menu
)
open_data_button.pack(side="left")
workspace_content = ttk.Frame(main_area, style="Workspace.TFrame")
workspace_content.grid(row=1, column=0, sticky="nsew")
# Persistent status bar: a pattern shared by Origin, IDEs and lab software.
statusbar = tk.Frame(
    main_area,
    bg=PALETTE["surface"],
    height=28,
    highlightbackground=PALETTE["border"],
    highlightthickness=1,
)
statusbar.grid(row=2, column=0, sticky="ew")
statusbar.grid_propagate(False)
statusbar.grid_columnconfigure(0, weight=1)
tk.Label(
    statusbar,
    textvariable=status_var,
    bg=PALETTE["surface"],
    fg=PALETTE["muted"],
    font=(UI_FONT, 8),
    anchor="w",
    padx=12,
).grid(row=0, column=0, sticky="ew")
tk.Label(
    statusbar,
    text=f"Session workspace  ·  v{IMESPEC_VERSION}",
    bg=PALETTE["surface"],
    fg="#94A3B8",
    font=(UI_FONT, 8),
    padx=12,
).grid(row=0, column=1, sticky="e")

# ------------------------------------------------------------
# SHORTCUTS / STARTUP
# ------------------------------------------------------------
janela.bind("<Control-h>", lambda event: mostrar_home())
janela.bind("<Control-Key-1>", lambda event: abrir_imagem_raman())
janela.bind("<Control-Key-2>", lambda event: abrir_multiespectros())
janela.bind(
    "<F1>",
    lambda event: messagebox.showinfo(
        "IMESPEC Shortcuts",
        "Ctrl+1  Raman Map\nCtrl+2  Multi-Spectra\nCtrl+H  Home",
        parent=janela,
    ),
)
print("=" * 72)
print(f"IMESPEC {IMESPEC_VERSION} — {IMESPEC_EDITION}")
print(f"Main script     : {os.path.abspath(__file__)}")
print(
    f"Scientific core: {os.path.abspath(getattr(_imespec_core, '__file__', 'unknown'))}"
)
print("=" * 72)
atualizar_indicador_dependencias()
if _LEGACY_CHILD:

    def _abrir_mapa_inicial():
        abrir_imagem_raman()
        if janela.winfo_exists() and not workspace_content.winfo_children():
            janela.destroy()

    janela.update_idletasks()
    print("IMESPEC_MAP_READY", flush=True)
    if "--smoke-test" in sys.argv:
        janela.after(700, janela.destroy)
    else:
        janela.after(80, _abrir_mapa_inicial)
else:
    mostrar_home()
janela.mainloop()
if _LEGACY_CHILD:
    raise SystemExit(_MODERN_RETURN_CODE)
