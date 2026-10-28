#!/usr/bin/python3
"""Núcleo científico do IMESPEC.

Aqui ficam as rotinas que mexem nos dados: leitura, correções,
métricas e exportação. A interface chama estas funções, mas a matemática
continua separada para facilitar teste e manutenção.
"""
__author__ = "Cauã"
from matplotlib.backend_bases import MouseButton
from matplotlib.widgets import RadioButtons, Button
from functools import lru_cache
import copy
import importlib
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
# SciPy is a feature dependency rather than a hard startup dependency.
# Keeping the imports refreshable allows IMESPEC to activate optional
# numerical tools without leaving stale references in this module.
sparse = None
spsolve = None
find_peaks = None
peak_widths = None
_SCIPY_AVAILABLE = False
_SCIPY_IMPORT_ERROR = None

def refresh_optional_dependencies():
    """Refresh optional scientific imports and return SciPy availability."""
    global sparse, spsolve
    global find_peaks, peak_widths, _SCIPY_AVAILABLE, _SCIPY_IMPORT_ERROR
    try:
        importlib.invalidate_caches()
        from scipy import sparse as _sparse
        from scipy.sparse.linalg import spsolve as _spsolve
        from scipy.signal import find_peaks as _find_peaks, peak_widths as _peak_widths
        sparse = _sparse
        spsolve = _spsolve
        find_peaks = _find_peaks
        peak_widths = _peak_widths
        _SCIPY_AVAILABLE = True
        _SCIPY_IMPORT_ERROR = None
    except Exception as exc:
        sparse = None
        spsolve = None
        find_peaks = None
        peak_widths = None
        _SCIPY_AVAILABLE = False
        _SCIPY_IMPORT_ERROR = str(exc)
    # arPLS may have cached the NumPy fallback (None) before SciPy became
    # available through the in-app installer. Clear that cache so the newly
    # installed sparse solver is used immediately on the next call.
    cache_func = globals().get("_arpls_sparse_penalty")
    if cache_func is not None and hasattr(cache_func, "cache_clear"):
        try:
            cache_func.cache_clear()
        except Exception:
            pass
    return bool(_SCIPY_AVAILABLE)
refresh_optional_dependencies()

def _trapezoid(y, x=None, axis=-1):
    """NumPy-version compatible trapezoidal integration."""
    func = getattr(np, "trapezoid", None)
    if func is not None:
        return func(y, x=x, axis=axis)
    # NumPy < 2.0 compatibility.
    return np.trapz(y, x=x, axis=axis)
import os
import csv
import io
import json
import hashlib
import zipfile
from datetime import datetime, timezone
import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog as fd
from tkinter import ttk

# ============================================================
# EXPORT / INTEROPERABILITY HELPERS
# ============================================================
_EXPORT_SCHEMA_VERSION = "1.0"

def _json_default(value):
    """JSON encoder helper for NumPy scalars/arrays used in metadata."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (set, tuple)):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def _sha256_file(path):
    """Return SHA-256 for a source file when it is still accessible."""
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None

def _safe_export_name(name, fallback="spectrum"):
    base = os.path.splitext(os.path.basename(str(name or fallback)))[0]
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in base).strip("._")
    return cleaned or fallback

def _zip_csv_writer(zf, arcname):
    """Context helper: stream UTF-8 CSV directly into a ZIP member."""
    raw = zf.open(arcname, "w")
    text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
    return raw, text, csv.writer(text)

def _write_matrix_csv_to_zip(zf, arcname, matrix, x_label="y\\x"):
    matrix = np.asarray(matrix, dtype=float)
    raw, text, writer = _zip_csv_writer(zf, arcname)
    try:
        writer.writerow([x_label] + list(range(matrix.shape[1])))
        for row_idx, row in enumerate(matrix):
            writer.writerow([row_idx] + [f"{float(v):.12g}" for v in row])
        text.flush()
    finally:
        text.detach()
        raw.close()

def _figure_bytes_map(area, raman_start, raman_end, fmt="png", display_limits=None):
    area = np.asarray(area, dtype=float)
    fig = plt.Figure(figsize=(7.3, 6.2), dpi=150)
    ax = fig.add_subplot(111)
    kwargs = {"interpolation": "nearest"}
    if display_limits is not None and len(display_limits) == 2:
        lo, hi = map(float, display_limits)
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            kwargs.update(vmin=lo, vmax=hi)
    im = ax.imshow(area, **kwargs)
    ax.set_title(
        f"Raman Map — integrated band: {float(raman_start):.1f} to "
        f"{float(raman_end):.1f} cm$^{{-1}}$"
    )
    ax.set_xlabel("X pixel")
    ax.set_ylabel("Y pixel")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("Background-corrected Raman band area (a.u.·cm⁻¹)")
    fig.tight_layout()
    bio = io.BytesIO()
    fig.savefig(bio, format=fmt, bbox_inches="tight")
    return bio.getvalue()

def _figure_bytes_multispectra(data, names=None, title="Multi-Spectra", fmt="png"):
    if len(data) < 2 or len(data) % 2:
        raise ValueError("Invalid Multi-Spectra data structure for export plot.")
    fig = plt.Figure(figsize=(9.0, 5.5), dpi=150)
    ax = fig.add_subplot(111)
    n = len(data) // 2
    for p in range(n):
        label = None
        if names and p < len(names):
            label = os.path.basename(str(names[p]))
        ax.plot(np.asarray(data[2*p], float), np.asarray(data[2*p+1], float), lw=1.0, label=label)
    ax.set_xlabel("Raman shift (cm$^{-1}$)")
    ax.set_ylabel("Raman intensity (a.u.)")
    ax.set_title(title)
    ax.grid(False)
    if names and n <= 12:
        ax.legend(loc="best", fontsize=7)
    fig.tight_layout()
    bio = io.BytesIO()
    fig.savefig(bio, format=fmt, bbox_inches="tight")
    return bio.getvalue()

def faixa_comum_multiespectros(f3):
    """Validate spectra and return their common Raman-shift interval."""
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    mins, maxs = [], []
    for p in range(len(f3)//2):
        x = np.asarray(f3[2*p], dtype=float)
        y = np.asarray(f3[2*p+1], dtype=float)
        if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
            raise ValueError(f"Spectrum {p+1} has invalid x/y data.")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError(f"Spectrum {p+1} contains non-finite values.")
        dx = np.diff(x)
        if np.any(np.abs(dx) <= np.finfo(float).eps):
            raise ValueError(f"Spectrum {p+1} contains repeated Raman-shift values.")
        if not (np.all(dx > 0) or np.all(dx < 0)):
            raise ValueError(f"Spectrum {p+1} Raman-shift axis must be strictly monotonic.")
        mins.append(float(np.min(x)))
        maxs.append(float(np.max(x)))
    lo = max(mins)
    hi = min(maxs)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        raise ValueError("The spectra do not share a common Raman-shift interval.")
    return float(lo), float(hi)

def sugerir_x_referencia_multiespectros(f3):
    """Suggest a quiet, valid high-wavenumber point for display alignment."""
    x, y = construir_espectro_representativo(f3)
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.size < 5:
        return float(x[len(x)//2])
    lo, hi = float(np.min(x)), float(np.max(x))
    span = max(hi-lo, np.finfo(float).eps)
    # Prefer the upper quarter, where a quiet baseline point is often easier to
    # identify, but score intensity and slope so a real peak is avoided.
    mask = (x >= lo + 0.72*span) & (x <= lo + 0.97*span)
    if np.count_nonzero(mask) < 5:
        mask = np.ones_like(x, dtype=bool)
    ys = _media_movel(y, 9)
    grad = np.abs(np.gradient(ys, x))
    yy = ys[mask]
    gg = grad[mask]
    def robust_scale(v):
        med = np.median(v)
        mad = np.median(np.abs(v-med))
        s = 1.4826*mad
        if not np.isfinite(s) or s <= np.finfo(float).eps:
            s = np.std(v)
        return max(float(s), np.finfo(float).eps)
    score = (yy - np.min(yy))/robust_scale(yy) + gg/robust_scale(gg)
    candidates = np.flatnonzero(mask)
    return float(x[candidates[int(np.argmin(score))]])

def exportar_pacote_raman_mapa(
    caminho_zip,
    b_atual,
    b_sessao,
    area_atual,
    area_original,
    xstart,
    xstop,
    nx,
    ny,
    source_path=None,
    cosmic_history=None,
    bad_pixel_history=None,
    processing_history=None,
    display_limits=None,
    robust_display=False,
    software_version="unknown",
):
    """Export a reproducible Raman-map analysis bundle as a ZIP archive."""
    if not caminho_zip:
        raise ValueError("Export path was not provided.")
    if not str(caminho_zip).lower().endswith(".zip"):
        caminho_zip = str(caminho_zip) + ".zip"
    b_atual = np.asarray(b_atual)
    b_sessao = np.asarray(b_sessao)
    area_atual = np.asarray(area_atual, dtype=float)
    area_original = np.asarray(area_original, dtype=float)
    nx, ny = int(nx), int(ny)
    mt = nx*ny
    if b_atual.ndim != 2 or b_atual.shape[1] < mt+1:
        raise ValueError("Current Raman matrix does not match the map geometry.")
    if b_sessao.shape != b_atual.shape:
        raise ValueError("Session-open and current Raman matrices have different shapes.")
    if area_atual.shape != (ny, nx) or area_original.shape != (ny, nx):
        raise ValueError("Raman map dimensions do not match the confirmed geometry.")
    x = np.asarray(b_atual[:, 0], dtype=float)
    i0, i1 = sorted((int(xstart), int(xstop)))
    if not (0 <= i0 < i1 < x.size):
        raise ValueError("Selected Raman band indices are invalid.")
    raman_start = float(min(x[i0], x[i1]))
    raman_end = float(max(x[i0], x[i1]))
    source_name = os.path.basename(source_path) if source_path else None
    source_hash = _sha256_file(source_path)
    cosmic_history = list(cosmic_history or [])
    bad_pixel_history = list(bad_pixel_history or [])
    processing_history = list(processing_history or [])
    metadata = {
        "schema": "IMESPEC Raman Map Export",
        "schema_version": _EXPORT_SCHEMA_VERSION,
        "software": "IMESPEC",
        "software_version": software_version,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": source_name,
        "source_sha256": source_hash,
        "geometry": {"nx": nx, "ny": ny, "spectra_used": mt},
        "selected_band": {
            "start_cm-1": raman_start,
            "end_cm-1": raman_end,
            "start_index": i0,
            "end_index": i1,
            "sampled_points": i1-i0+1,
        },
        "map_units": "background-corrected integrated Raman area (a.u.·cm^-1)",
        "integration": {
            "method": "trapezoidal integration after local linear background subtraction",
            "background": "mean of two sampled points immediately before and after the selected band",
        },
        "display": {
            "robust_range": bool(robust_display),
            "limits": list(display_limits) if display_limits is not None else None,
        },
        "processing_history": processing_history,
        "cosmic_ray_apply_count": len(cosmic_history),
        "bad_pixel_repair_count": len(bad_pixel_history),
        "renishaw_style_full_scan_txt_included": bool((x.size * mt) <= 5_000_000),
        "notes": [
            "Bad Pixel Repair is map-only and does not alter underlying spectra.",
            "The original source file on disk is never modified by IMESPEC.",
            "NPZ files preserve the session-open and current in-memory spectral matrices compactly.",
        ],
    }
    readme = f"""IMESPEC RAMAN MAP ANALYSIS PACKAGE
Source: {source_name or 'unknown'}
Selected band: {raman_start:.6g} to {raman_end:.6g} cm^-1
Geometry: {nx} x {ny}
Portable outputs:
  map_current_matrix.csv        Current map as Y rows x X columns.
  map_original_matrix.csv       Map when this map window was opened.
  map_current_long.csv          X/Y/value table for Origin, Excel, Python, R, etc.
  selected_band_spectra.csv     Current spectra only within the selected band.
  spectral_map_long.txt         Generic scan table (#X/#Y/#Wave/#Intensity) when dataset size allows.
  map_current.png / .svg        Publication/report-friendly map images.
  metadata.json                 Geometry, band, provenance and processing history.
  cosmic_ray_corrections.csv    Reviewed/applied spectral cosmic-ray events, when present.
  bad_pixel_repairs.csv         Map-only repaired pixels, when present.
Compact reproducibility files:
  spectra_session_open.npz      Raman shift + intensity matrix at map-window opening.
  spectra_current.npz           Current Raman shift + intensity matrix after spectral corrections.
Text/CSV files use a decimal point and UTF-8 encoding. The source file on disk is not changed.
"""
    with zipfile.ZipFile(caminho_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr("README.txt", readme)
        zf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False, default=_json_default))
        _write_matrix_csv_to_zip(zf, "map_current_matrix.csv", area_atual)
        _write_matrix_csv_to_zip(zf, "map_original_matrix.csv", area_original)
        raw, text, writer = _zip_csv_writer(zf, "map_current_long.csv")
        try:
            writer.writerow(["x_pixel", "y_pixel", "integrated_area_au_cm-1"])
            for yy in range(ny):
                for xx in range(nx):
                    writer.writerow([xx, yy, f"{float(area_atual[yy, xx]):.12g}"])
            text.flush()
        finally:
            text.detach(); raw.close()
        raw, text, writer = _zip_csv_writer(zf, "selected_band_spectra.csv")
        try:
            writer.writerow(["spectrum", "x_pixel", "y_pixel", "raman_shift_cm-1", "intensity_au"])
            for s in range(1, mt+1):
                p = s-1
                xx, yy = p % nx, p // nx
                for k in range(i0, i1+1):
                    writer.writerow([s, xx, yy, f"{float(x[k]):.12g}", f"{float(b_atual[k, s]):.12g}"])
            text.flush()
        finally:
            text.detach(); raw.close()
        # Generic four-column scan text mirrors the portable convention used by
        # major Raman software exports: X, Y, wavenumber, intensity. Keep a
        # safety cap so very large hyperspectral maps do not create enormous
        # text files; the compact NPZ export is always available.
        if (x.size * mt) <= 5_000_000:
            raw = zf.open("spectral_map_long.txt", "w")
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            try:
                text.write("#X\t#Y\t#Wave\t#Intensity\n")
                for sidx in range(1, mt + 1):
                    pidx = sidx - 1
                    xx, yy = pidx % nx, pidx // nx
                    for k in range(x.size):
                        text.write(
                            f"{xx}\t{yy}\t{float(x[k]):.12g}\t{float(b_atual[k, sidx]):.12g}\n"
                        )
                text.flush()
            finally:
                text.detach(); raw.close()
        for arcname, matrix in (("spectra_session_open.npz", b_sessao), ("spectra_current.npz", b_atual)):
            bio = io.BytesIO()
            np.savez_compressed(
                bio,
                raman_shift=np.asarray(matrix[:, 0], dtype=float),
                intensity=np.asarray(matrix[:, 1:mt+1], dtype=float),
                nx=np.asarray(nx), ny=np.asarray(ny),
                selected_band_indices=np.asarray([i0, i1], dtype=int),
            )
            zf.writestr(arcname, bio.getvalue())
        raw, text, writer = _zip_csv_writer(zf, "cosmic_ray_corrections.csv")
        try:
            writer.writerow([
                "apply_pass", "spectrum", "x_pixel", "y_pixel", "peak_index",
                "raman_shift_cm-1", "start_index", "end_index", "points"
            ])
            for pass_no, report in enumerate(cosmic_history, start=1):
                for item in report.get("spectra", []):
                    s = int(item.get("spectrum", 0))
                    p = s-1
                    xx, yy = (p % nx, p // nx) if 1 <= s <= mt else ("", "")
                    for ev in item.get("events", []):
                        peak = int(ev.get("peak_index", -1))
                        start = int(ev.get("start_index", peak))
                        end = int(ev.get("end_index", peak))
                        shift = float(x[peak]) if 0 <= peak < x.size else ""
                        writer.writerow([pass_no, s, xx, yy, peak, shift, start, end, end-start+1])
            text.flush()
        finally:
            text.detach(); raw.close()
        raw, text, writer = _zip_csv_writer(zf, "bad_pixel_repairs.csv")
        try:
            writer.writerow(["sequence", "mode", "x_pixel", "y_pixel", "old_value", "new_value", "method"])
            for idx, item in enumerate(bad_pixel_history, start=1):
                writer.writerow([
                    idx, item.get("mode", ""), item.get("x_pixel", ""), item.get("y_pixel", ""),
                    item.get("old_value", ""), item.get("new_value", ""), item.get("method", "")
                ])
            text.flush()
        finally:
            text.detach(); raw.close()
        zf.writestr("map_current.png", _figure_bytes_map(area_atual, raman_start, raman_end, "png", display_limits))
        zf.writestr("map_current.svg", _figure_bytes_map(area_atual, raman_start, raman_end, "svg", display_limits))
    return {"path": str(caminho_zip), "metadata": metadata}

def exportar_pacote_multiespectros(
    caminho_zip,
    dados_quantitativos,
    dados_exibicao=None,
    caminhos=None,
    metadata=None,
    cosmic_report=None,
    software_version="unknown",
):
    """Export Multi-Spectra results in portable text/CSV plus reproducibility files."""
    if not caminho_zip:
        raise ValueError("Export path was not provided.")
    if not str(caminho_zip).lower().endswith(".zip"):
        caminho_zip = str(caminho_zip) + ".zip"
    if len(dados_quantitativos) < 2 or len(dados_quantitativos) % 2:
        raise ValueError("Invalid Multi-Spectra quantitative data.")
    n = len(dados_quantitativos)//2
    if dados_exibicao is not None and len(dados_exibicao) != len(dados_quantitativos):
        raise ValueError("Display and quantitative Multi-Spectra datasets do not match.")
    caminhos = list(caminhos or [])
    names = [os.path.basename(caminhos[i]) if i < len(caminhos) else f"Spectrum_{i+1:03d}" for i in range(n)]
    source_info = []
    for i in range(n):
        path = caminhos[i] if i < len(caminhos) else None
        source_info.append({
            "spectrum": i+1,
            "file": names[i],
            "sha256": _sha256_file(path),
        })
    meta = dict(metadata or {})
    meta.update({
        "schema": "IMESPEC Multi-Spectra Export",
        "schema_version": _EXPORT_SCHEMA_VERSION,
        "software": "IMESPEC",
        "software_version": software_version,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "spectra_count": n,
        "sources": source_info,
        "quantitative_data_note": "Vertical Distribution is intentionally excluded from quantitative data.",
        "text_format_note": "Individual TXT files are two-column tab-delimited Raman shift / intensity with decimal point.",
    })
    readme = """IMESPEC MULTI-SPECTRA ANALYSIS PACKAGE

Use quantitative_long.csv or spectra_txt/*.txt for further quantitative work in Origin,
Excel, Python, R, MATLAB, spectroscopy software, etc. The TXT files are plain two-column
ASCII/UTF-8 with Raman shift in column 1 and intensity in column 2.

Files:
  quantitative_long.csv          All quantitative spectra in one tidy/long table.
  spectra_txt/*.txt              One portable two-column spectrum per source file.
  quantitative_data.npz          Compact lossless arrays for reproducible Python workflows.
  quantitative_overview.png/svg  Clean overview figure.
  display_long.csv               Present only when a separate display/distributed dataset exists.
  display_overview.png/svg       Present only for that display dataset.
  cosmic_ray_report.csv          Reviewed cosmic-ray events, when available.
  metadata.json                  Processing settings, source hashes and provenance.

Vertical Distribution is display-only and is never mixed into quantitative export.
"""
    with zipfile.ZipFile(caminho_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr("README.txt", readme)
        zf.writestr("metadata.json", json.dumps(meta, indent=2, ensure_ascii=False, default=_json_default))
        raw, text, writer = _zip_csv_writer(zf, "quantitative_long.csv")
        try:
            writer.writerow(["spectrum", "file", "raman_shift_cm-1", "intensity_au"])
            for p in range(n):
                x = np.asarray(dados_quantitativos[2*p], float)
                y = np.asarray(dados_quantitativos[2*p+1], float)
                for xx, yy in zip(x, y):
                    writer.writerow([p+1, names[p], f"{float(xx):.12g}", f"{float(yy):.12g}"])
            text.flush()
        finally:
            text.detach(); raw.close()
        npz = io.BytesIO()
        payload = {}
        for p in range(n):
            payload[f"x_{p+1:04d}"] = np.asarray(dados_quantitativos[2*p], dtype=float)
            payload[f"y_{p+1:04d}"] = np.asarray(dados_quantitativos[2*p+1], dtype=float)
        np.savez_compressed(npz, **payload)
        zf.writestr("quantitative_data.npz", npz.getvalue())
        for p in range(n):
            base = _safe_export_name(names[p], f"spectrum_{p+1:03d}")
            raw = io.BytesIO()
            x = np.asarray(dados_quantitativos[2*p], float)
            y = np.asarray(dados_quantitativos[2*p+1], float)
            for xx, yy in zip(x, y):
                raw.write(f"{float(xx):.12g}\t{float(yy):.12g}\n".encode("utf-8"))
            zf.writestr(f"spectra_txt/{p+1:03d}_{base}.txt", raw.getvalue())
        zf.writestr("quantitative_overview.png", _figure_bytes_multispectra(dados_quantitativos, names, "Multi-Spectra — Quantitative", "png"))
        zf.writestr("quantitative_overview.svg", _figure_bytes_multispectra(dados_quantitativos, names, "Multi-Spectra — Quantitative", "svg"))
        if dados_exibicao is not None:
            raw, text, writer = _zip_csv_writer(zf, "display_long.csv")
            try:
                writer.writerow(["spectrum", "file", "raman_shift_cm-1", "display_intensity_au"])
                for p in range(n):
                    x = np.asarray(dados_exibicao[2*p], float)
                    y = np.asarray(dados_exibicao[2*p+1], float)
                    for xx, yy in zip(x, y):
                        writer.writerow([p+1, names[p], f"{float(xx):.12g}", f"{float(yy):.12g}"])
                text.flush()
            finally:
                text.detach(); raw.close()
            zf.writestr("display_overview.png", _figure_bytes_multispectra(dados_exibicao, names, "Multi-Spectra — Display", "png"))
            zf.writestr("display_overview.svg", _figure_bytes_multispectra(dados_exibicao, names, "Multi-Spectra — Display", "svg"))
        raw, text, writer = _zip_csv_writer(zf, "cosmic_ray_report.csv")
        try:
            writer.writerow(["spectrum", "file", "raman_shift_cm-1", "peak_index", "start_index", "end_index", "points"])
            report = cosmic_report or {}
            for item in report.get("spectra", []):
                s = int(item.get("spectrum", 0))
                file_name = names[s-1] if 1 <= s <= n else ""
                shifts = list(item.get("raman_shift", []))
                for idx, ev in enumerate(item.get("events", [])):
                    start = int(ev.get("start_index", -1)); end = int(ev.get("end_index", -1))
                    shift = shifts[idx] if idx < len(shifts) else ""
                    writer.writerow([s, file_name, shift, ev.get("peak_index", ""), start, end, end-start+1 if start >= 0 and end >= start else ""])
            text.flush()
        finally:
            text.detach(); raw.close()
    return {"path": str(caminho_zip), "metadata": meta}

# ============================================================
# MULTI-FORMAT SCIENTIFIC EXPORT
# ============================================================
# These exporters intentionally favor open, documented interchange formats.
# The feature set mirrors what established spectroscopy packages expose:
# portable text, JCAMP-DX, Galactic/Thermo SPC, MATLAB, HDF5, spreadsheet
# output, NumPy archives and publication figures. Optional formats are imported
# lazily so the analysis program still starts without every export dependency.

def _normalizar_formatos_exportacao(formatos):
    aliases = {
        "jdx": "jcamp", "jcamp-dx": "jcamp", "jcampdx": "jcamp",
        "h5": "hdf5", "hdf": "hdf5",
        "excel": "xlsx", "xls": "xlsx",
        "matlab": "mat",
        "jpeg": "jpg",
    }
    saida = []
    for item in formatos or []:
        chave = str(item).strip().lower().lstrip('.')
        chave = aliases.get(chave, chave)
        if chave and chave not in saida:
            saida.append(chave)
    return saida

def _diretorio_exportacao_unico(pasta_pai, nome_base):
    pasta_pai = os.path.abspath(os.path.expanduser(str(pasta_pai)))
    if not os.path.isdir(pasta_pai):
        os.makedirs(pasta_pai, exist_ok=True)
    base = _safe_export_name(nome_base, "IMESPEC_export")
    candidato = os.path.join(pasta_pai, base)
    if not os.path.exists(candidato):
        os.makedirs(candidato)
        return candidato
    for n in range(2, 10000):
        candidato = os.path.join(pasta_pai, f"{base}_{n}")
        if not os.path.exists(candidato):
            os.makedirs(candidato)
            return candidato
    raise RuntimeError("Could not create a unique export directory.")

def _write_text_xy(path, x, y, delimiter='\t', header=True):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
        raise ValueError("Spectrum x/y arrays are invalid for text export.")
    with open(path, 'w', encoding='utf-8', newline='') as f:
        if header:
            f.write(f"Raman_shift_cm-1{delimiter}Intensity_au\n")
        for xx, yy in zip(x, y):
            f.write(f"{float(xx):.12g}{delimiter}{float(yy):.12g}\n")
    return path

def _axes_multiespectros_iguais(dados, rtol=1e-10, atol=1e-10):
    if len(dados) < 2 or len(dados) % 2:
        return False
    ref = np.asarray(dados[0], dtype=float)
    for p in range(1, len(dados)//2):
        cur = np.asarray(dados[2*p], dtype=float)
        if cur.shape != ref.shape or not np.allclose(cur, ref, rtol=rtol, atol=atol, equal_nan=False):
            return False
    return True

def _write_multispectra_wide(path, dados, nomes, delimiter=','):
    if not _axes_multiespectros_iguais(dados):
        return False
    x = np.asarray(dados[0], dtype=float)
    ys = [np.asarray(dados[2*p+1], dtype=float) for p in range(len(dados)//2)]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(["raman_shift_cm-1"] + [str(n) for n in nomes])
        for i in range(x.size):
            writer.writerow([f"{float(x[i]):.12g}"] + [f"{float(y[i]):.12g}" for y in ys])
    return True

def _clean_jcamp_text(value):
    texto = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
    return texto[:240]

def escrever_jcamp_dx(path, x, y, title="IMESPEC Raman Spectrum", metadata=None):
    """Write a conservative JCAMP-DX 5.01 Raman spectrum using XYPOINTS."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
        raise ValueError("Invalid spectrum for JCAMP-DX export.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("JCAMP-DX export requires finite x/y values.")
    meta = dict(metadata or {})
    lines = [
        f"##TITLE={_clean_jcamp_text(title)}",
        "##JCAMP-DX=5.01",
        "##DATA TYPE=RAMAN SPECTRUM",
        "##ORIGIN=IMESPEC",
        "##OWNER=",
        "##XUNITS=1/CM",
        "##YUNITS=ARBITRARY UNITS",
        "##XFACTOR=1",
        "##YFACTOR=1",
        f"##FIRSTX={float(x[0]):.12g}",
        f"##LASTX={float(x[-1]):.12g}",
        f"##MINX={float(np.min(x)):.12g}",
        f"##MAXX={float(np.max(x)):.12g}",
        f"##MINY={float(np.min(y)):.12g}",
        f"##MAXY={float(np.max(y)):.12g}",
        f"##NPOINTS={int(x.size)}",
    ]
    for key, value in meta.items():
        if value is None:
            continue
        label = ''.join(c if c.isalnum() else '_' for c in str(key).upper()).strip('_')[:48]
        if label:
            lines.append(f"##$IMESPEC_{label}={_clean_jcamp_text(value)}")
    lines.append("##XYPOINTS=(XY..XY)")
    lines.extend(f"{float(xx):.12g}, {float(yy):.12g}" for xx, yy in zip(x, y))
    lines.append("##END=")
    with open(path, 'w', encoding='ascii', errors='replace', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return path

def _write_spc_file(path, x, y, memo="IMESPEC Raman spectrum"):
    """Write one Raman spectrum as Galactic/Thermo SPC using SPyC_Writer."""
    try:
        from SPyC_Writer import SPCFileWriter, SPCFileType, SPCTechType, SPCXType, SPCYType
    except Exception as exc:
        raise ImportError("SPC export requires the optional package SPyC_Writer.") from exc
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    writer = SPCFileWriter(
        file_type=SPCFileType.TXVALS,
        experiment_type=SPCTechType.SPCTechRmn,
        x_units=SPCXType.SPCXRamans,
        y_units=SPCYType.SPCYArb,
        memo=_clean_jcamp_text(memo),
        src_instrument_desc="IMESPEC",
    )
    ok = writer.write_spc_file(str(path), y_values=y, x_values=x)
    if ok is False or not os.path.isfile(path):
        raise RuntimeError("SPyC_Writer did not create the requested SPC file.")
    return path

def _write_spc_multifile(path, x, ys, memo="IMESPEC Raman spectra"):
    try:
        from SPyC_Writer import SPCFileWriter, SPCFileType, SPCTechType, SPCXType, SPCYType
    except Exception as exc:
        raise ImportError("SPC export requires the optional package SPyC_Writer.") from exc
    x = np.asarray(x, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if ys.ndim != 2 or ys.shape[1] != x.size:
        raise ValueError("SPC multifile data have incompatible dimensions.")
    writer = SPCFileWriter(
        file_type=SPCFileType.TMULTI | SPCFileType.TXVALS,
        experiment_type=SPCTechType.SPCTechRmn,
        x_units=SPCXType.SPCXRamans,
        y_units=SPCYType.SPCYArb,
        memo=_clean_jcamp_text(memo),
        src_instrument_desc="IMESPEC",
    )
    ok = writer.write_spc_file(str(path), y_values=ys, x_values=x)
    if ok is False or not os.path.isfile(path):
        raise RuntimeError("SPyC_Writer did not create the requested SPC multifile.")
    return path

def _write_manifest(pasta, metadata=None):
    itens = []
    for root, dirs, files in os.walk(pasta):
        dirs.sort(); files.sort()
        for name in files:
            if name == "manifest.json":
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, pasta).replace(os.sep, '/')
            itens.append({
                "file": rel,
                "bytes": int(os.path.getsize(full)),
                "sha256": _sha256_file(full),
            })
    payload = {
        "schema": "IMESPEC Export Manifest",
        "schema_version": _EXPORT_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": itens,
        "metadata": metadata or {},
    }
    path = os.path.join(pasta, "manifest.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=_json_default)
    return path

def _write_hdf5_multispectra(path, dados, nomes, metadata=None, display=None):
    try:
        import h5py
    except Exception as exc:
        raise ImportError("HDF5 export requires the optional package h5py.") from exc
    with h5py.File(path, 'w') as h5:
        h5.attrs['software'] = 'IMESPEC'
        h5.attrs['schema'] = 'IMESPEC Multi-Spectra HDF5'
        h5.attrs['metadata_json'] = json.dumps(metadata or {}, ensure_ascii=False, default=_json_default)
        root = h5.create_group('spectra')
        for p in range(len(dados)//2):
            g = root.create_group(f"{p+1:04d}")
            g.attrs['file'] = str(nomes[p])
            g.create_dataset('raman_shift_cm-1', data=np.asarray(dados[2*p], dtype=np.float64), compression='gzip', shuffle=True)
            g.create_dataset('intensity_au', data=np.asarray(dados[2*p+1], dtype=np.float64), compression='gzip', shuffle=True)
        if display is not None:
            droot = h5.create_group('display_only')
            for p in range(len(display)//2):
                g = droot.create_group(f"{p+1:04d}")
                g.attrs['file'] = str(nomes[p])
                g.create_dataset('raman_shift_cm-1', data=np.asarray(display[2*p], dtype=np.float64), compression='gzip', shuffle=True)
                g.create_dataset('display_intensity_au', data=np.asarray(display[2*p+1], dtype=np.float64), compression='gzip', shuffle=True)
    return path

def _write_mat_multispectra(path, dados, nomes, metadata=None, display=None):
    try:
        from scipy.io import savemat
    except Exception as exc:
        raise ImportError("MATLAB MAT export requires SciPy.") from exc
    payload = {
        'IMESPEC_schema': 'IMESPEC Multi-Spectra MATLAB Export',
        'metadata_json': json.dumps(metadata or {}, ensure_ascii=False, default=_json_default),
        'spectrum_names': np.asarray([str(n) for n in nomes], dtype=object),
    }
    for p in range(len(dados)//2):
        payload[f'x_{p+1:04d}'] = np.asarray(dados[2*p], dtype=np.float64)
        payload[f'y_{p+1:04d}'] = np.asarray(dados[2*p+1], dtype=np.float64)
        if display is not None:
            payload[f'y_display_{p+1:04d}'] = np.asarray(display[2*p+1], dtype=np.float64)
    savemat(path, payload, do_compression=True, long_field_names=True)
    return path

def _excel_sheet_name(name, used):
    bad = '[]:*?/\\'
    clean = ''.join('_' if c in bad else c for c in str(name)).strip() or 'Spectrum'
    clean = clean[:31]
    base = clean
    n = 2
    while clean in used:
        suffix = f"_{n}"
        clean = base[:31-len(suffix)] + suffix
        n += 1
    used.add(clean)
    return clean

def _write_xlsx_multispectra(path, dados, nomes, metadata=None, display=None):
    try:
        from openpyxl import Workbook
    except Exception as exc:
        raise ImportError("Excel XLSX export requires the optional package openpyxl.") from exc
    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    ws.append(['IMESPEC Multi-Spectra Export'])
    ws.append(['Spectra', len(dados)//2])
    ws.append([])
    ws.append(['Metadata JSON'])
    ws.append([json.dumps(metadata or {}, ensure_ascii=False, default=_json_default)])
    used = {'Summary'}
    for p in range(len(dados)//2):
        name = _excel_sheet_name(f"{p+1:03d}_{os.path.basename(str(nomes[p]))}", used)
        sh = wb.create_sheet(name)
        sh.append(['Raman shift (cm^-1)', 'Intensity (a.u.)'] + (['Display intensity (a.u.)'] if display is not None else []))
        x = np.asarray(dados[2*p], dtype=float)
        y = np.asarray(dados[2*p+1], dtype=float)
        yd = np.asarray(display[2*p+1], dtype=float) if display is not None else None
        for i in range(x.size):
            row = [float(x[i]), float(y[i])]
            if yd is not None:
                row.append(float(yd[i]))
            sh.append(row)
    wb.save(path)
    return path

def _write_hdf5_raman_map(path, b_current, b_open, area_current, area_original, nx, ny, band_indices, metadata=None):
    try:
        import h5py
    except Exception as exc:
        raise ImportError("HDF5 export requires the optional package h5py.") from exc
    b_current = np.asarray(b_current, dtype=float)
    b_open = np.asarray(b_open, dtype=float)
    nx, ny = int(nx), int(ny)
    mt = nx*ny
    x = b_current[:, 0]
    cube_cur = b_current[:, 1:mt+1].T.reshape(ny, nx, x.size)
    cube_open = b_open[:, 1:mt+1].T.reshape(ny, nx, x.size)
    with h5py.File(path, 'w') as h5:
        h5.attrs['software'] = 'IMESPEC'
        h5.attrs['schema'] = 'IMESPEC Raman Map HDF5'
        h5.attrs['metadata_json'] = json.dumps(metadata or {}, ensure_ascii=False, default=_json_default)
        h5.create_dataset('raman_shift_cm-1', data=x, compression='gzip', shuffle=True)
        h5.create_dataset('map/current', data=np.asarray(area_current, float), compression='gzip', shuffle=True)
        h5.create_dataset('map/original', data=np.asarray(area_original, float), compression='gzip', shuffle=True)
        h5.create_dataset('spectral_cube/current', data=cube_cur, compression='gzip', shuffle=True, chunks=(1, min(nx, 8), min(x.size, 256)))
        h5.create_dataset('spectral_cube/session_open', data=cube_open, compression='gzip', shuffle=True, chunks=(1, min(nx, 8), min(x.size, 256)))
        h5.create_dataset('selected_band_indices', data=np.asarray(band_indices, dtype=np.int64))
        h5.attrs['axis_order'] = 'y_pixel, x_pixel, raman_shift'
    return path

def _write_mat_raman_map(path, b_current, b_open, area_current, area_original, nx, ny, band_indices, metadata=None):
    try:
        from scipy.io import savemat
    except Exception as exc:
        raise ImportError("MATLAB MAT export requires SciPy.") from exc
    mt = int(nx)*int(ny)
    payload = {
        'IMESPEC_schema': 'IMESPEC Raman Map MATLAB Export',
        'metadata_json': json.dumps(metadata or {}, ensure_ascii=False, default=_json_default),
        'raman_shift_cm_1': np.asarray(b_current[:, 0], dtype=np.float64),
        'spectra_current': np.asarray(b_current[:, 1:mt+1], dtype=np.float64),
        'spectra_session_open': np.asarray(b_open[:, 1:mt+1], dtype=np.float64),
        'map_current': np.asarray(area_current, dtype=np.float64),
        'map_original': np.asarray(area_original, dtype=np.float64),
        'nx': np.asarray([[int(nx)]], dtype=np.int32),
        'ny': np.asarray([[int(ny)]], dtype=np.int32),
        'selected_band_indices': np.asarray(band_indices, dtype=np.int32),
    }
    savemat(path, payload, do_compression=True, long_field_names=True)
    return path

def _write_xlsx_raman_map(path, area_current, area_original, metadata=None, cosmic_history=None, bad_pixel_history=None):
    try:
        from openpyxl import Workbook
    except Exception as exc:
        raise ImportError("Excel XLSX export requires the optional package openpyxl.") from exc
    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    ws.append(['IMESPEC Raman Map Export'])
    ws.append(['Metadata JSON'])
    ws.append([json.dumps(metadata or {}, ensure_ascii=False, default=_json_default)])
    for title, arr in [('Map_Current', area_current), ('Map_Original', area_original)]:
        sh = wb.create_sheet(title)
        arr = np.asarray(arr, dtype=float)
        sh.append(['y\\x'] + list(range(arr.shape[1])))
        for iy, row in enumerate(arr):
            sh.append([iy] + [float(v) for v in row])
    sh = wb.create_sheet('Cosmic_Rays')
    sh.append(['apply_pass','spectrum','peak_index','raman_shift_cm-1','start_index','end_index'])
    for pass_no, report in enumerate(cosmic_history or [], start=1):
        for item in report.get('spectra', []):
            shifts = list(item.get('raman_shift', []))
            for idx, ev in enumerate(item.get('events', [])):
                shift = shifts[idx] if idx < len(shifts) else ''
                sh.append([pass_no, item.get('spectrum',''), ev.get('peak_index',''), shift, ev.get('start_index',''), ev.get('end_index','')])
    sh = wb.create_sheet('Bad_Pixels')
    sh.append(['sequence','mode','x_pixel','y_pixel','old_value','new_value','method'])
    for idx, item in enumerate(bad_pixel_history or [], start=1):
        sh.append([idx,item.get('mode',''),item.get('x_pixel',''),item.get('y_pixel',''),item.get('old_value',''),item.get('new_value',''),item.get('method','')])
    wb.save(path)
    return path

def exportar_multiespectros_formatos(
    pasta_pai,
    nome_base,
    formatos,
    dados_quantitativos,
    dados_exibicao=None,
    caminhos=None,
    metadata=None,
    cosmic_report=None,
    software_version="unknown",
):
    """Export Multi-Spectra data to one or more established interchange formats."""
    formatos = _normalizar_formatos_exportacao(formatos)
    if not formatos:
        raise ValueError("Select at least one export format.")
    if len(dados_quantitativos) < 2 or len(dados_quantitativos) % 2:
        raise ValueError("Invalid Multi-Spectra quantitative data.")
    n = len(dados_quantitativos)//2
    caminhos = list(caminhos or [])
    nomes = [os.path.basename(caminhos[p]) if p < len(caminhos) else f"Spectrum_{p+1:03d}" for p in range(n)]
    pasta = _diretorio_exportacao_unico(pasta_pai, nome_base)
    base = _safe_export_name(nome_base, 'IMESPEC_MultiSpectra')
    meta = dict(metadata or {})
    meta.update({
        'schema': 'IMESPEC Multi-Spectra Multi-Format Export',
        'schema_version': _EXPORT_SCHEMA_VERSION,
        'software_version': software_version,
        'exported_at_utc': datetime.now(timezone.utc).isoformat(),
        'formats_requested': formatos,
        'spectra_count': n,
        'sources': [
            {'spectrum': p+1, 'file': nomes[p], 'sha256': _sha256_file(caminhos[p]) if p < len(caminhos) else None}
            for p in range(n)
        ],
        'vertical_distribution_note': 'Display-only data are exported separately and never replace quantitative intensities.',
    })
    criados, avisos = [], []
    def add(path):
        criados.append(os.path.relpath(path, pasta).replace(os.sep, '/'))
        return path
    # Metadata is always present, regardless of chosen data formats.
    meta_path = os.path.join(pasta, f"{base}_metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, default=_json_default)
    add(meta_path)
    if 'csv' in formatos:
        path = os.path.join(pasta, f"{base}_spectra_long.csv")
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['spectrum','file','raman_shift_cm-1','intensity_au'])
            for p in range(n):
                x = np.asarray(dados_quantitativos[2*p], float); y = np.asarray(dados_quantitativos[2*p+1], float)
                for xx, yy in zip(x, y):
                    w.writerow([p+1, nomes[p], f"{float(xx):.12g}", f"{float(yy):.12g}"])
        add(path)
        wide = os.path.join(pasta, f"{base}_spectra_wide.csv")
        if _write_multispectra_wide(wide, dados_quantitativos, nomes, ','):
            add(wide)
    if 'tsv' in formatos:
        path = os.path.join(pasta, f"{base}_spectra_long.tsv")
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, delimiter='\t')
            w.writerow(['spectrum','file','raman_shift_cm-1','intensity_au'])
            for p in range(n):
                x = np.asarray(dados_quantitativos[2*p], float); y = np.asarray(dados_quantitativos[2*p+1], float)
                for xx, yy in zip(x, y):
                    w.writerow([p+1, nomes[p], f"{float(xx):.12g}", f"{float(yy):.12g}"])
        add(path)
        wide = os.path.join(pasta, f"{base}_spectra_wide.tsv")
        if _write_multispectra_wide(wide, dados_quantitativos, nomes, '\t'):
            add(wide)
    if 'txt' in formatos:
        sub = os.path.join(pasta, 'TXT_ASCII'); os.makedirs(sub, exist_ok=True)
        for p in range(n):
            stem = _safe_export_name(nomes[p], f"spectrum_{p+1:03d}")
            add(_write_text_xy(os.path.join(sub, f"{p+1:03d}_{stem}.txt"), dados_quantitativos[2*p], dados_quantitativos[2*p+1], '\t', True))
    if 'jcamp' in formatos:
        sub = os.path.join(pasta, 'JCAMP_DX'); os.makedirs(sub, exist_ok=True)
        for p in range(n):
            stem = _safe_export_name(nomes[p], f"spectrum_{p+1:03d}")
            add(escrever_jcamp_dx(
                os.path.join(sub, f"{p+1:03d}_{stem}.jdx"),
                dados_quantitativos[2*p], dados_quantitativos[2*p+1],
                title=nomes[p],
                metadata={'spectrum_number': p+1, 'software_version': software_version},
            ))
    if 'spc' in formatos:
        if _axes_multiespectros_iguais(dados_quantitativos):
            x = np.asarray(dados_quantitativos[0], float)
            ys = np.vstack([np.asarray(dados_quantitativos[2*p+1], float) for p in range(n)])
            add(_write_spc_multifile(os.path.join(pasta, f"{base}.spc"), x, ys, f"IMESPEC Multi-Spectra ({n} traces)"))
        else:
            sub = os.path.join(pasta, 'SPC'); os.makedirs(sub, exist_ok=True)
            for p in range(n):
                stem = _safe_export_name(nomes[p], f"spectrum_{p+1:03d}")
                add(_write_spc_file(os.path.join(sub, f"{p+1:03d}_{stem}.spc"), dados_quantitativos[2*p], dados_quantitativos[2*p+1], nomes[p]))
            avisos.append('SPC was exported as individual files because Raman-shift axes differ between spectra.')
    if 'mat' in formatos:
        add(_write_mat_multispectra(os.path.join(pasta, f"{base}.mat"), dados_quantitativos, nomes, meta, dados_exibicao))
    if 'hdf5' in formatos:
        add(_write_hdf5_multispectra(os.path.join(pasta, f"{base}.h5"), dados_quantitativos, nomes, meta, dados_exibicao))
    if 'xlsx' in formatos:
        add(_write_xlsx_multispectra(os.path.join(pasta, f"{base}.xlsx"), dados_quantitativos, nomes, meta, dados_exibicao))
    if 'npz' in formatos:
        payload = {'metadata_json': np.asarray(json.dumps(meta, ensure_ascii=False, default=_json_default))}
        for p in range(n):
            payload[f'x_{p+1:04d}'] = np.asarray(dados_quantitativos[2*p], dtype=float)
            payload[f'y_{p+1:04d}'] = np.asarray(dados_quantitativos[2*p+1], dtype=float)
            if dados_exibicao is not None:
                payload[f'y_display_{p+1:04d}'] = np.asarray(dados_exibicao[2*p+1], dtype=float)
        path = os.path.join(pasta, f"{base}.npz")
        np.savez_compressed(path, **payload); add(path)
    for fmt in ('png','svg','pdf'):
        if fmt in formatos:
            path = os.path.join(pasta, f"{base}_quantitative.{fmt}")
            with open(path, 'wb') as f:
                f.write(_figure_bytes_multispectra(dados_quantitativos, nomes, 'Multi-Spectra — Quantitative', fmt))
            add(path)
            if dados_exibicao is not None:
                path2 = os.path.join(pasta, f"{base}_display.{fmt}")
                with open(path2, 'wb') as f:
                    f.write(_figure_bytes_multispectra(dados_exibicao, nomes, 'Multi-Spectra — Display only', fmt))
                add(path2)
    if 'zip' in formatos:
        result = exportar_pacote_multiespectros(
            os.path.join(pasta, f"{base}_analysis_package.zip"),
            dados_quantitativos,
            dados_exibicao=dados_exibicao,
            caminhos=caminhos,
            metadata=meta,
            cosmic_report=cosmic_report,
            software_version=software_version,
        )
        add(result['path'])
    manifest = _write_manifest(pasta, {'formats': formatos, 'warnings': avisos})
    add(manifest)
    return {'directory': pasta, 'files': criados, 'warnings': avisos, 'metadata': meta}

def exportar_raman_mapa_formatos(
    pasta_pai,
    nome_base,
    formatos,
    b_atual,
    b_sessao,
    area_atual,
    area_original,
    xstart,
    xstop,
    nx,
    ny,
    source_path=None,
    cosmic_history=None,
    bad_pixel_history=None,
    processing_history=None,
    display_limits=None,
    robust_display=False,
    software_version="unknown",
):
    """Export a Raman map/hyperspectral cube to several established formats."""
    formatos = _normalizar_formatos_exportacao(formatos)
    if not formatos:
        raise ValueError("Select at least one export format.")
    b_atual = np.asarray(b_atual)
    b_sessao = np.asarray(b_sessao)
    area_atual = np.asarray(area_atual, dtype=float)
    area_original = np.asarray(area_original, dtype=float)
    nx, ny = int(nx), int(ny); mt = nx*ny
    if b_atual.ndim != 2 or b_atual.shape[1] < mt+1 or b_sessao.shape != b_atual.shape:
        raise ValueError("Raman spectral matrix does not match the confirmed map geometry.")
    if area_atual.shape != (ny, nx) or area_original.shape != (ny, nx):
        raise ValueError("Raman map dimensions do not match the confirmed geometry.")
    x = np.asarray(b_atual[:,0], dtype=float)
    i0, i1 = sorted((int(xstart), int(xstop)))
    if not (0 <= i0 < i1 < x.size):
        raise ValueError("Selected Raman band indices are invalid.")
    raman_start, raman_end = sorted((float(x[i0]), float(x[i1])))
    pasta = _diretorio_exportacao_unico(pasta_pai, nome_base)
    base = _safe_export_name(nome_base, 'IMESPEC_RamanMap')
    cosmic_history = list(cosmic_history or [])
    bad_pixel_history = list(bad_pixel_history or [])
    processing_history = list(processing_history or [])
    meta = {
        'schema': 'IMESPEC Raman Map Multi-Format Export',
        'schema_version': _EXPORT_SCHEMA_VERSION,
        'software_version': software_version,
        'exported_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_file': os.path.basename(source_path) if source_path else None,
        'source_sha256': _sha256_file(source_path),
        'geometry': {'nx':nx,'ny':ny,'spectra_used':mt},
        'selected_band': {'start_cm-1':raman_start,'end_cm-1':raman_end,'start_index':i0,'end_index':i1},
        'processing_history': processing_history,
        'bad_pixel_note': 'Bad Pixel Repair changes map values only; underlying spectra remain unchanged.',
        'formats_requested': formatos,
    }
    criados, avisos = [], []
    def add(path):
        criados.append(os.path.relpath(path, pasta).replace(os.sep, '/')); return path
    meta_path = os.path.join(pasta, f"{base}_metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, default=_json_default)
    add(meta_path)
    if 'csv' in formatos:
        path = os.path.join(pasta, f"{base}_map_matrix.csv")
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w=csv.writer(f); w.writerow(['y\\x']+list(range(nx)))
            for iy,row in enumerate(area_atual): w.writerow([iy]+[f"{float(v):.12g}" for v in row])
        add(path)
        path = os.path.join(pasta, f"{base}_map_long.csv")
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w=csv.writer(f); w.writerow(['x_pixel','y_pixel','integrated_area_au_cm-1'])
            for iy in range(ny):
                for ix in range(nx): w.writerow([ix,iy,f"{float(area_atual[iy,ix]):.12g}"])
        add(path)
    if 'tsv' in formatos:
        path = os.path.join(pasta, f"{base}_map_long.tsv")
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w=csv.writer(f, delimiter='\t'); w.writerow(['x_pixel','y_pixel','integrated_area_au_cm-1'])
            for iy in range(ny):
                for ix in range(nx): w.writerow([ix,iy,f"{float(area_atual[iy,ix]):.12g}"])
        add(path)
    if 'txt' in formatos:
        path = os.path.join(pasta, f"{base}_selected_band_spectra.txt")
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('#X\t#Y\t#Wave\t#Intensity\n')
            for sidx in range(1, mt+1):
                p=sidx-1; ix=p%nx; iy=p//nx
                for k in range(i0, i1+1):
                    f.write(f"{ix}\t{iy}\t{float(x[k]):.12g}\t{float(b_atual[k,sidx]):.12g}\n")
        add(path)
        total = int(x.size)*mt
        if total <= 5_000_000:
            path2 = os.path.join(pasta, f"{base}_spectral_map_long.txt")
            with open(path2, 'w', encoding='utf-8', newline='\n') as f:
                f.write('#X\t#Y\t#Wave\t#Intensity\n')
                for sidx in range(1, mt+1):
                    p=sidx-1; ix=p%nx; iy=p//nx
                    for k in range(x.size):
                        f.write(f"{ix}\t{iy}\t{float(x[k]):.12g}\t{float(b_atual[k,sidx]):.12g}\n")
            add(path2)
        else:
            avisos.append('Full four-column TXT spectral map was skipped because it would exceed 5,000,000 rows; selected-band TXT, HDF5/MAT/NPZ remain available.')
    if 'jcamp' in formatos:
        sub = os.path.join(pasta, 'JCAMP_DX_pixels'); os.makedirs(sub, exist_ok=True)
        if mt > 500:
            avisos.append(f'JCAMP-DX creates one file per map pixel ({mt} files). HDF5 or SPC is more convenient for whole-map exchange.')
        for sidx in range(1, mt+1):
            p=sidx-1; ix=p%nx; iy=p//nx
            add(escrever_jcamp_dx(
                os.path.join(sub, f"pixel_y{iy:04d}_x{ix:04d}.jdx"), x, b_atual[:,sidx],
                title=f"{os.path.basename(source_path) if source_path else base} pixel x={ix} y={iy}",
                metadata={'x_pixel':ix,'y_pixel':iy,'software_version':software_version},
            ))
    if 'spc' in formatos:
        ys = np.asarray(b_atual[:,1:mt+1], dtype=float).T
        add(_write_spc_multifile(os.path.join(pasta, f"{base}_spectral_map.spc"), x, ys, f"IMESPEC Raman map {nx}x{ny}; row-major pixels"))
    if 'mat' in formatos:
        add(_write_mat_raman_map(os.path.join(pasta, f"{base}.mat"), b_atual, b_sessao, area_atual, area_original, nx, ny, [i0,i1], meta))
    if 'hdf5' in formatos:
        add(_write_hdf5_raman_map(os.path.join(pasta, f"{base}.h5"), b_atual, b_sessao, area_atual, area_original, nx, ny, [i0,i1], meta))
    if 'xlsx' in formatos:
        add(_write_xlsx_raman_map(os.path.join(pasta, f"{base}.xlsx"), area_atual, area_original, meta, cosmic_history, bad_pixel_history))
    if 'npz' in formatos:
        path = os.path.join(pasta, f"{base}.npz")
        np.savez_compressed(path,
            raman_shift=np.asarray(x,float),
            spectra_current=np.asarray(b_atual[:,1:mt+1],float),
            spectra_session_open=np.asarray(b_sessao[:,1:mt+1],float),
            map_current=np.asarray(area_atual,float),
            map_original=np.asarray(area_original,float),
            nx=np.asarray(nx), ny=np.asarray(ny), selected_band_indices=np.asarray([i0,i1]),
            metadata_json=np.asarray(json.dumps(meta, ensure_ascii=False, default=_json_default)),
        ); add(path)
    for fmt in ('png','svg','pdf'):
        if fmt in formatos:
            path = os.path.join(pasta, f"{base}_map.{fmt}")
            with open(path, 'wb') as f: f.write(_figure_bytes_map(area_atual, raman_start, raman_end, fmt, display_limits))
            add(path)
    if 'zip' in formatos:
        result = exportar_pacote_raman_mapa(
            os.path.join(pasta, f"{base}_analysis_package.zip"),
            b_atual=b_atual, b_sessao=b_sessao,
            area_atual=area_atual, area_original=area_original,
            xstart=i0, xstop=i1, nx=nx, ny=ny,
            source_path=source_path, cosmic_history=cosmic_history,
            bad_pixel_history=bad_pixel_history, processing_history=processing_history,
            display_limits=display_limits, robust_display=robust_display,
            software_version=software_version,
        ); add(result['path'])
    manifest = _write_manifest(pasta, {'formats':formatos,'warnings':avisos}); add(manifest)
    return {'directory':pasta,'files':criados,'warnings':avisos,'metadata':meta}

# ============================================================
# PARTE 1 — MAPA RAMAN
# ============================================================
# Limiares internos da detecção automática.
# Eles ficam escondidos da interface porque o usuário não deve
# precisar "chutar" um parâmetro estatístico para usar o programa.
# A detecção é propositalmente conservadora: um candidato precisa
# parecer anômalo no mapa E apresentar uma feição espectral estreita
# e isolada no espectro bruto.
_AUTO_MAP_Z = 6.0
_AUTO_SPECTRAL_Z = 12.0
_AUTO_MAX_PEAK_WIDTH = 5
_AUTO_SHARED_PEAK_LIMIT = 3

def _pixel_mais_proximo(valor):
    """Converte a coordenada contínua do clique para o pixel mais próximo."""
    return int(np.floor(float(valor) + 0.5))

def _vizinhos_8(area, linha, coluna):
    valores = []
    for dl in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dl == 0 and dc == 0:
                continue
            valores.append(area[linha + dl, coluna + dc])
    return np.asarray(valores, dtype=float)

def _escala_robusta(valores):
    """
    Retorna mediana e uma escala robusta baseada em MAD.
    Se o MAD for nulo, usa o desvio padrão apenas como fallback.
    """
    valores = np.asarray(valores, dtype=float)
    valores = valores[np.isfinite(valores)]
    if valores.size == 0:
        return 0.0, 1.0
    mediana = float(np.median(valores))
    mad = float(np.median(np.abs(valores - mediana)))
    escala = 1.4826 * mad
    if not np.isfinite(escala) or escala <= np.finfo(float).eps:
        escala = float(np.std(valores))
    if not np.isfinite(escala) or escala <= np.finfo(float).eps:
        escala = 1.0
    return mediana, escala

def _connected_component_sizes(mask):
    """Return 8-connected component size for each True pixel in a 2-D mask."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("Connected-component mask must be two-dimensional.")
    sizes = {}
    visited = set()
    rows, cols = mask.shape
    for row, col in zip(*np.nonzero(mask)):
        key = (int(row), int(col))
        if key in visited:
            continue
        stack = [key]
        visited.add(key)
        component = []
        while stack:
            r, c = stack.pop()
            component.append((r, c))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    rr, cc = r + dr, c + dc
                    neighbor = (rr, cc)
                    if (
                        0 <= rr < rows
                        and 0 <= cc < cols
                        and mask[rr, cc]
                        and neighbor not in visited
                    ):
                        visited.add(neighbor)
                        stack.append(neighbor)
        component_size = len(component)
        for item in component:
            sizes[item] = component_size
    return sizes

def detectar_pixels_anomalos(
    area,
    z_limite=6.0,
    min_relative_deviation=0.20,
    max_cluster_size=2,
    outside_scale=1.5,
    return_diagnostics=False,
):
    """
    Detect isolated spatial outlier candidates in a Raman map.

    The previous detector normalized every pixel by one global residual scale.
    On maps with a real, smooth Raman hotspot this global scale can be tiny,
    causing many legitimate high-intensity pixels to be flagged together.

    This version is deliberately conservative. A candidate must satisfy all of
    the following:
      1. large deviation from the median of its eight neighbors;
      2. large deviation relative to the LOCAL robust neighbor spread;
      3. meaningful relative contrast, so tiny numerical differences are ignored;
      4. lie outside the local neighbor envelope by a safety margin;
      5. remain spatially isolated (large connected regions are protected).

    Nothing is modified. When ``return_diagnostics=True`` the function also
    returns counts explaining how many preliminary candidates were protected as
    coherent spatial structures.
    """
    area = np.asarray(area, dtype=float)
    if area.ndim != 2 or min(area.shape) < 3:
        empty = []
        diagnostics = {
            "preliminary_count": 0,
            "suppressed_cluster_count": 0,
            "global_scale_floor": np.nan,
        }
        return (empty, diagnostics) if return_diagnostics else empty
    z_limite = float(z_limite)
    min_relative_deviation = float(min_relative_deviation)
    max_cluster_size = int(max_cluster_size)
    outside_scale = float(outside_scale)
    if not np.isfinite(z_limite) or z_limite <= 0:
        raise ValueError("Bad-pixel z threshold must be positive and finite.")
    if not np.isfinite(min_relative_deviation) or min_relative_deviation < 0:
        raise ValueError("Bad-pixel relative-deviation threshold must be finite and non-negative.")
    if max_cluster_size < 1:
        raise ValueError("Bad-pixel maximum cluster size must be at least 1.")
    if not np.isfinite(outside_scale) or outside_scale < 0:
        raise ValueError("Bad-pixel outside-neighborhood margin must be finite and non-negative.")
    # A small global floor prevents divisions by a near-zero local MAD on very
    # flat maps. It is intentionally only a floor; the local neighborhood scale
    # dominates wherever the map has a genuine gradient or hotspot.
    residuals = []
    for row in range(1, area.shape[0] - 1):
        for col in range(1, area.shape[1] - 1):
            center = float(area[row, col])
            neighbors = _vizinhos_8(area, row, col)
            finite_neighbors = neighbors[np.isfinite(neighbors)]
            if not np.isfinite(center) or finite_neighbors.size < 5:
                continue
            residuals.append(center - float(np.median(finite_neighbors)))
    finite_area = np.where(np.isfinite(area), area, np.nan)
    adjacent_differences = []
    horizontal = finite_area[:, 1:] - finite_area[:, :-1]
    vertical = finite_area[1:, :] - finite_area[:-1, :]
    for block in (horizontal, vertical):
        values = np.asarray(block, dtype=float).ravel()
        values = values[np.isfinite(values)]
        if values.size:
            adjacent_differences.extend(values.tolist())
    _, residual_scale = _escala_robusta(residuals)
    _, adjacent_scale = _escala_robusta(adjacent_differences)
    scale_floor = max(
        0.50 * float(residual_scale),
        0.25 * float(adjacent_scale),
        np.finfo(float).eps,
    )
    preliminary = []
    candidate_mask = np.zeros(area.shape, dtype=bool)
    for row in range(1, area.shape[0] - 1):
        for col in range(1, area.shape[1] - 1):
            center = float(area[row, col])
            neighbors = _vizinhos_8(area, row, col)
            neighbors = neighbors[np.isfinite(neighbors)]
            if not np.isfinite(center) or neighbors.size < 5:
                continue
            local_median = float(np.median(neighbors))
            local_mad = 1.4826 * float(np.median(np.abs(neighbors - local_median)))
            q25, q75 = np.percentile(neighbors, [25.0, 75.0])
            iqr_scale = float((q75 - q25) / 1.349) if q75 > q25 else 0.0
            local_scale = max(local_mad, iqr_scale, scale_floor)
            difference = center - local_median
            z_local = abs(difference) / local_scale
            relative_deviation = abs(difference) / (
                abs(local_median) + local_scale + np.finfo(float).eps
            )
            lower_neighbor = float(np.min(neighbors))
            upper_neighbor = float(np.max(neighbors))
            outside_envelope = (
                center < lower_neighbor - outside_scale * local_scale
                or center > upper_neighbor + outside_scale * local_scale
            )
            if (
                z_local >= z_limite
                and relative_deviation >= min_relative_deviation
                and outside_envelope
            ):
                candidate_mask[row, col] = True
                preliminary.append({
                    "linha": row,
                    "coluna": col,
                    "z_espacial": float(z_local),
                    "z_local": float(z_local),
                    "relative_deviation": float(relative_deviation),
                    "valor": center,
                    "mediana_local": local_median,
                    "local_scale": float(local_scale),
                })
    component_sizes = _connected_component_sizes(candidate_mask)
    candidates = []
    suppressed = 0
    for candidate in preliminary:
        key = (candidate["linha"], candidate["coluna"])
        cluster_size = int(component_sizes.get(key, 1))
        candidate["cluster_size"] = cluster_size
        if cluster_size <= max_cluster_size:
            candidates.append(candidate)
        else:
            suppressed += 1
    diagnostics = {
        "preliminary_count": len(preliminary),
        "suppressed_cluster_count": suppressed,
        "global_scale_floor": float(scale_floor),
        "max_cluster_size": max_cluster_size,
    }
    return (candidates, diagnostics) if return_diagnostics else candidates

def _ruido_espectral_robusto(y):
    """Estima o ruído de alta frequência a partir da primeira diferença."""
    y = np.asarray(y, dtype=float)
    if y.ndim != 1 or y.size < 4:
        return 1.0
    d = np.diff(y)
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med)))
    escala = 1.4826 * mad
    if not np.isfinite(escala) or escala <= np.finfo(float).eps:
        escala = float(np.std(d))
    if not np.isfinite(escala) or escala <= np.finfo(float).eps:
        escala = 1.0
    return escala

def _detectar_eventos_cosmic_espectro(y, threshold=10.0, max_width=3.0):
    """
    Detecta spikes positivos, estreitos e proeminentes em um espectro.

    Esta versão abandona a classificação direta por modified z-score da
    derivada, que pode gerar muitos falsos positivos em bandas Raman reais.
    O screening usa duas características clássicas de cosmic rays:
      * proeminência grande em relação ao ruído local;
      * largura espectral muito pequena (FWHM em pontos).

    A etapa de mapa ainda aplica uma validação espacial adicional usando
    espectros vizinhos. Em Multi-Spectra, feições estreitas compartilhadas
    entre muitos espectros da série são protegidas.
    """
    y = np.asarray(y, dtype=float)
    threshold = float(threshold)
    max_width = float(max_width)
    if y.ndim != 1 or y.size < 5:
        return []
    if not np.all(np.isfinite(y)):
        raise ValueError("Cosmic-ray detection requires finite intensity values.")
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Cosmic-ray threshold must be positive and finite.")
    if not np.isfinite(max_width) or max_width <= 0:
        raise ValueError("Maximum cosmic-ray width must be positive and finite.")
    if not _SCIPY_AVAILABLE or find_peaks is None or peak_widths is None:
        raise RuntimeError("SciPy is required for the narrow-spike cosmic-ray detector.")
    ruido = _ruido_espectral_robusto(y)
    prominencia_min = threshold * ruido
    picos, props = find_peaks(
        y,
        prominence=prominencia_min,
        width=(0.0, max_width),
    )
    eventos = []
    for i, pico in enumerate(picos):
        pico = int(pico)
        largura = float(props["widths"][i])
        prominencia = float(props["prominences"][i])
        # A extensão usada para correção é medida em um nível mais baixo
        # (70% da proeminência) para capturar spikes de 2–3 pontos sem
        # alargar artificialmente um evento de um único ponto.
        _, _, left70, right70 = peak_widths(y, [pico], rel_height=0.70)
        inicio = int(np.ceil(float(left70[0])))
        fim = int(np.floor(float(right70[0])))
        inicio = max(0, min(inicio, pico))
        fim = min(y.size - 1, max(fim, pico))
        eventos.append({
            "peak_index": pico,
            "start_index": inicio,
            "end_index": fim,
            "width_points": largura,
            "prominence": prominencia,
            "prominence_noise": prominencia / max(ruido, np.finfo(float).eps),
        })
    return eventos

def _eventos_para_indices(eventos):
    indices = set()
    for evento in eventos:
        indices.update(range(int(evento["start_index"]), int(evento["end_index"]) + 1))
    return sorted(indices)

def _corrigir_eventos_cosmic(y, eventos, kernel_size=3):
    """
    Corrige somente os intervalos confirmados como cosmic ray.

    Cada bloco contaminado é substituído por interpolação entre os pontos
    imediatamente externos ao bloco. Esse procedimento preserva melhor a
    tendência Raman subjacente do que substituir uma banda inteira por uma
    média constante.
    """
    y = np.asarray(y, dtype=float)
    kernel_size = int(kernel_size)
    if kernel_size < 1:
        raise ValueError("Cosmic-ray replacement kernel must be at least 1.")
    corrigido = y.copy()
    if not eventos:
        return corrigido
    intervalos = sorted(
        [[int(e["start_index"]), int(e["end_index"])] for e in eventos],
        key=lambda v: v[0]
    )
    # Une intervalos sobrepostos/adjacentes para não corrigir o mesmo evento
    # em etapas que poderiam contaminar os próprios pontos de referência.
    grupos = []
    for inicio, fim in intervalos:
        if grupos and inicio <= grupos[-1][1] + 1:
            grupos[-1][1] = max(grupos[-1][1], fim)
        else:
            grupos.append([inicio, fim])
    for inicio, fim in grupos:
        esquerda = inicio - 1
        direita = fim + 1
        if esquerda >= 0 and direita < corrigido.size:
            corrigido[inicio:fim + 1] = np.interp(
                np.arange(inicio, fim + 1, dtype=float),
                [float(esquerda), float(direita)],
                [float(corrigido[esquerda]), float(corrigido[direita])]
            )
            continue
        # Fallback para bordas: mediana de pontos válidos próximos.
        lo = max(0, inicio - kernel_size)
        hi = min(corrigido.size, fim + kernel_size + 1)
        vizinhos = np.concatenate((corrigido[lo:inicio], corrigido[fim + 1:hi]))
        if vizinhos.size:
            corrigido[inicio:fim + 1] = float(np.median(vizinhos))
    return corrigido

def _whitaker_hayes_mask(y, threshold=10.0):
    """
    Compatibilidade com versões antigas do IMESPEC.

    A máscara agora usa o detector conservador de spikes estreitos em vez de
    classificar diretamente a derivada como cosmic ray. O nome é mantido
    apenas para não quebrar chamadas externas antigas.
    """
    y = np.asarray(y, dtype=float)
    mascara = np.zeros(y.shape, dtype=bool)
    for evento in _detectar_eventos_cosmic_espectro(y, threshold=threshold, max_width=3.0):
        mascara[evento["start_index"]:evento["end_index"] + 1] = True
    return mascara

def corrigir_cosmic_ray_espectro(y, threshold=10.0, kernel_size=3, max_width=3.0):
    """Detecta e corrige cosmic rays estreitos em um único espectro."""
    eventos = _detectar_eventos_cosmic_espectro(
        y, threshold=threshold, max_width=max_width
    )
    indices = _eventos_para_indices(eventos)
    corrigido = _corrigir_eventos_cosmic(y, eventos, kernel_size=kernel_size)
    return corrigido, indices

def _proteger_picos_compartilhados_multiespectros(f3, eventos_por_espectro):
    """
    Remove da lista feições estreitas que se repetem em muitos espectros.

    Cosmic rays são estocásticos. Já uma linha Raman física muito estreita
    tende a reaparecer em vários espectros da mesma série. Essa proteção é
    aplicada apenas ao Multi-Spectra, onde não existe geometria espacial.
    """
    numero = len(eventos_por_espectro)
    if numero < 3:
        return eventos_por_espectro
    # Para séries pequenas, exigimos ao menos 3 espectros compartilhando a
    # feição. Para séries maiores, a proteção cresce suavemente com o tamanho.
    outros_necessarios = max(2, int(np.ceil(0.15 * numero)))
    saida = []
    shifts_por_espectro = []
    tolerancias = []
    for p in range(numero):
        x = np.asarray(f3[2 * p], dtype=float)
        passo = float(np.median(np.abs(np.diff(x)))) if x.size > 1 else 1.0
        tolerancias.append(max(1.5 * passo, np.finfo(float).eps))
        shifts_por_espectro.append([
            float(x[e["peak_index"]]) for e in eventos_por_espectro[p]
            if 0 <= int(e["peak_index"]) < x.size
        ])
    for p, eventos in enumerate(eventos_por_espectro):
        x = np.asarray(f3[2 * p], dtype=float)
        mantidos = []
        for evento in eventos:
            shift = float(x[int(evento["peak_index"])])
            compartilhado = 0
            for q in range(numero):
                if q == p:
                    continue
                tol = max(tolerancias[p], tolerancias[q])
                if any(abs(shift - s) <= tol for s in shifts_por_espectro[q]):
                    compartilhado += 1
            if compartilhado < outros_necessarios:
                mantidos.append(evento)
        saida.append(mantidos)
    return saida

def detectar_cosmic_rays_multiespectros(
    f3,
    threshold=10.0,
    max_width=3.0,
    prominence_width_factor=2.0,
    max_repair_points=5,
):
    """
    Detect conservative narrow spikes in ``[x1,y1,x2,y2,...]``.

    In addition to prominence/FWHM and recurrence protection, the accepted
    correction span is capped. This prevents a narrow FWHM candidate from
    requesting interpolation across a much wider interval at the lower
    prominence level used to define the repair range.
    """
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    threshold = float(threshold)
    max_width = float(max_width)
    prominence_width_factor = float(prominence_width_factor)
    max_repair_points = max(1, int(max_repair_points))
    if threshold <= 0 or not np.isfinite(threshold):
        raise ValueError("Cosmic-ray threshold must be positive and finite.")
    if max_width <= 0 or not np.isfinite(max_width):
        raise ValueError("Maximum cosmic-ray FWHM must be positive and finite.")
    if prominence_width_factor <= 0 or not np.isfinite(prominence_width_factor):
        raise ValueError("Prominence/width factor must be positive and finite.")
    ratio_minimo = threshold * prominence_width_factor
    eventos_por_espectro = []
    rejeitados_span = 0
    rejeitados_ratio = 0
    for p in range(len(f3) // 2):
        y = np.asarray(f3[2 * p + 1], dtype=float)
        eventos_raw = _detectar_eventos_cosmic_espectro(
            y, threshold=threshold, max_width=max_width
        )
        eventos = []
        for evento_original in eventos_raw:
            evento = dict(evento_original)
            inicio = int(evento["start_index"])
            fim = int(evento["end_index"])
            span = fim - inicio + 1
            largura = max(float(evento.get("width_points", 1.0)), 1.0)
            ratio = float(evento.get("prominence_noise", 0.0)) / largura
            evento["repair_span_points"] = span
            evento["prominence_width_score"] = ratio
            if span > max_repair_points:
                rejeitados_span += 1
                continue
            if ratio < ratio_minimo:
                rejeitados_ratio += 1
                continue
            eventos.append(evento)
        eventos_por_espectro.append(
            _mesclar_eventos_cosmic_sobrepostos(
                eventos, max_repair_points=max_repair_points
            )
        )
    antes_protecao = sum(len(v) for v in eventos_por_espectro)
    eventos_por_espectro = _proteger_picos_compartilhados_multiespectros(
        f3, eventos_por_espectro
    )
    depois_protecao = sum(len(v) for v in eventos_por_espectro)
    detalhes = []
    total_eventos = 0
    total_pontos = 0
    for p, eventos in enumerate(eventos_por_espectro):
        if not eventos:
            continue
        x = np.asarray(f3[2 * p], dtype=float)
        indices = _eventos_para_indices(eventos)
        centros = [int(e["peak_index"]) for e in eventos]
        detalhes.append({
            "spectrum": p + 1,
            "indices": indices,
            "event_centers": centros,
            "raman_shift": [float(x[i]) for i in centros if i < x.size],
            "events": eventos,
        })
        total_eventos += len(eventos)
        total_pontos += len(indices)
    return {
        "total_events": int(total_eventos),
        "total_points": int(total_pontos),
        "spectra": detalhes,
        "method": "narrow_spike_prominence_fwhm_series_validation_safe_span",
        "diagnostics": {
            "max_repair_points": int(max_repair_points),
            "prominence_width_min_score": float(ratio_minimo),
            "rejected_wide_repair_span": int(rejeitados_span),
            "rejected_low_prominence_width": int(rejeitados_ratio),
            "protected_shared_events": int(max(0, antes_protecao - depois_protecao)),
        },
    }

def _normalizar_relatorio_cosmic_multiespectros(relatorio, f3, max_repair_points=5):
    """Validate and freeze a reviewed Multi-Spectra cosmic-ray report."""
    if not isinstance(relatorio, dict):
        raise ValueError("Invalid cosmic-ray detection report.")
    numero = len(f3) // 2
    frozen = copy.deepcopy(relatorio)
    detalhes = []
    vistos = set()
    total_eventos = 0
    total_pontos = 0
    max_repair_points = max(1, int(max_repair_points))
    for item in frozen.get("spectra", []):
        if not isinstance(item, dict) or "spectrum" not in item:
            raise ValueError("Malformed cosmic-ray report: missing spectrum identifier.")
        spectrum = int(item["spectrum"])
        if not 1 <= spectrum <= numero or spectrum in vistos:
            raise ValueError("Malformed cosmic-ray report: invalid or duplicated spectrum identifier.")
        vistos.add(spectrum)
        y = np.asarray(f3[2 * (spectrum - 1) + 1])
        events = []
        indices = set()
        for raw in item.get("events", []):
            e = dict(raw)
            peak = int(e["peak_index"])
            start = int(e["start_index"])
            end = int(e["end_index"])
            if not (0 <= start <= peak <= end < y.size):
                raise ValueError("Malformed cosmic-ray report: event interval is outside a spectrum.")
            span = end - start + 1
            if span > max_repair_points:
                raise ValueError(
                    f"Unsafe cosmic-ray report: an event requests repair of {span} points "
                    f"(limit {max_repair_points})."
                )
            e["repair_span_points"] = span
            events.append(e)
            indices.update(range(start, end + 1))
        if not events:
            continue
        item_n = dict(item)
        item_n["events"] = events
        item_n["indices"] = sorted(indices)
        item_n["event_centers"] = [int(e["peak_index"]) for e in events]
        detalhes.append(item_n)
        total_eventos += len(events)
        total_pontos += len(indices)
    if int(frozen.get("total_events", total_eventos)) != total_eventos or int(
        frozen.get("total_points", total_pontos)
    ) != total_pontos:
        raise ValueError(
            "Cosmic-ray report consistency check failed. Run Detect again before applying removal."
        )
    frozen["spectra"] = detalhes
    frozen["total_events"] = int(total_eventos)
    frozen["total_points"] = int(total_pontos)
    frozen.setdefault("diagnostics", {})
    frozen["diagnostics"]["validated_report"] = True
    frozen["diagnostics"]["max_repair_points"] = int(max_repair_points)
    return frozen

def corrigir_cosmic_rays_multiespectros(
    f3,
    threshold=10.0,
    kernel_size=3,
    max_width=3.0,
    relatorio=None,
    max_repair_points=5,
):
    """
    Correct confirmed cosmic-ray events in Multi-Spectra data.

    A supplied report is validated and applied exactly as reviewed. If no
    report is supplied, programmatic callers may still request one-pass
    detection+correction; the graphical IMESPEC workflow requires explicit
    Detect before Apply Processing.
    """
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    if relatorio is None:
        relatorio = detectar_cosmic_rays_multiespectros(
            f3,
            threshold=threshold,
            max_width=max_width,
            max_repair_points=max_repair_points,
        )
    relatorio_validado = _normalizar_relatorio_cosmic_multiespectros(
        relatorio, f3, max_repair_points=max_repair_points
    )
    por_espectro = {
        int(item["spectrum"]): item
        for item in relatorio_validado.get("spectra", [])
    }
    saida = []
    for p in range(len(f3) // 2):
        x = np.asarray(f3[2 * p])
        y = np.asarray(f3[2 * p + 1], dtype=float)
        item = por_espectro.get(p + 1)
        if item:
            y = _corrigir_eventos_cosmic(
                y, item.get("events", []), kernel_size=kernel_size
            )
        saida.append(x.copy())
        saida.append(y.copy())
    return saida, relatorio_validado

def _indices_vizinhos_mapa(espectro_zero, nx, ny, numero_espectros):
    linha, coluna = divmod(int(espectro_zero), int(nx))
    vizinhos = []
    for dl in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dl == 0 and dc == 0:
                continue
            l2, c2 = linha + dl, coluna + dc
            if 0 <= l2 < int(ny) and 0 <= c2 < int(nx):
                idx = l2 * int(nx) + c2
                if 0 <= idx < int(numero_espectros):
                    vizinhos.append(idx)
    return vizinhos

def _melhor_vizinho_espectral(alvo, vizinhos):
    """Retorna o vizinho com maior correlação espectral com o alvo."""
    alvo = np.asarray(alvo, dtype=float)
    a = alvo - np.median(alvo)
    norma_a = float(np.linalg.norm(a))
    melhor = None
    melhor_corr = -np.inf
    for vizinho in vizinhos:
        v = np.asarray(vizinho, dtype=float)
        vv = v - np.median(v)
        denom = norma_a * float(np.linalg.norm(vv))
        corr = float(np.dot(a, vv) / denom) if denom > 0 else -1.0
        if corr > melhor_corr:
            melhor_corr = corr
            melhor = v
    return melhor, melhor_corr

def _predicao_robusta_vizinho(alvo, vizinho):
    """Ajusta alvo ≈ a*vizinho+b e retorna predição e escala robusta residual."""
    alvo = np.asarray(alvo, dtype=float)
    vizinho = np.asarray(vizinho, dtype=float)
    A = np.column_stack((vizinho, np.ones_like(vizinho)))
    coef, *_ = np.linalg.lstsq(A, alvo, rcond=None)
    pred = A @ coef
    resid = alvo - pred
    med, escala = _escala_robusta(resid)
    mascara = np.abs(resid - med) < 4.0 * escala
    if np.count_nonzero(mascara) >= 10:
        coef, *_ = np.linalg.lstsq(A[mascara], alvo[mascara], rcond=None)
        pred = A @ coef
        resid = alvo - pred
        _, escala = _escala_robusta(resid)
    return pred, escala

def _referencia_espacial_mediana(b, viz_idx):
    """
    Build a robust reference spectrum from spatial neighbors.

    Using the pointwise median of all available neighbors is more conservative
    than selecting only one "best" neighbor: genuine Raman bands that are
    present in the local region tend to remain in the reference, while a
    stochastic cosmic spike present in only the target spectrum does not.
    """
    if not viz_idx:
        return None
    vizinhos = np.asarray(
        [np.asarray(b[:, int(i) + 1], dtype=float) for i in viz_idx],
        dtype=float,
    )
    if vizinhos.ndim != 2 or vizinhos.shape[0] == 0:
        return None
    return np.median(vizinhos, axis=0)

def _mesclar_eventos_cosmic_sobrepostos(eventos, max_repair_points=5):
    """
    Merge overlapping/adjacent candidate intervals from the same spectrum.

    A multi-point cosmic hit can create more than one local maximum. Reporting
    those maxima as separate cosmic events is confusing and can double-count a
    single artifact. Merging is allowed only when the combined correction span
    remains inside the same conservative safety limit used by the detector.
    """
    if not eventos:
        return []
    max_repair_points = max(1, int(max_repair_points))
    ordenados = sorted(
        [dict(e) for e in eventos],
        key=lambda e: (int(e["start_index"]), int(e["end_index"])),
    )
    grupos = []
    for evento in ordenados:
        inicio = int(evento["start_index"])
        fim = int(evento["end_index"])
        if not grupos:
            grupos.append([evento])
            continue
        atual_inicio = min(int(e["start_index"]) for e in grupos[-1])
        atual_fim = max(int(e["end_index"]) for e in grupos[-1])
        novo_inicio = min(atual_inicio, inicio)
        novo_fim = max(atual_fim, fim)
        if inicio <= atual_fim + 1 and (novo_fim - novo_inicio + 1) <= max_repair_points:
            grupos[-1].append(evento)
        else:
            grupos.append([evento])
    saida = []
    for grupo in grupos:
        if len(grupo) == 1:
            e = dict(grupo[0])
            e["merged_event_count"] = 1
            saida.append(e)
            continue
        principal = max(
            grupo,
            key=lambda e: (
                float(e.get("prominence_noise", 0.0)),
                float(e.get("prominence", 0.0)),
            ),
        )
        combinado = dict(principal)
        combinado["start_index"] = min(int(e["start_index"]) for e in grupo)
        combinado["end_index"] = max(int(e["end_index"]) for e in grupo)
        combinado["repair_span_points"] = (
            int(combinado["end_index"]) - int(combinado["start_index"]) + 1
        )
        combinado["prominence"] = max(float(e.get("prominence", 0.0)) for e in grupo)
        combinado["prominence_noise"] = max(
            float(e.get("prominence_noise", 0.0)) for e in grupo
        )
        combinado["prominence_width_score"] = max(
            float(e.get("prominence_width_score", 0.0)) for e in grupo
        )
        if any("spatial_residual_z" in e for e in grupo):
            combinado["spatial_residual_z"] = max(
                float(e.get("spatial_residual_z", 0.0)) for e in grupo
            )
        combinado["merged_event_count"] = len(grupo)
        saida.append(combinado)
    return saida

def _contagens_compartilhadas_eventos(eventos_por_espectro, tolerancia_pontos=2):
    """
    Count in how many OTHER spectra a candidate occurs at nearly the same
    spectral channel.

    Cosmic rays are stochastic. A narrow feature recurring at the same Raman
    shift across many spectra is much more likely to be a real/systematic
    spectral feature. The tolerance is expressed in spectral samples rather
    than Raman-shift units so it also remains valid for non-uniformly named
    files that share the same X axis internally.
    """
    tolerancia_pontos = max(0, int(tolerancia_pontos))
    indices_por_espectro = {}
    for espectro, eventos in eventos_por_espectro.items():
        indices_por_espectro[int(espectro)] = [
            int(e["peak_index"]) for e in eventos
        ]
    contagens = {}
    for espectro, eventos in eventos_por_espectro.items():
        for pos, evento in enumerate(eventos):
            pico = int(evento["peak_index"])
            outros = 0
            for outro_espectro, indices in indices_por_espectro.items():
                if int(outro_espectro) == int(espectro):
                    continue
                if any(abs(int(indice) - pico) <= tolerancia_pontos for indice in indices):
                    outros += 1
            contagens[(int(espectro), int(pos))] = outros
    return contagens

def _minimo_espectros_para_proteger_pico(numero_espectros):
    """Dataset-size-aware recurrence threshold used by Raman Map protection."""
    numero_espectros = max(1, int(numero_espectros))
    if numero_espectros < 50:
        return 3
    if numero_espectros < 200:
        return 4
    return 5

def detectar_cosmic_rays_matriz(
    b, numero_espectros=None, threshold=10.0, max_width=3.0,
    nx=None, ny=None, spatial_validate=False, spatial_threshold=8.0,
    shared_tolerance_points=2, shared_min_spectra=None,
    prominence_width_factor=2.0, max_repair_points=5,
):
    """
    Detect conservative cosmic-ray candidates in a Raman matrix.

    In Raman-map mode the detector works on a *spatial residual*: each target
    spectrum is compared with the pointwise median of its surrounding map
    spectra, followed by a robust affine alignment. A genuine Raman band that
    is locally shared is therefore largely cancelled, whereas a stochastic
    spike remains as a narrow positive residual.

    Four safeguards are combined:

      1. Prominence/noise and FWHM screening of the spatial residual.
      2. A second robust spatial-residual z threshold.
      3. Shared-feature protection: candidate channels that recur in several
         spectra are treated as likely physical/systematic features.
         Importantly, this recurrence check also uses narrow peaks found in the
         RAW spectra, so a real narrow Raman peak is protected even if local
         intensity variation makes it stand out in one residual spectrum.
      4. Repair-span protection: no automatically accepted event may request
         interpolation over more than ``max_repair_points`` samples.

    The prominence/width score is normalized by spectral noise. With the
    default threshold=10 and factor=2, a candidate needs a score >= 20.

    Nothing is modified by this function.
    """
    b = np.asarray(b)
    if b.ndim != 2 or b.shape[1] < 2:
        raise ValueError("Invalid Raman matrix.")
    threshold = float(threshold)
    max_width = float(max_width)
    spatial_threshold = float(spatial_threshold)
    prominence_width_factor = float(prominence_width_factor)
    max_repair_points = int(max_repair_points)
    shared_tolerance_points = max(0, int(shared_tolerance_points))
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Cosmic-ray threshold must be positive and finite.")
    if not np.isfinite(max_width) or max_width <= 0:
        raise ValueError("Maximum cosmic-ray FWHM must be positive and finite.")
    if not np.isfinite(spatial_threshold) or spatial_threshold <= 0:
        raise ValueError("Spatial cosmic-ray threshold must be positive and finite.")
    if not np.isfinite(prominence_width_factor) or prominence_width_factor <= 0:
        raise ValueError("Prominence/width factor must be positive and finite.")
    if max_repair_points < 1:
        raise ValueError("Maximum repair span must be at least one point.")
    disponiveis = b.shape[1] - 1
    if numero_espectros is None:
        numero_espectros = disponiveis
    numero_espectros = min(int(numero_espectros), disponiveis)
    usar_espacial = (
        bool(spatial_validate) and nx is not None and ny is not None
        and int(nx) * int(ny) >= numero_espectros
    )
    if shared_min_spectra is None:
        shared_min_spectra = _minimo_espectros_para_proteger_pico(numero_espectros)
    shared_min_spectra = max(2, int(shared_min_spectra))
    ratio_minimo = threshold * prominence_width_factor

    # ------------------------------------------------------------------
    # Pass 1: raw narrow peaks are retained only as a recurrence map.
    # They are NOT automatically classified as cosmic rays in Raman-map mode.
    # ------------------------------------------------------------------
    raw_eventos_por_espectro = {}
    total_raw_narrow_peaks = 0
    for espectro_zero in range(numero_espectros):
        y = np.asarray(b[:, espectro_zero + 1], dtype=float)
        eventos_raw = _detectar_eventos_cosmic_espectro(
            y, threshold=threshold, max_width=max_width
        )
        raw_eventos_por_espectro[espectro_zero + 1] = eventos_raw
        total_raw_narrow_peaks += len(eventos_raw)
    candidatos_por_espectro = {}
    rejeitados_span = 0
    rejeitados_ratio = 0
    rejeitados_espaciais = 0

    # ------------------------------------------------------------------
    # Pass 2: actual classification.
    # In a Raman map, detect narrow peaks in the spatial residual rather than
    # in the raw target spectrum. This is the main protection against genuine
    # Raman bands in heterogeneous samples.
    # ------------------------------------------------------------------
    for espectro_zero in range(numero_espectros):
        y = np.asarray(b[:, espectro_zero + 1], dtype=float)
        if usar_espacial:
            viz_idx = _indices_vizinhos_mapa(
                espectro_zero, int(nx), int(ny), numero_espectros
            )
            referencia = _referencia_espacial_mediana(b, viz_idx)
            if referencia is None:
                sinal_deteccao = y
                pred = None
                escala_espacial = _ruido_espectral_robusto(y)
            else:
                pred, escala_espacial = _predicao_robusta_vizinho(y, referencia)
                sinal_deteccao = y - pred
        else:
            sinal_deteccao = y
            pred = None
            escala_espacial = _ruido_espectral_robusto(y)
        eventos = _detectar_eventos_cosmic_espectro(
            sinal_deteccao,
            threshold=threshold,
            max_width=max_width,
        )
        if not eventos:
            continue
        filtrados = []
        for evento_original in eventos:
            evento = dict(evento_original)
            inicio = int(evento["start_index"])
            fim = int(evento["end_index"])
            span = fim - inicio + 1
            largura = max(float(evento.get("width_points", 1.0)), 1.0)
            ratio = float(evento.get("prominence_noise", 0.0)) / largura
            evento["repair_span_points"] = int(span)
            evento["prominence_width_score"] = float(ratio)
            if span > max_repair_points:
                rejeitados_span += 1
                continue
            if ratio < ratio_minimo:
                rejeitados_ratio += 1
                continue
            if usar_espacial and pred is not None:
                excesso = max(float(y[i] - pred[i]) for i in range(inicio, fim + 1))
                z_espacial = excesso / max(
                    float(escala_espacial), np.finfo(float).eps
                )
                if z_espacial < spatial_threshold:
                    rejeitados_espaciais += 1
                    continue
                evento["spatial_residual_z"] = float(z_espacial)
            filtrados.append(evento)
        if filtrados:
            filtrados = _mesclar_eventos_cosmic_sobrepostos(
                filtrados, max_repair_points=max_repair_points
            )
            candidatos_por_espectro[espectro_zero + 1] = filtrados

    # ------------------------------------------------------------------
    # Pass 3: recurrence/shared-feature protection.
    # Build a support map from BOTH raw narrow peaks and residual candidates.
    # A recurring channel is ambiguous/likely physical and is not removed.
    # ------------------------------------------------------------------
    suporte_por_espectro = {}
    for espectro in range(1, numero_espectros + 1):
        indices = [
            int(e["peak_index"])
            for e in raw_eventos_por_espectro.get(espectro, [])
        ]
        indices.extend(
            int(e["peak_index"])
            for e in candidatos_por_espectro.get(espectro, [])
        )
        suporte_por_espectro[espectro] = indices
    protegidos_compartilhados = 0
    eventos_finais_por_espectro = {}
    for espectro, eventos in candidatos_por_espectro.items():
        mantidos = []
        for evento in eventos:
            pico = int(evento["peak_index"])
            compartilhado_total = 0
            for outro_espectro, indices in suporte_por_espectro.items():
                if any(
                    abs(int(indice) - pico) <= shared_tolerance_points
                    for indice in indices
                ):
                    compartilhado_total += 1
            evento = dict(evento)
            evento["shared_spectra_count"] = int(compartilhado_total)
            if compartilhado_total >= shared_min_spectra:
                protegidos_compartilhados += 1
                continue
            mantidos.append(evento)
        if mantidos:
            eventos_finais_por_espectro[int(espectro)] = mantidos
    detalhes = []
    total_eventos = 0
    total_pontos = 0
    for espectro in sorted(eventos_finais_por_espectro):
        eventos = eventos_finais_por_espectro[espectro]
        indices = _eventos_para_indices(eventos)
        centros = [int(e["peak_index"]) for e in eventos]
        detalhes.append({
            "spectrum": int(espectro),
            "indices": indices,
            "event_centers": centros,
            "raman_shift": [float(b[i, 0]) for i in centros],
            "events": eventos,
        })
        total_eventos += len(eventos)
        total_pontos += len(indices)
    return {
        "total_events": int(total_eventos),
        "total_points": int(total_pontos),
        "spectra": detalhes,
        "method": (
            "spatial_residual_prominence_fwhm_shared_peak_protection"
            if usar_espacial
            else "prominence_fwhm_shared_peak_protection"
        ),
        "diagnostics": {
            "spatial_validation": bool(usar_espacial),
            "screening_signal": "spatial_residual" if usar_espacial else "raw_spectrum",
            "raw_narrow_peak_count": int(total_raw_narrow_peaks),
            "shared_tolerance_points": int(shared_tolerance_points),
            "shared_min_spectra": int(shared_min_spectra),
            "prominence_width_min_score": float(ratio_minimo),
            "max_repair_points": int(max_repair_points),
            "protected_shared_events": int(protegidos_compartilhados),
            "rejected_wide_repair_span": int(rejeitados_span),
            "rejected_low_prominence_width": int(rejeitados_ratio),
            "rejected_spatial_validation": int(rejeitados_espaciais),
        },
    }

def _normalizar_relatorio_cosmic(
    relatorio,
    numero_pontos,
    numero_espectros,
    max_repair_points=None,
):
    """
    Validate and deep-copy a reviewed cosmic-ray report.

    The interactive workflow must never apply a stale, malformed, or partially
    modified report. Counts are recomputed from the event intervals rather than
    trusting cached ``total_events`` / ``total_points`` fields. A mismatch is
    treated as an internal consistency error instead of silently changing what
    the user reviewed.
    """
    if not isinstance(relatorio, dict):
        raise ValueError("Invalid cosmic-ray detection report.")
    numero_pontos = int(numero_pontos)
    numero_espectros = int(numero_espectros)
    if numero_pontos < 1 or numero_espectros < 1:
        raise ValueError("Invalid Raman matrix dimensions for cosmic-ray report validation.")
    if max_repair_points is None:
        try:
            max_repair_points = int(
                relatorio.get("diagnostics", {}).get("max_repair_points", 5)
            )
        except Exception:
            max_repair_points = 5
    max_repair_points = max(1, int(max_repair_points))
    frozen = copy.deepcopy(relatorio)
    detalhes_normalizados = []
    espectros_vistos = set()
    total_eventos = 0
    total_pontos = 0
    for item in frozen.get("spectra", []):
        if not isinstance(item, dict) or "spectrum" not in item:
            raise ValueError("Malformed cosmic-ray report: missing spectrum identifier.")
        espectro = int(item["spectrum"])
        if not 1 <= espectro <= numero_espectros:
            raise ValueError(
                f"Malformed cosmic-ray report: spectrum {espectro} is outside the valid range."
            )
        if espectro in espectros_vistos:
            raise ValueError(
                f"Malformed cosmic-ray report: spectrum {espectro} appears more than once."
            )
        espectros_vistos.add(espectro)
        eventos = item.get("events", [])
        if not isinstance(eventos, (list, tuple)):
            raise ValueError("Malformed cosmic-ray report: event list is invalid.")
        eventos_normalizados = []
        indices = set()
        for evento in eventos:
            if not isinstance(evento, dict):
                raise ValueError("Malformed cosmic-ray report: an event is not a mapping.")
            try:
                pico = int(evento["peak_index"])
                inicio = int(evento["start_index"])
                fim = int(evento["end_index"])
            except Exception as exc:
                raise ValueError(
                    "Malformed cosmic-ray report: event indices are missing or invalid."
                ) from exc
            if inicio > fim:
                raise ValueError("Malformed cosmic-ray report: event interval is reversed.")
            if not (0 <= inicio <= pico <= fim < numero_pontos):
                raise ValueError(
                    "Malformed cosmic-ray report: event interval is outside the spectrum."
                )
            span = fim - inicio + 1
            if span > max_repair_points:
                raise ValueError(
                    f"Unsafe cosmic-ray report: an event requests repair of {span} points "
                    f"(limit {max_repair_points})."
                )
            evento_n = dict(evento)
            evento_n["peak_index"] = pico
            evento_n["start_index"] = inicio
            evento_n["end_index"] = fim
            evento_n["repair_span_points"] = span
            eventos_normalizados.append(evento_n)
            indices.update(range(inicio, fim + 1))
        if not eventos_normalizados:
            continue
        item_n = dict(item)
        item_n["spectrum"] = espectro
        item_n["events"] = eventos_normalizados
        item_n["indices"] = sorted(indices)
        item_n["event_centers"] = [int(e["peak_index"]) for e in eventos_normalizados]
        detalhes_normalizados.append(item_n)
        total_eventos += len(eventos_normalizados)
        total_pontos += len(indices)
    declared_events = int(frozen.get("total_events", total_eventos))
    declared_points = int(frozen.get("total_points", total_pontos))
    if declared_events != total_eventos or declared_points != total_pontos:
        raise ValueError(
            "Cosmic-ray report consistency check failed: reviewed counts do not match "
            "the stored event intervals. Run Detect again before applying removal."
        )
    frozen["spectra"] = detalhes_normalizados
    frozen["total_events"] = int(total_eventos)
    frozen["total_points"] = int(total_pontos)
    frozen.setdefault("diagnostics", {})
    frozen["diagnostics"]["validated_report"] = True
    frozen["diagnostics"]["max_repair_points"] = int(max_repair_points)
    return frozen

def _celulas_relatorio_cosmic(relatorio):
    """Return {(spectral_index, spectrum_column), ...} for a validated report."""
    cells = set()
    for item in relatorio.get("spectra", []):
        espectro = int(item["spectrum"])
        for evento in item.get("events", []):
            inicio = int(evento["start_index"])
            fim = int(evento["end_index"])
            for indice in range(inicio, fim + 1):
                cells.add((indice, espectro))
    return cells

def corrigir_cosmic_rays_matriz(
    b, numero_espectros=None, threshold=10.0, kernel_size=3, max_width=3.0,
    nx=None, ny=None, spatial_validate=False, spatial_threshold=8.0,
    relatorio=None,
):
    """
    Return a copy of a Raman matrix with confirmed cosmic rays corrected.

    When ``relatorio`` is supplied, exactly that reviewed and validated report
    is applied. The routine never runs a hidden second detection in that case.
    """
    b = np.asarray(b)
    if b.ndim != 2 or b.shape[1] < 2:
        raise ValueError("Invalid Raman matrix.")
    corrigida = b.copy()
    disponiveis = b.shape[1] - 1
    if numero_espectros is None:
        numero_espectros = disponiveis
    numero_espectros = min(int(numero_espectros), disponiveis)
    if numero_espectros < 1:
        raise ValueError("No Raman spectra are available for cosmic-ray correction.")
    if relatorio is None:
        relatorio = detectar_cosmic_rays_matriz(
            b,
            numero_espectros=numero_espectros,
            threshold=threshold,
            max_width=max_width,
            nx=nx,
            ny=ny,
            spatial_validate=spatial_validate,
            spatial_threshold=spatial_threshold,
        )
    relatorio_validado = _normalizar_relatorio_cosmic(
        relatorio,
        numero_pontos=b.shape[0],
        numero_espectros=numero_espectros,
    )
    por_espectro = {
        int(item["spectrum"]): item
        for item in relatorio_validado.get("spectra", [])
    }
    for espectro in range(1, numero_espectros + 1):
        item = por_espectro.get(espectro)
        if not item:
            continue
        corrigida[:, espectro] = _corrigir_eventos_cosmic(
            b[:, espectro], item.get("events", []), kernel_size=kernel_size
        )
    # Safety check: correction must not touch any cell outside the reviewed
    # intervals. This catches indexing/callback/report bugs before data in the
    # interactive session are committed.
    expected_cells = _celulas_relatorio_cosmic(relatorio_validado)
    diff = np.asarray(corrigida[:, 1:numero_espectros + 1], dtype=float) != np.asarray(
        b[:, 1:numero_espectros + 1], dtype=float
    )
    changed_rows, changed_cols0 = np.nonzero(diff)
    changed_cells = {
        (int(row), int(col0) + 1)
        for row, col0 in zip(changed_rows.tolist(), changed_cols0.tolist())
    }
    unexpected = changed_cells - expected_cells
    if unexpected:
        raise RuntimeError(
            "Cosmic-ray correction safety check failed: data outside the reviewed "
            "event intervals would be modified. No correction was committed."
        )
    relatorio_validado.setdefault("diagnostics", {})
    relatorio_validado["diagnostics"]["numerically_changed_points"] = int(
        len(changed_cells)
    )
    relatorio_validado["diagnostics"]["reviewed_point_cells"] = int(
        len(expected_cells)
    )
    return corrigida, relatorio_validado

def calcular_valor_correcao(area, linha, coluna, metodo):
    """
    Calcula o valor substituto de um pixel usando o método escolhido.

    Métodos:
      - 'mean4'   : média dos 4 vizinhos ortogonais
      - 'mean8'   : média dos 8 vizinhos
      - 'median8' : mediana dos 8 vizinhos
    """
    if not (
        0 < linha < area.shape[0] - 1
        and 0 < coluna < area.shape[1] - 1
    ):
        raise ValueError(
            "Border pixels cannot be corrected because a complete "
            "neighborhood is not available."
        )
    if metodo == "mean4":
        valores = np.asarray([
            area[linha, coluna + 1],
            area[linha, coluna - 1],
            area[linha - 1, coluna],
            area[linha + 1, coluna],
        ], dtype=float)
        return float(np.mean(valores))
    vizinhos = _vizinhos_8(area, linha, coluna)
    if metodo == "mean8":
        return float(np.mean(vizinhos))
    if metodo == "median8":
        return float(np.median(vizinhos))
    raise ValueError(f"Unknown correction method: {metodo}")

def _limites_exibicao(area):
    """
    Escolhe uma escala de cores estável.

    A escala completa é mantida quando o mapa não possui um outlier
    dominante. Se um único valor extremo esmagar o contraste do mapa,
    a visualização usa percentis 1–99. Os dados NÃO são alterados.
    """
    valores = np.asarray(area, dtype=float)
    valores = valores[np.isfinite(valores)]
    if valores.size == 0:
        return 0.0, 1.0, False
    minimo = float(np.min(valores))
    maximo = float(np.max(valores))
    if minimo == maximo:
        return minimo, minimo + 1.0, False
    p1, p99 = np.percentile(valores, [1.0, 99.0])
    p1 = float(p1)
    p99 = float(p99)
    intervalo_total = maximo - minimo
    intervalo_robusto = p99 - p1
    # Só aplica escala robusta quando a amplitude completa é muito
    # maior que a região onde está praticamente todo o mapa.
    usar_robusta = (
        np.isfinite(intervalo_robusto)
        and intervalo_robusto > 0
        and intervalo_total / intervalo_robusto >= 4.0
    )
    if usar_robusta:
        return p1, p99, True
    return minimo, maximo, False

def _indice_espectro(nx, linha, coluna):
    """Mapeia (linha, coluna) do mapa para a coluna do espectro no .asc."""
    return (nx * linha) + coluna + 1

def _indices_espectros_vizinhos(nx, linha, coluna):
    indices = []
    for dl in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dl == 0 and dc == 0:
                continue
            indices.append(_indice_espectro(nx, linha + dl, coluna + dc))
    return indices

def detectar_spikes(area, b, xstart, xstop, nx):
    """
    Detecta candidatos a spike de forma conservadora e sem parâmetro
    exposto ao usuário.

    Etapa 1 — espacial:
        procura pixels muito diferentes da mediana dos 8 vizinhos.

    Etapa 2 — espectral:
        exige que o espectro bruto daquele pixel tenha uma feição
        estreita e anômala, comparada aos espectros dos 8 pixels vizinhos,
        justamente na região que participa da integração/background.

    Etapa 3 — proteção contra falsos positivos:
        feições estreitas repetidas em vários pixels no mesmo Raman shift
        são tratadas como provável sinal físico, não como spike isolado.

    Retorna uma lista de dicionários com linha, coluna e informações de
    diagnóstico. Nenhum dado é modificado nesta função.
    """
    area = np.asarray(area, dtype=float)
    if area.ndim != 2 or min(area.shape) < 3:
        return []

    # --------------------------------------------------------
    # 1) Resíduo espacial em relação à mediana da vizinhança
    # --------------------------------------------------------
    coordenadas = []
    residuos = []
    for linha in range(1, area.shape[0] - 1):
        for coluna in range(1, area.shape[1] - 1):
            centro = float(area[linha, coluna])
            mediana_local = float(np.median(_vizinhos_8(area, linha, coluna)))
            coordenadas.append((linha, coluna))
            residuos.append(centro - mediana_local)
    med_residuo, escala_residuo = _escala_robusta(residuos)
    # A janela de contexto serve apenas para estimar o ruído espectral.
    # A feição candidata, por outro lado, precisa cair na região que de
    # fato influencia o mapa: seleção + os 2 pontos de background.
    delta = 2
    contexto = 10
    rel_inicio = max(0, int(xstart) - delta)
    rel_fim = min(b.shape[0] - 1, int(xstop) + delta)
    ctx_inicio = max(0, rel_inicio - contexto)
    ctx_fim = min(b.shape[0] - 1, rel_fim + contexto)
    preliminares = []
    for (linha, coluna), residuo in zip(coordenadas, residuos):
        z_mapa = abs(float(residuo) - med_residuo) / escala_residuo
        if z_mapa < _AUTO_MAP_Z:
            continue
        indice = _indice_espectro(nx, linha, coluna)
        vizinhos_indices = _indices_espectros_vizinhos(nx, linha, coluna)
        centro = b[ctx_inicio:ctx_fim + 1, indice].astype(float)
        vizinhos = b[
            ctx_inicio:ctx_fim + 1,
            vizinhos_indices
        ].astype(float)
        mediana_vizinhos = np.median(vizinhos, axis=1)
        diferenca = centro - mediana_vizinhos
        med_dif, escala_dif = _escala_robusta(diferenca)
        desvio = np.abs(diferenca - med_dif)
        inicio_local = rel_inicio - ctx_inicio
        fim_local = rel_fim - ctx_inicio
        desvio_relevante = desvio[inicio_local:fim_local + 1]
        if desvio_relevante.size == 0:
            continue
        pos_local = int(np.argmax(desvio_relevante))
        desvio_maximo = float(desvio_relevante[pos_local])
        z_espectral = desvio_maximo / escala_dif
        if desvio_maximo <= 0:
            continue
        largura = int(np.sum(desvio_relevante >= 0.5 * desvio_maximo))
        if z_espectral < _AUTO_SPECTRAL_Z:
            continue
        if largura > _AUTO_MAX_PEAK_WIDTH:
            continue
        indice_pico = rel_inicio + pos_local
        preliminares.append({
            "linha": linha,
            "coluna": coluna,
            "z_mapa": float(z_mapa),
            "z_espectral": float(z_espectral),
            "largura": largura,
            "indice_pico": int(indice_pico),
            "raman_shift": float(b[indice_pico, 0]),
            "valor": float(area[linha, coluna]),
        })

    # --------------------------------------------------------
    # 3) Evita apagar uma feição Raman real repetida no mapa
    # --------------------------------------------------------
    candidatos = []
    for candidato in preliminares:
        k = candidato["indice_pico"]
        linha = candidato["linha"]
        coluna = candidato["coluna"]
        compartilhados = sum(
            1
            for outro in preliminares
            if abs(outro["indice_pico"] - k) <= 1
        )
        vizinho_com_mesmo_pico = any(
            outro is not candidato
            and max(
                abs(outro["linha"] - linha),
                abs(outro["coluna"] - coluna)
            ) <= 1
            and abs(outro["indice_pico"] - k) <= 1
            for outro in preliminares
        )
        if compartilhados >= _AUTO_SHARED_PEAK_LIMIT:
            continue
        if vizinho_com_mesmo_pico:
            continue
        candidatos.append(candidato)
    return candidatos

def _calcular_area_raman(b, xstart, xstop, nx, ny):
    """
    Calculate the integrated Raman-band area after a local linear background.

    This is mathematically equivalent to the previous spectrum-by-spectrum
    implementation, but it performs the baseline and trapezoidal integration
    for all map spectra at once with NumPy broadcasting. Large Raman maps are
    therefore substantially faster while keeping the same result.
    """
    b = np.asarray(b)
    mt = int(nx) * int(ny)
    total_spectra = b.shape[1] - 1
    if nx <= 0 or ny <= 0:
        raise ValueError("Map geometry must have positive X and Y values.")
    if mt > total_spectra:
        raise ValueError(
            f"The geometry {nx} × {ny} requires {mt} spectra, "
            f"but the file contains only {total_spectra}."
        )
    xstart = int(xstart)
    xstop = int(xstop)
    if xstart > xstop:
        xstart, xstop = xstop, xstart
    if xstop - xstart < 1:
        raise ValueError("Select at least two Raman-shift samples to integrate a band.")
    delta = 2
    bgstart1 = xstart - delta
    bgstop1 = xstart
    bgstart2 = xstop
    bgstop2 = xstop + delta
    if bgstart1 < 0 or bgstop2 >= b.shape[0]:
        raise ValueError(
            "The selected Raman region is too close to the spectrum boundary."
        )
    x = np.asarray(b[:, 0], dtype=float)
    spectra = np.asarray(b[:, 1:mt + 1], dtype=float)
    x_region = x[xstart:xstop + 1]
    if x_region.size < 2:
        raise ValueError("The selected Raman region is too small for integration.")
    order = np.argsort(x_region)
    x_integral = x_region[order]
    x_left = float(np.mean(x[bgstart1:bgstop1 + 1]))
    x_right = float(np.mean(x[bgstart2:bgstop2 + 1]))
    if abs(x_right - x_left) <= np.finfo(float).eps:
        raise ValueError("Could not define the local linear background.")
    y_left = np.mean(spectra[bgstart1:bgstop1 + 1, :], axis=0)
    y_right = np.mean(spectra[bgstart2:bgstop2 + 1, :], axis=0)
    slopes = (y_right - y_left) / (x_right - x_left)
    baseline = (
        y_left[np.newaxis, :]
        + (x_region[:, np.newaxis] - x_left) * slopes[np.newaxis, :]
    )
    corrected = spectra[xstart:xstop + 1, :] - baseline
    integrated = _trapezoid(
        corrected[order, :], x=x_integral, axis=0
    )
    return np.asarray(integrated, dtype=float).reshape(int(ny), int(nx))

def fazer_imagem(b, xstart, xstop, nx, ny, tetoz, dependency_handler=None, source_path=None, software_version="unknown", embed_parent=None, spectrum_callback=None):
    """
    Gera o mapa Raman e abre uma interface de inspeção/correção.

    Separação científica desta versão:
      * Cosmic Ray Removal atua nos ESPECTROS usando detecção conservadora
        de spikes estreitos + validação espacial e então o mapa é recalculado.
      * Bad Pixel Repair atua somente na IMAGEM já calculada e é uma ferramenta
        espacial de reparo/visualização.

    O arquivo em disco nunca é alterado. Correções espectrais feitas nesta
    janela permanecem na matriz carregada em memória, permitindo que um novo
    mapa gerado na mesma sessão use os espectros corrigidos.

    ``embed_parent`` permite renderizar toda a área Data Quality dentro da
    janela principal do IMESPEC. Isso mantém a análise em um workspace único,
    em vez de abrir uma nova janela Matplotlib para cada mapa.
    """
    b_backup = np.asarray(b).copy()
    mt = int(nx) * int(ny)
    area = _calcular_area_raman(b, xstart, xstop, nx, ny)
    area_original = area.copy()
    raman_a = float(b[int(xstart), 0])
    raman_b = float(b[int(xstop), 0])
    raman_inicio = min(raman_a, raman_b)
    raman_fim = max(raman_a, raman_b)
    if embed_parent is None:
        fig_mapa = plt.figure(figsize=(14.2, 8.0))
        try:
            fig_mapa.canvas.manager.set_window_title("IMESPEC — Raman Map")
        except Exception:
            pass
        embedded_canvas = None
        embedded_toolbar = None
    else:
        # A normal Figure + FigureCanvasTkAgg lets the same scientific figure
        # live inside the application workspace, like MATLAB/LabSpec docked
        # analysis panes, instead of creating a detached OS window.
        for child in list(embed_parent.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        fig_mapa = Figure(figsize=(14.2, 8.0), dpi=100)
        canvas_host = ttk.Frame(embed_parent)
        canvas_host.pack(fill="both", expand=True)
        embedded_canvas = FigureCanvasTkAgg(fig_mapa, master=canvas_host)
        toolbar_host = ttk.Frame(canvas_host)
        toolbar_host.pack(fill="x", side="bottom")
        embedded_toolbar = NavigationToolbar2Tk(
            embedded_canvas, toolbar_host, pack_toolbar=False
        )
        embedded_toolbar.update()
        embedded_toolbar.pack(fill="x")
        embedded_canvas.get_tk_widget().pack(fill="both", expand=True)
    fig_mapa.set_facecolor('#FFFFFF')
    ax_mapa = fig_mapa.add_axes([0.050, 0.10, 0.585, 0.82])
    ax_mapa.set_facecolor('#F8FAFC')
    for spine in ax_mapa.spines.values():
        spine.set_color('#CBD5E1')
    vmin, vmax, escala_robusta = _limites_exibicao(area_original)
    imagem = ax_mapa.imshow(area, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax_mapa.set_title(
        rf"Raman Map — integrated band: {raman_inicio:.1f} to "
        rf"{raman_fim:.1f} cm$^{{-1}}$"
    )
    ax_mapa.set_xlabel("X pixel")
    ax_mapa.set_ylabel("Y pixel")
    colorbar = fig_mapa.colorbar(
        imagem, ax=ax_mapa, fraction=0.046, pad=0.04,
        extend="both" if escala_robusta else "neither"
    )
    colorbar.set_label("Background-corrected Raman band area (a.u.·cm⁻¹)")

    # -------------------- Painel: cosmic rays --------------------
    fig_mapa.text(0.70, 0.93, "Data Quality", fontsize=13, fontweight="bold", color="#0F172A")
    fig_mapa.text(0.70, 0.885, "Cosmic Ray Removal — spectral", fontsize=10.5, fontweight="bold", color="#0F172A")
    fig_mapa.text(
        0.70, 0.845,
        "Conservative spike detector + spatial/shared-peak protection\n"
        "Prominence/noise ≥ 10 | FWHM ≤ 3 | repair span ≤ 5 points",
        fontsize=8.5, va="top"
    )
    ax_cosmic_detect = fig_mapa.add_axes([0.70, 0.735, 0.13, 0.052])
    botao_cosmic_detect = Button(ax_cosmic_detect, "Detect", color="#E8EDF4", hovercolor="#DDE5EF")
    ax_cosmic_apply = fig_mapa.add_axes([0.84, 0.735, 0.14, 0.052])
    botao_cosmic_apply = Button(ax_cosmic_apply, "Apply Removal", color="#2563EB", hovercolor="#1D4ED8")
    botao_cosmic_apply.label.set_color("white")
    botao_cosmic_apply.label.set_fontweight("bold")

    # -------------------- Painel: bad pixels --------------------
    fig_mapa.text(0.70, 0.665, "Bad Pixel Repair — map only", fontsize=10.5, fontweight="bold", color="#0F172A")
    fig_mapa.text(
        0.70, 0.625,
        "Robust local outlier + isolation protection\n"
        "Left-click: inspect pixel spectrum | Right-click: manual repair",
        fontsize=8.3, va="top"
    )
    ax_radio = fig_mapa.add_axes([0.70, 0.415, 0.275, 0.17])
    rotulos = [
        "Orthogonal Mean (4-neighbor)",
        "Local Mean (8-neighbor)",
        "Local Median (8-neighbor)",
    ]
    ax_radio.set_facecolor("#F8FAFC")
    for spine in ax_radio.spines.values():
        spine.set_color("#E2E8F0")
    radio = RadioButtons(ax_radio, rotulos, active=2, activecolor="#2563EB")
    mapa_metodos = {
        "Orthogonal Mean (4-neighbor)": "mean4",
        "Local Mean (8-neighbor)": "mean8",
        "Local Median (8-neighbor)": "median8",
    }
    ax_bad_detect = fig_mapa.add_axes([0.70, 0.335, 0.13, 0.052])
    botao_bad_detect = Button(ax_bad_detect, "Detect Candidates", color="#E8EDF4", hovercolor="#DDE5EF")
    ax_bad_apply = fig_mapa.add_axes([0.84, 0.335, 0.14, 0.052])
    botao_bad_apply = Button(ax_bad_apply, "Apply Repair", color="#2563EB", hovercolor="#1D4ED8")
    botao_bad_apply.label.set_color("white")
    botao_bad_apply.label.set_fontweight("bold")
    ax_clear = fig_mapa.add_axes([0.70, 0.270, 0.13, 0.048])
    botao_clear = Button(ax_clear, "Clear Marks", color="#E8EDF4", hovercolor="#DDE5EF")
    ax_restore = fig_mapa.add_axes([0.84, 0.270, 0.14, 0.048])
    botao_restore = Button(ax_restore, "Restore All", color="#E8EDF4", hovercolor="#DDE5EF")
    display_mode = "Robust display range" if escala_robusta else "Full display range"
    display_text = fig_mapa.text(
        0.70, 0.235,
        f"Display: {display_mode}\n"
        "Color scale updates after corrections.",
        fontsize=8.2, va="top"
    )
    status_text = fig_mapa.text(0.70, 0.165, "Ready.", fontsize=8.7, va="top", wrap=True)
    bad_candidatos = []
    cosmic_relatorio = None
    cosmic_estado = {"aplicando": False, "map_only_modified": False}
    marcadores_bad = []
    marcadores_cosmic = []
    export_history = {
        "cosmic_reports": [],
        "bad_pixel_repairs": [],
        "actions": [],
    }
    # Removal is deliberately disabled until the user explicitly runs Detect.
    # This prevents an accidental second pass from being triggered by Apply.
    botao_cosmic_apply.set_active(False)
    def metodo_atual():
        return mapa_metodos[radio.value_selected]
    def atualizar_status_mapa(texto):
        status_text.set_text(texto)
        fig_mapa.canvas.draw_idle()
    def redesenhar_mapa(recalcular_escala=False):
        nonlocal vmin, vmax, escala_robusta, display_mode
        imagem.set_data(area)
        if recalcular_escala:
            vmin, vmax, escala_robusta = _limites_exibicao(area)
            display_mode = "Robust display range" if escala_robusta else "Full display range"
            display_text.set_text(
                f"Display: {display_mode}\n"
                "Color scale updates after corrections."
            )
            fig_mapa._imespec_display_limits = (vmin, vmax)
            fig_mapa._imespec_robust_display = escala_robusta
        imagem.set_clim(vmin, vmax)
        colorbar.extend = "both" if escala_robusta else "neither"
        colorbar.update_normal(imagem)
        fig_mapa.canvas.draw_idle()
    def limpar_marcadores_bad():
        nonlocal bad_candidatos, marcadores_bad
        for marcador in marcadores_bad:
            try:
                marcador.remove()
            except Exception:
                pass
        bad_candidatos = []
        marcadores_bad = []
    def limpar_marcadores_cosmic():
        nonlocal marcadores_cosmic
        for marcador in marcadores_cosmic:
            try:
                marcador.remove()
            except Exception:
                pass
        marcadores_cosmic = []
    def limpar_todos_marcadores(event=None):
        nonlocal cosmic_relatorio
        limpar_marcadores_bad()
        limpar_marcadores_cosmic()
        fig_mapa.canvas.draw_idle()
        if event is not None:
            # Explicitly clearing review marks also discards the reviewed cosmic
            # report, matching Bad Pixel behavior and preventing hidden Apply.
            cosmic_relatorio = None
            botao_cosmic_apply.set_active(False)
            atualizar_status_mapa(
                "Detection marks and reviewed candidates cleared. Data unchanged."
            )
    def mostrar_bad(candidatos):
        nonlocal bad_candidatos, marcadores_bad
        limpar_marcadores_bad()
        bad_candidatos = list(candidatos)
        if not bad_candidatos:
            fig_mapa.canvas.draw_idle()
            return
        xs = [c["coluna"] for c in bad_candidatos]
        ys = [c["linha"] for c in bad_candidatos]
        marcador, = ax_mapa.plot(
            xs, ys, linestyle="None", marker="o", markersize=10,
            markerfacecolor="none", markeredgecolor="red", markeredgewidth=1.7
        )
        marcadores_bad = [marcador]
        fig_mapa.canvas.draw_idle()
    def mostrar_cosmic(relatorio):
        nonlocal marcadores_cosmic
        limpar_marcadores_cosmic()
        coords = []
        inicio_rel = max(0, int(xstart) - 2)
        fim_rel = min(b.shape[0] - 1, int(xstop) + 2)
        for item in relatorio.get("spectra", []):
            espectro = int(item["spectrum"])
            if espectro < 1 or espectro > mt:
                continue
            if not any(inicio_rel <= int(k) <= fim_rel for k in item.get("indices", [])):
                continue
            p = espectro - 1
            coords.append((p % int(nx), p // int(nx)))
        if coords:
            xs, ys = zip(*coords)
            marcador, = ax_mapa.plot(
                xs, ys, linestyle="None", marker="x", markersize=9,
                markeredgewidth=1.8
            )
            marcadores_cosmic = [marcador]
        fig_mapa.canvas.draw_idle()
        return len(coords)
    def solicitar_dependencia(package, feature):
        """Route missing-feature dependencies to the main IMESPEC UI."""
        if callable(dependency_handler):
            try:
                dependency_handler(package, feature)
                return
            except Exception:
                pass
        messagebox.showwarning(
            "Missing Dependency",
            f"{feature} requires {package}.\n\n"
            "Open IMESPEC > Help > Dependencies to install it in the active Python environment."
        )
    def on_click(event):
        nonlocal cosmic_relatorio
        if event.inaxes is not ax_mapa or event.xdata is None or event.ydata is None:
            return
        coluna = _pixel_mais_proximo(event.xdata)
        linha = _pixel_mais_proximo(event.ydata)
        if linha < 0 or linha >= ny or coluna < 0 or coluna >= nx:
            return
        if event.button is MouseButton.LEFT:
            espectro = _indice_espectro(nx, linha, coluna)
            if espectro >= b.shape[1]:
                return
            if callable(spectrum_callback):
                try:
                    spectrum_callback(
                        int(espectro),
                        np.asarray(b[:, 0], dtype=float),
                        np.asarray(b[:, espectro], dtype=float),
                        int(linha),
                        int(coluna),
                    )
                except Exception as exc:
                    atualizar_status_mapa(f"Could not show spectrum {espectro}: {exc}")
                    return
            else:
                plt.ion()
                fig_espectro = plt.figure()
                ax_espectro = fig_espectro.add_subplot(111)
                ax_espectro.plot(b[:, 0], b[:, espectro])
                ax_espectro.set_xlabel(r"Raman shift (cm$^{-1}$)")
                ax_espectro.set_ylabel("Raman intensity (a.u.)")
                ax_espectro.set_title(f"Spectrum {espectro}")
                ax_espectro.set_xlim(float(np.min(b[:, 0])), float(np.max(b[:, 0])))
                ax_espectro.relim()
                ax_espectro.autoscale_view(scalex=False, scaley=True)
                fig_espectro.canvas.draw_idle()
                plt.show(block=False)
            atualizar_status_mapa(
                f"Spectrum {espectro} opened (row {linha}, column {coluna})."
            )
        elif event.button is MouseButton.RIGHT:
            if not (0 < linha < ny - 1 and 0 < coluna < nx - 1):
                atualizar_status_mapa(
                    "Border pixels cannot be repaired because a complete neighborhood is unavailable."
                )
                return
            metodo = metodo_atual()
            antigo = float(area[linha, coluna])
            try:
                novo = calcular_valor_correcao(area.copy(), linha, coluna, metodo)
            except ValueError as erro:
                atualizar_status_mapa(str(erro))
                return
            area[linha, coluna] = novo
            export_history["bad_pixel_repairs"].append({
                "mode": "manual-right-click",
                "x_pixel": int(coluna),
                "y_pixel": int(linha),
                "old_value": float(antigo),
                "new_value": float(novo),
                "method": str(radio.value_selected),
            })
            export_history["actions"].append({
                "action": "bad_pixel_repair", "mode": "manual",
                "x_pixel": int(coluna), "y_pixel": int(linha),
            })
            cosmic_estado["map_only_modified"] = True
            cosmic_relatorio = None
            botao_cosmic_apply.set_active(False)
            limpar_marcadores_bad()
            limpar_marcadores_cosmic()
            redesenhar_mapa(recalcular_escala=True)
            atualizar_status_mapa(
                f"Map pixel ({coluna}, {linha}) repaired: {antigo:.3g} → {novo:.3g} "
                f"using {radio.value_selected}. Underlying spectrum was not changed."
            )
    def detectar_cosmic(event):
        nonlocal cosmic_relatorio
        if cosmic_estado["aplicando"]:
            return
        if cosmic_estado["map_only_modified"]:
            messagebox.showinfo(
                "Processing Order",
                "Bad-pixel map-only repairs have already been applied in this map window.\n\n"
                "Cosmic Ray Removal recalculates the map from the spectra and would discard "
                "those map-only edits. Use Restore All, then run Cosmic Ray Detect/Removal "
                "before Bad Pixel Repair."
            )
            atualizar_status_mapa(
                "Recommended order: Cosmic Ray Removal first, Bad Pixel Repair second."
            )
            return
        if not refresh_optional_dependencies():
            botao_cosmic_apply.set_active(False)
            atualizar_status_mapa(
                "SciPy is required for Cosmic Ray Removal. Open Dependencies to install it."
            )
            solicitar_dependencia("scipy", "Cosmic Ray Removal")
            return
        # A new Detect always invalidates any older review before scanning.
        cosmic_relatorio = None
        botao_cosmic_detect.set_active(False)
        botao_cosmic_apply.set_active(False)
        atualizar_status_mapa("Scanning spectra for cosmic rays...")
        fig_mapa.canvas.draw_idle()
        try:
            relatorio_novo = detectar_cosmic_rays_matriz(
                b, numero_espectros=mt, threshold=10.0, max_width=3.0,
                nx=nx, ny=ny, spatial_validate=True, spatial_threshold=8.0
            )
            # Freeze/validate the report immediately. If anything inside the
            # detector is internally inconsistent we fail before showing it.
            cosmic_relatorio = _normalizar_relatorio_cosmic(
                relatorio_novo,
                numero_pontos=b.shape[0],
                numero_espectros=mt,
            )
        except Exception as exc:
            cosmic_relatorio = None
            limpar_marcadores_cosmic()
            messagebox.showerror("Cosmic Ray Detection", str(exc))
            atualizar_status_mapa("Cosmic-ray detection failed. Data unchanged.")
            botao_cosmic_detect.set_active(True)
            botao_cosmic_apply.set_active(False)
            return
        finally:
            botao_cosmic_detect.set_active(True)
        afetados_mapa = mostrar_cosmic(cosmic_relatorio)
        total_eventos = int(cosmic_relatorio.get("total_events", 0))
        total_pontos = int(cosmic_relatorio.get("total_points", 0))
        diagnostico_cosmic = cosmic_relatorio.get("diagnostics", {})
        protegidos = int(diagnostico_cosmic.get("protected_shared_events", 0))
        botao_cosmic_apply.set_active(total_eventos > 0)
        if total_eventos == 0:
            detalhe = (
                f" {protegidos} recurring narrow feature(s) were protected as likely physical/systematic."
                if protegidos else ""
            )
            messagebox.showinfo(
                "Cosmic Ray Detection",
                "No isolated cosmic-ray candidates passed the conservative validation." + detalhe
            )
            atualizar_status_mapa("No cosmic-ray candidates detected." + detalhe)
        else:
            detalhe = (
                f" {protegidos} recurring narrow feature(s) were protected."
                if protegidos else ""
            )
            atualizar_status_mapa(
                f"{total_eventos} cosmic-ray event(s) detected "
                f"({total_pontos} spectral point(s)); "
                f"{afetados_mapa} map pixel(s) are affected in/near the selected band."
                f"{detalhe} Review, then apply removal if appropriate."
            )
    def aplicar_cosmic(event):
        nonlocal cosmic_relatorio
        # Apply never performs an implicit Detect. The user must explicitly
        # review a report first, which also makes double-clicks harmless.
        if cosmic_estado["aplicando"]:
            return
        if cosmic_estado["map_only_modified"]:
            messagebox.showinfo(
                "Processing Order",
                "Bad-pixel map-only repairs are present. Use Restore All and apply Cosmic Ray "
                "Removal before Bad Pixel Repair so no map-only corrections are silently lost."
            )
            atualizar_status_mapa(
                "Cosmic-ray removal blocked to protect existing map-only bad-pixel repairs."
            )
            return
        if cosmic_relatorio is None:
            botao_cosmic_apply.set_active(False)
            messagebox.showinfo(
                "Cosmic Ray Removal",
                "Run 'Detect' first, review the candidates, and then click Apply Removal."
            )
            atualizar_status_mapa("Run Detect before applying cosmic-ray removal.")
            return
        try:
            relatorio_revisado = _normalizar_relatorio_cosmic(
                cosmic_relatorio,
                numero_pontos=b.shape[0],
                numero_espectros=mt,
            )
        except Exception as exc:
            cosmic_relatorio = None
            botao_cosmic_apply.set_active(False)
            messagebox.showerror("Cosmic Ray Removal", str(exc))
            atualizar_status_mapa("Reviewed cosmic-ray report became invalid. Run Detect again.")
            return
        total_eventos = int(relatorio_revisado.get("total_events", 0))
        total_pontos = int(relatorio_revisado.get("total_points", 0))
        if total_eventos == 0:
            cosmic_relatorio = None
            botao_cosmic_apply.set_active(False)
            return
        # Lock the callback before opening the modal. A double click cannot
        # launch a second pass while/after this reviewed report is being used.
        cosmic_estado["aplicando"] = True
        botao_cosmic_detect.set_active(False)
        botao_cosmic_apply.set_active(False)
        try:
            confirmado = messagebox.askyesno(
                "Apply Cosmic Ray Removal",
                f"Apply removal to {total_eventos} detected cosmic-ray event(s) "
                f"({total_pontos} spectral point(s))?\n\n"
                "This corrects only the reviewed narrow spikes in memory and recalculates "
                "the Raman map. The file on disk is not modified."
            )
            if not confirmado:
                botao_cosmic_apply.set_active(True)
                atualizar_status_mapa("Cosmic-ray removal canceled. Reviewed candidates are still available.")
                return
            antes = np.asarray(b[:, 1:mt + 1], dtype=float).copy()
            corrigida, relatorio_aplicado = corrigir_cosmic_rays_matriz(
                b, numero_espectros=mt, threshold=10.0, kernel_size=3, max_width=3.0,
                nx=nx, ny=ny, spatial_validate=True, spatial_threshold=8.0,
                relatorio=relatorio_revisado,
            )
            # The correction function validates that no unreviewed cells are
            # touched. We additionally verify that its returned report retains
            # exactly the counts shown in the confirmation dialog.
            applied_events = int(relatorio_aplicado.get("total_events", -1))
            applied_points = int(relatorio_aplicado.get("total_points", -1))
            if applied_events != total_eventos or applied_points != total_pontos:
                raise RuntimeError(
                    "Cosmic-ray apply consistency check failed: the applied report does not "
                    "match the reviewed report. No correction was committed."
                )
            depois = np.asarray(corrigida[:, 1:mt + 1], dtype=float)
            changed_values = int(np.count_nonzero(depois != antes))
            # Commit only after every check above has succeeded.
            b[:, 1:mt + 1] = corrigida[:, 1:mt + 1]
            area[:, :] = _calcular_area_raman(b, xstart, xstop, nx, ny)
            export_history["cosmic_reports"].append(copy.deepcopy(relatorio_aplicado))
            export_history["actions"].append({
                "action": "cosmic_ray_removal",
                "events": int(total_eventos),
                "reviewed_points": int(total_pontos),
                "changed_values": int(changed_values),
                "threshold_prominence_noise": 10.0,
                "max_fwhm_points": 3.0,
                "spatial_threshold": 8.0,
                "max_repair_points": int(relatorio_aplicado.get("diagnostics", {}).get("max_repair_points", 5)),
            })
            cosmic_relatorio = None
            limpar_todos_marcadores()
            redesenhar_mapa(recalcular_escala=True)
            atualizar_status_mapa(
                f"Cosmic-ray removal applied to {total_eventos} event(s) "
                f"({total_pontos} reviewed spectral point(s)); "
                f"{changed_values} intensity value(s) changed. "
                "Map recalculated and display scale updated."
            )
        except Exception as exc:
            # b/area are only committed after validation, so failures leave the
            # current data unchanged.
            messagebox.showerror("Cosmic Ray Removal", str(exc))
            atualizar_status_mapa("Cosmic-ray removal failed. Data unchanged; run Detect again.")
            cosmic_relatorio = None
        finally:
            cosmic_estado["aplicando"] = False
            botao_cosmic_detect.set_active(True)
            # Successful apply or failure both require an explicit new Detect.
            # A canceled apply re-enabled the button above because the report
            # remains reviewed and unchanged.
            if cosmic_relatorio is None:
                botao_cosmic_apply.set_active(False)
    def detectar_bad(event):
        candidatos, diagnostico = detectar_pixels_anomalos(
            area, z_limite=6.0, return_diagnostics=True
        )
        mostrar_bad(candidatos)
        suppressed = int(diagnostico.get("suppressed_cluster_count", 0))
        if not candidatos:
            detalhe = (
                f" {suppressed} candidate pixel(s) belonged to larger coherent regions "
                "and were protected."
                if suppressed else ""
            )
            messagebox.showinfo(
                "Bad Pixel Candidates",
                "No isolated bad-pixel candidates were detected." + detalhe
            )
            atualizar_status_mapa(
                "No isolated bad-pixel candidates detected." + detalhe
            )
        else:
            detalhe = (
                f" {suppressed} pixel(s) in larger coherent regions were protected."
                if suppressed else ""
            )
            atualizar_status_mapa(
                f"{len(candidatos)} isolated bad-pixel candidate(s) marked."
                f"{detalhe} Review before repairing."
            )
    def aplicar_bad(event):
        nonlocal bad_candidatos, cosmic_relatorio
        if not bad_candidatos:
            messagebox.showinfo("Bad Pixel Repair", "Run 'Detect Candidates' first.")
            return
        confirmado = messagebox.askyesno(
            "Apply Bad Pixel Repair",
            f"Repair {len(bad_candidatos)} marked map pixel(s) using {radio.value_selected}?\n\n"
            "This changes only the current map values, not the underlying spectra."
        )
        if not confirmado:
            atualizar_status_mapa("Bad-pixel repair canceled.")
            return
        fonte = area.copy()
        metodo = metodo_atual()
        corrigidos = 0
        for candidato in bad_candidatos:
            linha = candidato["linha"]
            coluna = candidato["coluna"]
            if 0 < linha < ny - 1 and 0 < coluna < nx - 1:
                antigo = float(fonte[linha, coluna])
                novo = float(calcular_valor_correcao(fonte, linha, coluna, metodo))
                area[linha, coluna] = novo
                export_history["bad_pixel_repairs"].append({
                    "mode": "automatic-candidate",
                    "x_pixel": int(coluna),
                    "y_pixel": int(linha),
                    "old_value": antigo,
                    "new_value": novo,
                    "method": str(radio.value_selected),
                })
                corrigidos += 1
        if corrigidos:
            export_history["actions"].append({
                "action": "bad_pixel_repair", "mode": "automatic",
                "count": int(corrigidos), "method": str(radio.value_selected),
            })
        cosmic_estado["map_only_modified"] = True
        cosmic_relatorio = None
        botao_cosmic_apply.set_active(False)
        limpar_marcadores_bad()
        limpar_marcadores_cosmic()
        redesenhar_mapa(recalcular_escala=True)
        atualizar_status_mapa(
            f"{corrigidos} map pixel(s) repaired using {radio.value_selected}. "
            "Display scale updated."
        )
    def restaurar_tudo(event):
        nonlocal cosmic_relatorio
        b[:, :] = b_backup
        area[:, :] = area_original
        cosmic_relatorio = None
        cosmic_estado["aplicando"] = False
        cosmic_estado["map_only_modified"] = False
        export_history["cosmic_reports"].clear()
        export_history["bad_pixel_repairs"].clear()
        export_history["actions"].clear()
        botao_cosmic_detect.set_active(True)
        botao_cosmic_apply.set_active(False)
        limpar_todos_marcadores()
        redesenhar_mapa(recalcular_escala=True)
        atualizar_status_mapa("Spectra and Raman map restored to the state from when this map was opened.")

    # -------------------- Export --------------------
    ax_export = fig_mapa.add_axes([0.70, 0.035, 0.28, 0.052])
    botao_export = Button(ax_export, "Export...", color="#2563EB", hovercolor="#1D4ED8")
    botao_export.label.set_color("white")
    botao_export.label.set_fontweight("bold")
    def exportar_mapa(event=None):
        parent = embed_parent.winfo_toplevel() if embed_parent is not None else getattr(tk, '_default_root', None)
        win = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
        win.title("IMESPEC — Export Raman Map")
        win.geometry("720x690")
        win.minsize(680, 620)
        if parent is not None:
            try:
                win.transient(parent)
            except Exception:
                pass
        root = ttk.Frame(win, padding=16)
        root.pack(fill='both', expand=True)
        root.columnconfigure(1, weight=1)
        ttk.Label(root, text="Export Raman Map", font=("TkDefaultFont", 15, "bold")).grid(
            row=0, column=0, columnspan=3, sticky='w'
        )
        ttk.Label(
            root,
            text=(
                "Choose one or more interchange formats. CSV/TXT are ideal for Origin/Excel; "
                "HDF5/MAT/NPZ preserve the full hyperspectral dataset; PNG/SVG/PDF are figures. "
                "JCAMP-DX exports one spectrum per map pixel, while SPC stores the map spectra "
                "as a Galactic/Thermo multi-trace file."
            ),
            wraplength=670, justify='left', foreground='#555555'
        ).grid(row=1, column=0, columnspan=3, sticky='ew', pady=(5, 12))
        default_parent = os.path.dirname(source_path) if source_path and os.path.isdir(os.path.dirname(source_path)) else os.path.expanduser('~')
        pasta_var = tk.StringVar(value=default_parent)
        nome_var = tk.StringVar(value=f"{_safe_export_name(source_path or 'raman_map', 'raman_map')}_export")
        ttk.Label(root, text='Destination folder').grid(row=2, column=0, sticky='w', pady=4)
        ttk.Entry(root, textvariable=pasta_var).grid(row=2, column=1, sticky='ew', padx=(8, 8), pady=4)
        def procurar_pasta():
            escolhido = fd.askdirectory(parent=win, title='Choose export destination', initialdir=pasta_var.get() or default_parent)
            if escolhido:
                pasta_var.set(escolhido)
        ttk.Button(root, text='Browse...', command=procurar_pasta).grid(row=2, column=2, sticky='e', pady=4)
        ttk.Label(root, text='Export name').grid(row=3, column=0, sticky='w', pady=4)
        ttk.Entry(root, textvariable=nome_var).grid(row=3, column=1, columnspan=2, sticky='ew', padx=(8, 0), pady=4)
        box = ttk.LabelFrame(root, text='Formats', padding=10)
        box.grid(row=4, column=0, columnspan=3, sticky='nsew', pady=(12, 8))
        box.columnconfigure(0, weight=1); box.columnconfigure(1, weight=1)
        available = {
            'scipy': bool(_SCIPY_AVAILABLE),
            'h5py': importlib.util.find_spec('h5py') is not None,
            'openpyxl': importlib.util.find_spec('openpyxl') is not None,
            'SPyC_Writer': importlib.util.find_spec('SPyC_Writer') is not None,
        }
        specs = [
            ('csv', 'CSV tables (map matrix + long table)', True, None),
            ('tsv', 'TSV long table', False, None),
            ('txt', 'TXT scan table (#X #Y #Wave #Intensity)', True, None),
            ('jcamp', 'JCAMP-DX (.jdx) — one spectrum per pixel', False, None),
            ('spc', 'Galactic/Thermo SPC (.spc) — all map spectra', False, 'SPyC_Writer'),
            ('mat', 'MATLAB MAT (.mat)', available['scipy'], 'scipy'),
            ('hdf5', 'HDF5 (.h5) — recommended full-map container', available['h5py'], 'h5py'),
            ('xlsx', 'Excel workbook (.xlsx)', False, 'openpyxl'),
            ('npz', 'NumPy compressed archive (.npz)', True, None),
            ('png', 'PNG figure', True, None),
            ('svg', 'SVG vector figure', False, None),
            ('pdf', 'PDF figure', True, None),
            ('zip', 'IMESPEC reproducibility package (.zip)', True, None),
        ]
        vars_fmt = {}
        dep_for_fmt = {}
        for idx, (key, label, default, dep) in enumerate(specs):
            var = tk.BooleanVar(value=bool(default))
            vars_fmt[key] = var; dep_for_fmt[key] = dep
            text = label
            if dep and not available.get(dep, False):
                text += '  [dependency not installed]'
            ttk.Checkbutton(box, text=text, variable=var).grid(
                row=idx//2, column=idx%2, sticky='w', padx=(2, 16), pady=4
            )
        ttk.Label(
            root,
            text=(
                "Recommended for day-to-day work: CSV + HDF5 + NPZ + PNG/PDF + ZIP. "
                "Use JCAMP-DX or SPC when exchanging spectra with spectroscopy software."
            ),
            wraplength=670, justify='left', foreground='#666666'
        ).grid(row=5, column=0, columnspan=3, sticky='ew', pady=(4, 8))
        status_var = tk.StringVar(value='')
        ttk.Label(root, textvariable=status_var, wraplength=670, foreground='#555555').grid(
            row=6, column=0, columnspan=3, sticky='ew', pady=(2, 8)
        )
        buttons = ttk.Frame(root)
        buttons.grid(row=7, column=0, columnspan=3, sticky='e')
        ttk.Button(buttons, text='Cancel', command=win.destroy).pack(side='left', padx=(0, 8))
        def executar_exportacao():
            formatos = [k for k, v in vars_fmt.items() if v.get()]
            if not formatos:
                messagebox.showinfo('Raman Map Export', 'Select at least one export format.', parent=win)
                return
            for fmt in formatos:
                dep = dep_for_fmt.get(fmt)
                if dep and not available.get(dep, False):
                    status_var.set(f"{fmt.upper()} export requires {dep}. Install it and export again.")
                    solicitar_dependencia(dep, f"Raman Map {fmt.upper()} export")
                    return
            pasta = pasta_var.get().strip()
            nome = nome_var.get().strip()
            if not pasta or not nome:
                messagebox.showerror('Raman Map Export', 'Choose a destination folder and export name.', parent=win)
                return
            try:
                status_var.set('Exporting...')
                win.update_idletasks()
                result = exportar_raman_mapa_formatos(
                    pasta, nome, formatos,
                    b_atual=b, b_sessao=b_backup,
                    area_atual=area, area_original=area_original,
                    xstart=xstart, xstop=xstop, nx=nx, ny=ny,
                    source_path=source_path,
                    cosmic_history=export_history['cosmic_reports'],
                    bad_pixel_history=export_history['bad_pixel_repairs'],
                    processing_history=export_history['actions'],
                    display_limits=(vmin, vmax), robust_display=escala_robusta,
                    software_version=software_version,
                )
                warnings = '\n'.join(f"• {w}" for w in result.get('warnings', []))
                atualizar_status_mapa(f"Exported {len(result.get('files', []))} file(s) to {result['directory']}")
                win.destroy()
                messagebox.showinfo(
                    'Raman Map Export',
                    f"Export completed successfully.\n\nFolder:\n{result['directory']}\n\n"
                    f"Created files: {len(result.get('files', []))}"
                    + (f"\n\nNotes:\n{warnings}" if warnings else ''),
                    parent=parent,
                )
            except Exception as exc:
                status_var.set('Export failed. Data were not modified.')
                messagebox.showerror('Raman Map Export', str(exc), parent=win)
        ttk.Button(buttons, text='Export', command=executar_exportacao).pack(side='left')
        try:
            win.grab_set()
        except Exception:
            pass
    botao_export.on_clicked(exportar_mapa)
    cid_click = fig_mapa.canvas.mpl_connect("button_press_event", on_click)
    botao_cosmic_detect.on_clicked(detectar_cosmic)
    botao_cosmic_apply.on_clicked(aplicar_cosmic)
    botao_bad_detect.on_clicked(detectar_bad)
    botao_bad_apply.on_clicked(aplicar_bad)
    botao_clear.on_clicked(limpar_todos_marcadores)
    botao_restore.on_clicked(restaurar_tudo)
    # Mantém referências vivas e facilita testes.
    fig_mapa._imespec_area = area
    fig_mapa._imespec_area_original = area_original
    fig_mapa._imespec_radio = radio
    fig_mapa._imespec_botao_cosmic_detect = botao_cosmic_detect
    fig_mapa._imespec_botao_cosmic_apply = botao_cosmic_apply
    fig_mapa._imespec_botao_bad_detect = botao_bad_detect
    fig_mapa._imespec_botao_bad_apply = botao_bad_apply
    fig_mapa._imespec_botao_clear = botao_clear
    fig_mapa._imespec_botao_restore = botao_restore
    fig_mapa._imespec_botao_export = botao_export
    fig_mapa._imespec_export_history = export_history
    fig_mapa._imespec_cid_click = cid_click
    fig_mapa._imespec_imagem = imagem
    fig_mapa._imespec_colorbar = colorbar
    fig_mapa._imespec_display_limits = (vmin, vmax)
    fig_mapa._imespec_robust_display = escala_robusta
    if embed_parent is None:
        plt.show(block=False)
    else:
        fig_mapa._imespec_embedded_canvas = embedded_canvas
        fig_mapa._imespec_embedded_toolbar = embedded_toolbar
        embedded_canvas.draw_idle()
    return fig_mapa

def calcular_geometria_mapa(total_espectros, x_aquisicao, aplicar_correcao_andor=True):
    """
    Calcula a geometria a partir do número de pontos X informado.

    Por compatibilidade com o programa do professor, a correção Andor (+1)
    permanece disponível e vem ativada por padrão. Para dados de outro fluxo
    de aquisição, o usuário pode desativá-la e usar X diretamente.
    """
    if x_aquisicao is None:
        raise ValueError("X was not provided.")
    try:
        x_aquisicao = int(x_aquisicao)
    except (TypeError, ValueError):
        raise ValueError("X must be an integer.")
    if x_aquisicao <= 0:
        raise ValueError("X must be greater than zero.")
    aplicar_correcao_andor = bool(aplicar_correcao_andor)
    nx = x_aquisicao + 1 if aplicar_correcao_andor else x_aquisicao
    ny = int(total_espectros) // nx
    if ny <= 0:
        raise ValueError("This X value is larger than the number of spectra in the file.")
    pixels_usados = nx * ny
    sobrando = int(total_espectros) - pixels_usados
    return {
        "x_aquisicao": x_aquisicao,
        "nx": nx,
        "ny": ny,
        "pixels_usados": pixels_usados,
        "sobrando": sobrando,
        "quadrado": nx == ny and sobrando == 0,
        "andor_correction": aplicar_correcao_andor,
    }

def pedir_geometria_mapa(
    total_espectros,
    parent=None,
    valor_inicial=None,
    andor_inicial=True
):
    """
    Janela para confirmar a geometria espacial do mapa.

    O total de espectros, sozinho, não determina X×Y. A interface portanto
    exige que o usuário confirme o X real da aquisição e deixa explícita a
    correção Andor (+1) usada no código do professor.
    """
    resultado = {"valor": None}
    janela_geom = tk.Toplevel(parent)
    janela_geom.title("Raman Map Geometry")
    janela_geom.resizable(False, False)
    if parent is not None:
        janela_geom.transient(parent)
    quadro = tk.Frame(janela_geom, padx=20, pady=18)
    quadro.pack(fill="both", expand=True)
    tk.Label(
        quadro, text="Confirm Raman Map Geometry", font=("Segoe UI", 14, "bold")
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
    tk.Label(
        quadro,
        text=(
            f"The file contains {total_espectros} spectra.\n\n"
            "Enter the number of X positions used during acquisition. "
            "Do not infer X only from the total spectrum count."
        ),
        justify="left", wraplength=540
    ).grid(row=1, column=0, columnspan=2, sticky="w")
    tk.Label(quadro, text="X configured during acquisition:").grid(
        row=2, column=0, sticky="w", pady=(16, 5)
    )
    x_var = tk.StringVar()
    if valor_inicial is not None:
        x_var.set(str(valor_inicial))
    entrada = tk.Entry(quadro, textvariable=x_var, width=12)
    entrada.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(16, 5))
    andor_var = tk.BooleanVar(value=bool(andor_inicial))
    tk.Checkbutton(
        quadro,
        text="Apply Andor +1 correction (professor acquisition rule)",
        variable=andor_var
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 4))
    tk.Label(
        quadro,
        text=(
            "Keep this checked for the acquisition workflow in the professor's "
            "original code. Uncheck it only when the file geometry should use "
            "the entered X value directly."
        ),
        justify="left", wraplength=540, fg="#666666"
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 7))
    info_var = tk.StringVar()
    erro_var = tk.StringVar()
    tk.Label(
        quadro, textvariable=info_var, justify="left", anchor="w", font=("Consolas", 10)
    ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 8))
    tk.Label(
        quadro,
        text=(
            "Important: zero remaining spectra does not prove the geometry is correct. "
            "Use the X value from the actual scan configuration or metadata."
        ),
        justify="left", wraplength=540, fg="#8a4b08"
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 10))
    tk.Label(
        quadro, textvariable=erro_var, justify="left", wraplength=540, fg="#b00020"
    ).grid(row=7, column=0, columnspan=2, sticky="w")
    def calcular_previa():
        texto = x_var.get().strip()
        if not texto:
            info_var.set(
                "Internal X: —\nComplete rows (Y): —\nPixels used: —\nRemaining spectra: —"
            )
            erro_var.set("")
            return None
        try:
            geometria = calcular_geometria_mapa(
                total_espectros, texto, aplicar_correcao_andor=andor_var.get()
            )
        except ValueError as erro:
            info_var.set("")
            erro_var.set(str(erro))
            return None
        erro_var.set("")
        regra = " (+1 Andor)" if geometria["andor_correction"] else " (direct X)"
        info_var.set(
            f"Internal X{regra}: {geometria['nx']}\n"
            f"Complete rows (Y):  {geometria['ny']}\n"
            f"Pixels used:        {geometria['pixels_usados']}\n"
            f"Remaining spectra:  {geometria['sobrando']}"
        )
        return geometria
    def atualizar_previa(*args):
        calcular_previa()
    def usar_geometria():
        geometria = calcular_previa()
        if geometria is None:
            return
        regra = "Yes (+1)" if geometria["andor_correction"] else "No"
        confirmado = messagebox.askyesno(
            "Confirm Acquisition Geometry",
            f"X entered: {geometria['x_aquisicao']}\n"
            f"Andor correction: {regra}\n"
            f"Internal map: {geometria['nx']} × {geometria['ny']}\n"
            f"Pixels used: {geometria['pixels_usados']}\n"
            f"Remaining spectra: {geometria['sobrando']}\n\n"
            "Confirm only if this matches the acquisition geometry.",
            parent=janela_geom
        )
        if not confirmado:
            return
        resultado["valor"] = geometria
        janela_geom.destroy()
    def cancelar():
        resultado["valor"] = None
        janela_geom.destroy()
    botoes = tk.Frame(quadro)
    botoes.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))
    tk.Button(botoes, text="Cancel", command=cancelar, width=12).pack(
        side="left", padx=(0, 8)
    )
    tk.Button(botoes, text="Use Geometry", command=usar_geometria, width=16).pack(
        side="left"
    )
    x_var.trace_add("write", atualizar_previa)
    andor_var.trace_add("write", atualizar_previa)
    atualizar_previa()
    janela_geom.protocol("WM_DELETE_WINDOW", cancelar)
    entrada.focus_set()
    janela_geom.grab_set()
    janela_geom.wait_window()
    return resultado["valor"]

def pedir_valores(parent=None):
    """
    Compatibilidade com versões antigas do IMESPEC.

    A interface modular atual usa pedir_geometria_mapa().
    """
    from tkinter import simpledialog
    return simpledialog.askinteger(
        "X Points",
        "Number of X pixels:",
        parent=parent
    )

# ============================================================
# PARTE 2 — MULTI SPECTRA
# Fluxo baseado no programa fornecido pelo professor.
# Cada espectro vem de um arquivo .txt separado.
# ============================================================
import re

def chave_ordenacao_natural(caminho):
    """
    Chave de ordenação "natural" para nomes de arquivo.

    Diferente da ordenação puramente alfabética, os blocos numéricos
    são comparados como números. Assim, por exemplo:

        5K, 20K, 80K, 100K, 300K

    ficam nessa ordem mesmo que não possuam zeros à esquerda.
    """
    nome = os.path.basename(caminho).casefold()
    partes = re.split(r'(\d+(?:\.\d+)?)', nome)
    chave = []
    for parte in partes:
        if not parte:
            continue
        if re.fullmatch(r'\d+(?:\.\d+)?', parte):
            chave.append((0, float(parte)))
        else:
            chave.append((1, parte))
    return tuple(chave)

def ordenar_caminhos_natural(caminhos):
    """Retorna uma nova lista de caminhos em ordenação natural."""
    return sorted(caminhos, key=chave_ordenacao_natural)

def copiar_multiespectros(f3):
    """Cópia independente de [x1, y1, x2, y2, ...]."""
    return [np.asarray(vetor).copy() for vetor in f3]

def _parse_numeric_token(token, decimal_comma=False):
    """Parse one numeric field used by the robust spectrum text importer."""
    token = str(token).strip().strip('"').strip("'")
    if not token:
        raise ValueError("empty numeric token")
    if decimal_comma:
        token = token.replace(',', '.')
    # Common Unicode minus copied/exported by some applications.
    token = token.replace('\u2212', '-')
    return float(token)

def _split_spectral_line(line):
    """
    Return numeric fields from a likely spectrum data row, or None.

    Supported common text layouts:
      - whitespace separated TXT / ASCII
      - tab separated TSV
      - semicolon separated CSV (including decimal comma)
      - comma separated CSV with decimal point

    Header/metadata lines are deliberately rejected here and skipped later.
    """
    raw = str(line).strip()
    if not raw:
        return None
    if raw.startswith(('#', '//', '%')):
        return None
    # Prefer explicit separators before generic whitespace.
    if '\t' in raw:
        parts = [p.strip() for p in raw.split('\t')]
        decimal_comma = any(',' in p and '.' not in p for p in parts[:2])
    elif ';' in raw:
        parts = [p.strip() for p in raw.split(';')]
        # Semicolon exports commonly use decimal commas in European locales.
        decimal_comma = any(',' in p and '.' not in p for p in parts[:2])
    elif ',' in raw:
        # Comma delimiter is treated as CSV with decimal point. Decimal-comma
        # files are expected to use tab/semicolon separators, as is customary.
        parts = [p.strip() for p in raw.split(',')]
        decimal_comma = False
    else:
        parts = raw.split()
        decimal_comma = any(',' in p and '.' not in p for p in parts[:2])
    if len(parts) < 2:
        return None
    try:
        values = [_parse_numeric_token(p, decimal_comma=decimal_comma) for p in parts]
    except ValueError:
        return None
    if len(values) < 2 or not np.isfinite(values[0]) or not np.isfinite(values[1]):
        return None
    return values

def ler_espectro_texto(caminho, dtype=np.float32):
    """
    Robust importer for two-or-more-column Raman text spectra.

    Unlike ``numpy.loadtxt`` this accepts ordinary column headers and metadata
    before/after the numeric table. The longest contiguous numeric block is
    interpreted as the spectrum, which avoids mistaking isolated metadata
    numbers (laser wavelength, acquisition time, etc.) for spectral data.
    """
    encodings = ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1')
    linhas = None
    ultimo_erro = None
    for encoding in encodings:
        try:
            with open(caminho, 'r', encoding=encoding) as fh:
                linhas = fh.readlines()
            break
        except UnicodeDecodeError as exc:
            ultimo_erro = exc
    if linhas is None:
        raise ValueError(
            f"Could not decode '{os.path.basename(caminho)}' as a text spectrum: {ultimo_erro}"
        )
    blocos = []
    atual = []
    for line in linhas:
        parsed = _split_spectral_line(line)
        if parsed is None:
            if atual:
                blocos.append(atual)
                atual = []
            continue
        atual.append(parsed)
    if atual:
        blocos.append(atual)
    if not blocos:
        raise ValueError(
            f"The file '{os.path.basename(caminho)}' does not contain a numeric spectral table."
        )
    # The actual spectrum is overwhelmingly the longest numeric block.
    bloco = max(blocos, key=len)
    if len(bloco) < 2:
        raise ValueError(
            f"The file '{os.path.basename(caminho)}' does not contain enough spectral data points."
        )
    ncols = min(len(row) for row in bloco)
    if ncols < 2:
        raise ValueError(
            f"The file '{os.path.basename(caminho)}' does not contain at least two numeric columns."
        )
    # Keep all consistently available columns for future compatibility, while
    # current IMESPEC analysis uses the first two (shift, intensity).
    data = np.asarray([row[:ncols] for row in bloco], dtype=dtype)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(
            f"The file '{os.path.basename(caminho)}' does not contain at least two columns."
        )
    return data

def carregar_multiespectros(caminhos, ordenar=True):
    """
    Recebe vários arquivos de texto de espectros Raman.

    Cada arquivo deve ter pelo menos duas colunas numéricas:
        coluna 0 -> Raman shift
        coluna 1 -> intensidade

    Cabeçalhos e blocos comuns de metadados são aceitos. O importador reconhece
    TXT/ASCII por espaços, TSV, CSV por vírgula e CSV por ponto-e-vírgula.

    Por padrão aplica ordenação natural antes de montar:

        f3 = [x1, y1, x2, y2, ...]

    Se ordenar=False, preserva exatamente a ordem recebida. Isso é
    usado depois que o usuário revisa/reorganiza a lista na interface.
    """
    if not caminhos:
        return [], []
    if ordenar:
        caminhos_ordenados = ordenar_caminhos_natural(caminhos)
    else:
        caminhos_ordenados = list(caminhos)
    f3 = []
    for caminho in caminhos_ordenados:
        f2 = ler_espectro_texto(caminho, dtype=np.float32)
        if f2.ndim != 2 or f2.shape[1] < 2:
            raise ValueError(
                f"The file '{os.path.basename(caminho)}' "
                "does not contain at least two columns."
            )
        if f2.shape[0] < 2:
            raise ValueError(
                f"The file '{os.path.basename(caminho)}' "
                "does not contain enough data points."
            )
        if not np.all(np.isfinite(f2[:, :2])):
            raise ValueError(
                f"The file '{os.path.basename(caminho)}' "
                "contains non-finite values in the first two columns."
            )
        eixo = np.asarray(f2[:, 0], dtype=float)
        dx = np.diff(eixo)
        if np.any(np.abs(dx) <= np.finfo(float).eps):
            raise ValueError(
                f"The file '{os.path.basename(caminho)}' contains repeated Raman-shift values."
            )
        if not (np.all(dx > 0) or np.all(dx < 0)):
            raise ValueError(
                f"The file '{os.path.basename(caminho)}' Raman-shift axis must be strictly monotonic."
            )
        f3.append(f2[:, 0].copy())
        f3.append(f2[:, 1].copy())
    return f3, caminhos_ordenados

def _indices_faixa(colx, x_in, x_fi):
    """
    Localiza os índices mais próximos dos limites de uma faixa.

    A rotina do professor usa os pontos mais próximos de x_in e x_fi.
    Aqui apenas garantimos uma fatia válida também se o eixo x estiver
    armazenado em ordem decrescente.
    """
    idx_a = int(np.argmin(np.abs(colx - x_in)))
    idx_b = int(np.argmin(np.abs(colx - x_fi)))
    inicio = min(idx_a, idx_b)
    fim = max(idx_a, idx_b)
    if inicio == fim:
        raise ValueError(
            "Peak range is too narrow: both limits point to the same data point."
        )
    return inicio, fim

def corrigir_linha_base_linear(f3, x_esq, x_dir, meia_janela=5.0):
    """
    Correção de linha de base linear adicionada ao IMESPEC.

    IMPORTANTE:
    Esta rotina NÃO veio do material do professor. Ela é uma ferramenta
    transparente e conservadora do IMESPEC enquanto uma rotina específica
    do projeto não for fornecida/definida.

    Para cada espectro:
      1. calcula a intensidade média em uma pequena região ao redor de x_esq;
      2. calcula a intensidade média ao redor de x_dir;
      3. constrói a reta que liga esses dois níveis;
      4. subtrai essa reta do espectro inteiro.

    Os dois pontos de ancoragem devem ser escolhidos em regiões sem picos Raman.

    Parâmetros:
      f3           : [x1, y1, x2, y2, ...]
      x_esq        : centro da região de ancoragem esquerda (cm^-1)
      x_dir        : centro da região de ancoragem direita (cm^-1)
      meia_janela  : meia largura de cada região de média (cm^-1)

    Retorna uma nova lista [x1, y1_corrigido, x2, y2_corrigido, ...].
    """
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    x_esq = float(x_esq)
    x_dir = float(x_dir)
    meia_janela = float(meia_janela)
    if not np.isfinite(x_esq) or not np.isfinite(x_dir):
        raise ValueError("Baseline anchor positions must be finite.")
    if not np.isfinite(meia_janela) or meia_janela < 0:
        raise ValueError("Baseline anchor half-window must be finite and non-negative.")
    if x_esq == x_dir:
        raise ValueError("Left and right baseline anchors must be different.")
    corrigidos = []
    numero_espectros = len(f3) // 2
    def media_ancora(x, y, centro):
        if centro < float(np.min(x)) or centro > float(np.max(x)):
            raise ValueError(
                f"Baseline anchor {centro:g} cm^-1 is outside the spectrum range "
                f"({float(np.min(x)):g}–{float(np.max(x)):g} cm^-1)."
            )
        if meia_janela > 0:
            mascara = np.abs(x - centro) <= meia_janela
        else:
            mascara = np.zeros(x.shape, dtype=bool)
        # Se a janela for muito estreita para a amostragem disponível,
        # usa o ponto medido mais próximo. Isso evita depender da resolução.
        if not np.any(mascara):
            indice = int(np.argmin(np.abs(x - centro)))
            return float(x[indice]), float(y[indice])
        return (
            float(np.mean(x[mascara], dtype=np.float64)),
            float(np.mean(y[mascara], dtype=np.float64))
        )
    for p in range(numero_espectros):
        x = np.asarray(f3[2 * p])
        y = np.asarray(f3[2 * p + 1])
        if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
            raise ValueError(f"Spectrum {p + 1} has invalid x/y data.")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError(f"Spectrum {p + 1} contains non-finite values.")
        xa, ya = media_ancora(x, y, x_esq)
        xb, yb = media_ancora(x, y, x_dir)
        if abs(xb - xa) <= np.finfo(float).eps:
            raise ValueError(
                f"Baseline anchors collapse to the same sampled x value in spectrum {p + 1}."
            )
        inclinacao = (yb - ya) / (xb - xa)
        intercepto = ya - inclinacao * xa
        linha_base = inclinacao * x.astype(np.float64) + intercepto
        y_corrigido = y.astype(np.float64) - linha_base
        corrigidos.append(x.copy())
        corrigidos.append(y_corrigido)
    return corrigidos

# ============================================================
# BASELINE arPLS (Baek et al., Analyst 2015)
# ============================================================

def _resolver_pentadiagonal_simetrica(diag, off1, off2, rhs):
    """Resolve uma matriz simétrica pentadiagonal positiva definida em O(n)."""
    diag = np.asarray(diag, dtype=np.float64)
    off1 = np.asarray(off1, dtype=np.float64)
    off2 = np.asarray(off2, dtype=np.float64)
    rhs = np.asarray(rhs, dtype=np.float64)
    n = diag.size
    if rhs.size != n or off1.size != max(0, n - 1) or off2.size != max(0, n - 2):
        raise ValueError("Invalid pentadiagonal system dimensions.")
    l0 = np.zeros(n, dtype=np.float64)
    l1 = np.zeros(n, dtype=np.float64)
    l2 = np.zeros(n, dtype=np.float64)
    valor = diag[0]
    if valor <= 0 or not np.isfinite(valor):
        raise np.linalg.LinAlgError("arPLS system is not positive definite.")
    l0[0] = np.sqrt(valor)
    if n >= 2:
        l1[1] = off1[0] / l0[0]
        valor = diag[1] - l1[1] ** 2
        if valor <= 0 or not np.isfinite(valor):
            raise np.linalg.LinAlgError("arPLS system is not positive definite.")
        l0[1] = np.sqrt(valor)
    for i in range(2, n):
        l2[i] = off2[i - 2] / l0[i - 2]
        l1[i] = (off1[i - 1] - l2[i] * l1[i - 1]) / l0[i - 1]
        valor = diag[i] - l1[i] ** 2 - l2[i] ** 2
        if valor <= 0 or not np.isfinite(valor):
            raise np.linalg.LinAlgError("arPLS system is not positive definite.")
        l0[i] = np.sqrt(valor)
    ytmp = np.zeros(n, dtype=np.float64)
    ytmp[0] = rhs[0] / l0[0]
    if n >= 2:
        ytmp[1] = (rhs[1] - l1[1] * ytmp[0]) / l0[1]
    for i in range(2, n):
        ytmp[i] = (rhs[i] - l1[i] * ytmp[i - 1] - l2[i] * ytmp[i - 2]) / l0[i]
    sol = np.zeros(n, dtype=np.float64)
    sol[-1] = ytmp[-1] / l0[-1]
    if n >= 2:
        sol[-2] = (ytmp[-2] - l1[-1] * sol[-1]) / l0[-2]
    for i in range(n - 3, -1, -1):
        sol[i] = (
            ytmp[i]
            - l1[i + 1] * sol[i + 1]
            - l2[i + 2] * sol[i + 2]
        ) / l0[i]
    return sol
@lru_cache(maxsize=16)
def _arpls_sparse_penalty(n, lam):
    """Cache the second-difference penalty matrix used by arPLS."""
    if not _SCIPY_AVAILABLE or sparse is None:
        return None
    n = int(n)
    lam = float(lam)
    diagonals = [
        np.ones(n - 2, dtype=float),
        -2.0 * np.ones(n - 2, dtype=float),
        np.ones(n - 2, dtype=float),
    ]
    D = sparse.diags(
        diagonals, offsets=[0, 1, 2],
        shape=(n - 2, n), format="csc"
    )
    return lam * (D.T @ D)

def calcular_linha_base_arpls(y, lam=1e5, max_iter=50, tol=1e-3):
    """
    Estima a linha de base pelo método arPLS (Asymmetrically Reweighted
    Penalized Least Squares), de Baek et al. (Analyst, 2015).

    A formulação é:
        (W + lambda D^T D) z = W y
    com atualização logística dos pesos a partir dos resíduos negativos.

    Se SciPy estiver instalado, usa solução esparsa para maior velocidade. Se
    não estiver, usa um solver pentadiagonal próprio em NumPy, mantendo o
    programa funcional sem transformar SciPy em dependência obrigatória.
    """
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 1 or y.size < 4:
        raise ValueError("arPLS requires a one-dimensional spectrum with at least 4 points.")
    if not np.all(np.isfinite(y)):
        raise ValueError("arPLS requires finite intensity values.")
    lam = float(lam)
    tol = float(tol)
    max_iter = int(max_iter)
    if not np.isfinite(lam) or lam <= 0:
        raise ValueError("arPLS lambda must be positive and finite.")
    if not np.isfinite(tol) or tol <= 0:
        raise ValueError("arPLS tolerance must be positive and finite.")
    if max_iter < 1:
        raise ValueError("arPLS max iterations must be at least 1.")
    n = y.size
    # Diagonais de D^T D para segunda diferença [1, -2, 1].
    pen_diag = np.full(n, 6.0, dtype=np.float64)
    pen_diag[0] = pen_diag[-1] = 1.0
    pen_diag[1] = pen_diag[-2] = 5.0
    pen_off1 = np.full(n - 1, -4.0, dtype=np.float64)
    pen_off1[0] = pen_off1[-1] = -2.0
    pen_off2 = np.ones(n - 2, dtype=np.float64)
    pesos = np.ones(n, dtype=np.float64)
    baseline = y.copy()
    historico = []
    convergiu = False
    penalidade_sparse = None
    if _SCIPY_AVAILABLE:
        # All spectra of the same length and lambda share exactly the same
        # Whittaker penalty. Cache it instead of rebuilding D.T @ D for every
        # spectrum in a Multi-Spectra batch.
        penalidade_sparse = _arpls_sparse_penalty(n, lam)
    for _ in range(max_iter + 1):
        if _SCIPY_AVAILABLE:
            # SciPy sparse is substantially faster for long Raman series.
            W = sparse.diags(pesos, offsets=0, shape=(n, n), format="csc")
            baseline = spsolve(W + penalidade_sparse, pesos * y)
        else:
            # Fallback sem SciPy: mesma matriz, resolvida como sistema
            # pentadiagonal por Cholesky bandada.
            diag = pesos + lam * pen_diag
            off1 = lam * pen_off1
            off2 = lam * pen_off2
            baseline = _resolver_pentadiagonal_simetrica(
                diag, off1, off2, pesos * y
            )
        residuo = y - baseline
        negativos = residuo[residuo < 0]
        if negativos.size < 2:
            convergiu = True
            break
        media_neg = float(np.mean(negativos))
        sigma_neg = float(np.std(negativos, ddof=0))
        if not np.isfinite(sigma_neg) or sigma_neg <= np.finfo(float).eps:
            convergiu = True
            break
        centro = -media_neg + 2.0 * sigma_neg
        argumento = 2.0 * (residuo - centro) / sigma_neg
        argumento = np.clip(argumento, -700.0, 700.0)
        novos_pesos = 1.0 / (1.0 + np.exp(argumento))
        denominador = np.linalg.norm(pesos)
        diferenca = float(
            np.linalg.norm(novos_pesos - pesos)
            / max(denominador, np.finfo(float).eps)
        )
        historico.append(diferenca)
        pesos = novos_pesos
        if diferenca < tol:
            convergiu = True
            break
    return np.asarray(baseline, dtype=float), {
        "converged": bool(convergiu),
        "iterations": len(historico),
        "tol_history": np.asarray(historico, dtype=float),
        "lambda": lam,
        "tol": tol,
    }

def corrigir_linha_base_arpls(f3, lam=1e5, max_iter=50, tol=1e-3):
    """Aplica arPLS independentemente a cada espectro de uma série."""
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    corrigidos = []
    infos = []
    for p in range(len(f3) // 2):
        x = np.asarray(f3[2 * p])
        y = np.asarray(f3[2 * p + 1], dtype=float)
        baseline, info = calcular_linha_base_arpls(
            y, lam=lam, max_iter=max_iter, tol=tol
        )
        corrigidos.append(x.copy())
        corrigidos.append(y - baseline)
        infos.append(info)
    return corrigidos, infos

# ============================================================
# BASELINE AUTOMÁTICO / VISUAL PARA MULTI-SPECTRA
# ============================================================

def _media_movel(vetor, janela):
    """Suavização simples usada apenas para DETECÇÃO de regiões de baseline."""
    y = np.asarray(vetor, dtype=float)
    n = y.size
    if n < 3:
        return y.copy()
    janela = int(max(3, janela))
    if janela % 2 == 0:
        janela += 1
    janela = min(janela, n if n % 2 == 1 else n - 1)
    if janela < 3:
        return y.copy()
    metade = janela // 2
    ypad = np.pad(y, (metade, metade), mode="edge")
    kernel = np.ones(janela, dtype=float) / float(janela)
    return np.convolve(ypad, kernel, mode="valid")

def construir_espectro_representativo(f3):
    """
    Constrói um espectro representativo da série para a escolha automática
    das regiões de baseline.

    Cada espectro é interpolado para o eixo X do primeiro espectro dentro da
    faixa comum, centrado por um percentil baixo e escalado pela amplitude
    robusta. Depois é calculada a mediana ponto a ponto.

    Isso evita que um único espectro muito intenso domine a detecção.
    """
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    numero = len(f3) // 2
    minimos = []
    maximos = []
    for p in range(numero):
        x = np.asarray(f3[2 * p], dtype=float)
        if x.ndim != 1 or x.size < 3 or not np.all(np.isfinite(x)):
            raise ValueError(f"Spectrum {p + 1} has an invalid Raman shift axis.")
        minimos.append(float(np.min(x)))
        maximos.append(float(np.max(x)))
    comum_min = max(minimos)
    comum_max = min(maximos)
    if comum_max <= comum_min:
        raise ValueError("The spectra do not share a common Raman shift range.")
    x0 = np.asarray(f3[0], dtype=float)
    mascara = (x0 >= comum_min) & (x0 <= comum_max)
    xref = x0[mascara]
    if xref.size < 20:
        raise ValueError("The common Raman shift range is too small for automatic baseline detection.")
    # np.interp exige eixo crescente.
    ordem_ref = np.argsort(xref)
    xref_crescente = xref[ordem_ref]
    pilha = []
    for p in range(numero):
        x = np.asarray(f3[2 * p], dtype=float)
        y = np.asarray(f3[2 * p + 1], dtype=float)
        if x.shape != y.shape or not np.all(np.isfinite(y)):
            raise ValueError(f"Spectrum {p + 1} has invalid intensity data.")
        ordem = np.argsort(x)
        xs = x[ordem]
        ys = y[ordem]
        yi = np.interp(xref_crescente, xs, ys)
        centro = float(np.percentile(yi, 20.0))
        p10, p90 = np.percentile(yi, [10.0, 90.0])
        escala = float(p90 - p10)
        if not np.isfinite(escala) or escala <= np.finfo(float).eps:
            escala = float(np.std(yi))
        if not np.isfinite(escala) or escala <= np.finfo(float).eps:
            escala = 1.0
        pilha.append((yi - centro) / escala)
    representante = np.median(np.asarray(pilha, dtype=float), axis=0)
    return xref_crescente, representante

# ============================================================
# SUGESTÕES AUTOMÁTICAS DE ANÁLISE
# ============================================================

def _amostrar_multiespectros(f3, max_spectra=64):
    """Subconjunto uniforme usado apenas para diagnósticos rápidos da interface."""
    n = len(f3) // 2
    if n <= max_spectra:
        return f3
    idx = np.linspace(0, n - 1, int(max_spectra), dtype=int)
    out = []
    for i in idx:
        out.extend([f3[2*i], f3[2*i+1]])
    return out

def _ruido_robusto_1d(y):
    """Estimativa simples de ruído baseada na diferença entre pontos vizinhos."""
    y = np.asarray(y, dtype=float)
    if y.size < 5:
        return 0.0
    d = np.diff(y)
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med)))
    sigma = mad / 0.6744897501960817 / np.sqrt(2.0) if mad > 0 else float(np.std(d)) / np.sqrt(2.0)
    return float(max(sigma, np.finfo(float).eps))

def _lambda_arpls_sugerido(n_pontos):
    """Escolhe uma rigidez inicial coerente com o tamanho do eixo espectral."""
    n = max(int(n_pontos), 10)
    bruto = 1e5 * (n / 700.0) ** 2
    pot = int(np.clip(np.round(np.log10(max(bruto, 1e4))), 4, 8))
    return float(10 ** pot)

def detectar_picos_representativos(f3, max_peaks=6):
    """
    Procura picos recorrentes numa série sem alterar os dados.

    A mediana robusta evita que um único espectro domine a sugestão. A seleção
    usa proeminência e largura, parâmetros que são mais estáveis do que um
    simples limiar de altura quando a linha de base ainda não foi corrigida.
    """
    x, y = construir_espectro_representativo(f3)
    lam = _lambda_arpls_sugerido(x.size)
    try:
        baseline, _ = calcular_linha_base_arpls(y, lam=lam, tol=1e-3, max_iter=60)
        yc = y - baseline
    except Exception:
        yc = y - np.percentile(y, 15.0)
    janela = max(5, int(round(x.size / 350)))
    if janela % 2 == 0:
        janela += 1
    ys = _media_movel(yc, janela)
    noise = _ruido_robusto_1d(ys)
    robust_amp = float(np.percentile(ys, 95) - np.percentile(ys, 10))
    prominence = max(5.0 * noise, 0.035 * max(robust_amp, np.finfo(float).eps))
    distance = max(3, int(round(x.size / max(20, int(max_peaks) * 5))))
    if find_peaks is None:
        # Fallback conservador para ambientes em que SciPy ainda não foi instalado.
        idx = np.where((ys[1:-1] > ys[:-2]) & (ys[1:-1] >= ys[2:]))[0] + 1
        idx = idx[np.argsort(ys[idx])[-int(max_peaks):]] if idx.size else idx
        props = {}
    else:
        idx, props = find_peaks(ys, prominence=prominence, distance=distance, width=1)
        if idx.size > int(max_peaks):
            ranking = np.asarray(props.get('prominences', ys[idx]), dtype=float)
            idx = idx[np.argsort(ranking)[-int(max_peaks):]]
    idx = np.asarray(sorted(int(i) for i in idx), dtype=int)
    if idx.size == 0:
        return []
    dx = float(np.median(np.abs(np.diff(x)))) if x.size > 1 else 1.0
    widths = None
    if find_peaks is not None and peak_widths is not None:
        try:
            widths = peak_widths(ys, idx, rel_height=0.5)[0] * dx
        except Exception:
            widths = None
    picos = []
    for j, i in enumerate(idx):
        fwhm = float(widths[j]) if widths is not None else max(6.0 * dx, 0.012 * abs(x[-1] - x[0]))
        half = float(np.clip(2.5 * fwhm, max(8.0 * dx, 4.0), 0.14 * abs(x[-1] - x[0])))
        picos.append({
            'center': float(x[i]),
            'height': float(ys[i]),
            'fwhm_est': float(fwhm),
            'half_window': half,
            'index': int(i),
        })
    return picos

def sugerir_configuracao_multiespectros(f3):
    """
    Faz um diagnóstico rápido e devolve parâmetros iniciais para Multi-Spectra.

    A função só prepara sugestões; nenhum vetor é alterado aqui. Isso deixa o
    modo automático útil para quem está começando, mas mantém a revisão manual
    disponível para uma análise mais específica.
    """
    if len(f3) < 2 or len(f3) % 2:
        raise ValueError('Invalid Multi-Spectra data structure.')
    amostra = _amostrar_multiespectros(f3, max_spectra=64)
    xrep, yrep = construir_espectro_representativo(amostra)
    lam = _lambda_arpls_sugerido(xrep.size)
    try:
        base, _ = calcular_linha_base_arpls(yrep, lam=lam, tol=1e-3, max_iter=60)
        drift = float(np.ptp(base) / max(np.ptp(yrep), np.finfo(float).eps))
    except Exception:
        drift = 0.0
    picos = detectar_picos_representativos(amostra, max_peaks=6)
    quiet_x = float(sugerir_x_referencia_multiespectros(f3))
    peak = max(picos, key=lambda p: p['height']) if picos else None
    norm_ini = norm_fim = None
    norm_ref = 0
    if peak is not None:
        largura = max(float(peak['fwhm_est']) * 1.15, 0.008 * abs(xrep[-1] - xrep[0]))
        norm_ini = max(float(xrep[0]), float(peak['center']) - largura)
        norm_fim = min(float(xrep[-1]), float(peak['center']) + largura)
        # Usa como referência o espectro mais próximo da altura mediana do pico.
        heights = []
        for p in range(len(f3) // 2):
            x = np.asarray(f3[2*p], dtype=float)
            y = np.asarray(f3[2*p+1], dtype=float)
            ib = int(np.argmin(np.abs(x - quiet_x)))
            mask = (x >= min(norm_ini, norm_fim)) & (x <= max(norm_ini, norm_fim))
            heights.append(float(np.max(y[mask]) - y[ib]) if np.any(mask) else np.nan)
        arr = np.asarray(heights, dtype=float)
        valid = np.where(np.isfinite(arr) & (np.abs(arr) > np.finfo(float).eps))[0]
        if valid.size:
            med = float(np.median(arr[valid]))
            norm_ref = int(valid[np.argmin(np.abs(arr[valid] - med))])
    try:
        cosmic = detectar_cosmic_rays_multiespectros(amostra, threshold=10.0, max_width=3.0)
        cosmic_events = int(sum(len(item.get('events', [])) for item in cosmic.get('spectra', [])))
    except Exception:
        cosmic_events = 0
    amps = []
    for p in range(len(f3) // 2):
        y = np.asarray(f3[2*p+1], dtype=float)
        amps.append(float(np.percentile(y, 99.5) - np.percentile(y, 15)))
    amp_med = float(np.median(amps)) if amps else 1.0
    delta = max(1.0, 2.2 * amp_med)
    ordem = 10 ** np.floor(np.log10(delta)) if delta > 0 else 1.0
    delta = float(round(delta / ordem, 1) * ordem)
    return {
        'cosmic_enabled': cosmic_events > 0,
        'cosmic_events': cosmic_events,
        'cosmic_sampled': (len(f3) // 2) > (len(amostra) // 2),
        'baseline_enabled': drift >= 0.025,
        'baseline_score': drift,
        'baseline_lambda': lam,
        'normalization_enabled': peak is not None,
        'normalization_baseline_x': quiet_x,
        'normalization_peak_start': norm_ini,
        'normalization_peak_end': norm_fim,
        'normalization_reference': norm_ref,
        'distribution_enabled': len(f3) >= 4,
        'distribution_reference_x': quiet_x,
        'distribution_offset': delta,
        'detected_peaks': picos,
    }

def sugerir_banda_raman_mapa(matriz, max_peaks=5):
    """Sugere uma banda de integração a partir do comportamento comum do mapa."""
    b = np.asarray(matriz, dtype=float)
    if b.ndim != 2 or b.shape[1] < 2:
        raise ValueError('Raman map matrix must contain an axis and at least one spectrum.')
    x = b[:, 0]
    y = b[:, 1:]
    if y.shape[1] > 512:
        # Amostra espacialmente para manter a abertura rápida em mapas grandes.
        cols = np.linspace(0, y.shape[1]-1, 512, dtype=int)
        y = y[:, cols]
    centers = np.percentile(y, 20, axis=0)
    scales = np.percentile(y, 90, axis=0) - np.percentile(y, 10, axis=0)
    scales[~np.isfinite(scales) | (np.abs(scales) <= np.finfo(float).eps)] = 1.0
    rep = np.median((y - centers) / scales, axis=1)
    peaks = detectar_picos_representativos([x, rep], max_peaks=max_peaks)
    if not peaks:
        return None
    peak = max(peaks, key=lambda p: p['height'])
    half = max(float(peak['fwhm_est']), 0.006 * abs(x[-1] - x[0]))
    xmin = float(max(np.min(x), peak['center'] - half))
    xmax = float(min(np.max(x), peak['center'] + half))
    return {
        'center': float(peak['center']),
        'start': min(xmin, xmax),
        'end': max(xmin, xmax),
        'fwhm_est': float(peak['fwhm_est']),
        'detected_peaks': peaks,
    }

def detectar_ancoras_baseline_automaticas(f3, numero_ancoras=12):
    """
    Detecta automaticamente posições X prováveis de linha de base.

    Estratégia:
      1. analisa toda a série por meio de um espectro representativo robusto;
      2. estima uma envoltória inferior local para reconhecer regiões elevadas
         por bandas Raman, inclusive bandas relativamente largas;
      3. procura pontos baixos, suaves e pouco curvos em várias regiões da faixa;
      4. rejeita regiões que ainda parecem estar sobre picos;
      5. devolve X comuns para todos os espectros.

    A função NÃO altera dados. O resultado é uma proposta que deve continuar
    visível/revisável na interface.
    """
    x, y = construir_espectro_representativo(f3)
    n = x.size
    numero_ancoras = int(max(4, min(int(numero_ancoras), 18)))
    # Suavização curta: reduz ruído sem tentar apagar bandas reais.
    janela_curta = max(5, int(round(n / 250)))
    if janela_curta % 2 == 0:
        janela_curta += 1
    ys = _media_movel(y, janela_curta)
    # Envoltória inferior local. Uma janela larga ajuda a reconhecer quando
    # um segmento inteiro está elevado por uma banda Raman ampla.
    janela_env = max(31, int(round(n / 8)))
    if janela_env % 2 == 0:
        janela_env += 1
    metade = janela_env // 2
    ypad = np.pad(ys, (metade, metade), mode="edge")
    janelas = np.lib.stride_tricks.sliding_window_view(ypad, janela_env)
    envoltoria = np.percentile(janelas, 20.0, axis=1)
    envoltoria = _media_movel(envoltoria, max(5, int(round(n / 180))))
    amplitude = float(np.percentile(ys, 90.0) - np.percentile(ys, 10.0))
    if not np.isfinite(amplitude) or amplitude <= np.finfo(float).eps:
        amplitude = float(np.std(ys))
    if not np.isfinite(amplitude) or amplitude <= np.finfo(float).eps:
        amplitude = 1.0
    elevacao_pico = np.maximum(ys - envoltoria, 0.0) / amplitude
    grad = np.gradient(ys, x)
    curv = np.gradient(grad, x)
    def normalizar_abs(v):
        a = np.abs(np.asarray(v, dtype=float))
        escala = float(np.percentile(a, 75.0))
        if not np.isfinite(escala) or escala <= np.finfo(float).eps:
            escala = float(np.max(a)) if a.size else 1.0
        if not np.isfinite(escala) or escala <= np.finfo(float).eps:
            escala = 1.0
        return a / escala
    grad_n = normalizar_abs(grad)
    curv_n = normalizar_abs(curv)
    # Mais regiões do que âncoras desejadas: regiões ruins podem ser puladas.
    numero_regioes = max(14, min(22, numero_ancoras + 6))
    borda = max(2, int(round(0.01 * n)))
    limites = np.linspace(borda, n - borda, numero_regioes + 1, dtype=int)
    propostas = []
    for i in range(numero_regioes):
        ini = int(limites[i])
        fim = int(limites[i + 1])
        if fim - ini < 3:
            continue
        idx = np.arange(ini, fim)
        yseg = ys[idx]
        limite_baixo = float(np.percentile(yseg, 45.0))
        candidatos = idx[yseg <= limite_baixo]
        if candidatos.size == 0:
            candidatos = idx
        ymin = float(np.min(yseg))
        yrange = float(np.max(yseg) - ymin)
        if yrange <= np.finfo(float).eps:
            altura_n = np.zeros(candidatos.size, dtype=float)
        else:
            altura_n = (ys[candidatos] - ymin) / yrange
        score = (
            2.00 * elevacao_pico[candidatos]
            + 0.35 * grad_n[candidatos]
            + 0.15 * curv_n[candidatos]
            + 0.20 * altura_n
        )
        melhor = int(candidatos[int(np.argmin(score))])
        propostas.append({
            "indice": melhor,
            "x": float(x[melhor]),
            "peakness": float(elevacao_pico[melhor]),
            "score": float(np.min(score))
        })
    # Primeiro usa um critério conservador. Se isso deixar menos de quatro
    # regiões, relaxa discretamente para ainda permitir um baseline utilizável.
    boas = [p for p in propostas if p["peakness"] <= 0.05]
    if len(boas) < 4:
        boas = [p for p in propostas if p["peakness"] <= 0.10]
    if len(boas) < 4:
        boas = sorted(propostas, key=lambda p: p["score"])[:max(4, numero_ancoras)]
    boas.sort(key=lambda p: p["x"])
    # Evita várias âncoras quase no mesmo vale. Se duas propostas estiverem
    # muito próximas, fica a de melhor score.
    largura_total = float(x[-1] - x[0])
    espacamento_min = largura_total / max(18.0, numero_ancoras * 1.3)
    filtradas = []
    for proposta in boas:
        if not filtradas:
            filtradas.append(proposta)
            continue
        if proposta["x"] - filtradas[-1]["x"] < espacamento_min:
            if proposta["score"] < filtradas[-1]["score"]:
                filtradas[-1] = proposta
        else:
            filtradas.append(proposta)
    # Se sobraram mais que o alvo, mantém uma distribuição espacial razoável.
    if len(filtradas) > numero_ancoras:
        indices = np.linspace(0, len(filtradas) - 1, numero_ancoras)
        indices = sorted(set(int(round(v)) for v in indices))
        filtradas = [filtradas[i] for i in indices]
    if len(filtradas) < 2:
        raise ValueError("Automatic baseline detection could not find enough safe regions.")
    return [float(p["x"]) for p in filtradas]

def _nivel_ancora(x, y, centro, meia_janela):
    """Retorna (x_médio, y_mediano) em uma pequena região de ancoragem."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    centro = float(centro)
    meia_janela = float(meia_janela)
    if centro < float(np.min(x)) or centro > float(np.max(x)):
        raise ValueError(
            f"Baseline anchor {centro:g} cm^-1 is outside the spectrum range "
            f"({float(np.min(x)):g}–{float(np.max(x)):g} cm^-1)."
        )
    mascara = np.abs(x - centro) <= meia_janela if meia_janela > 0 else np.zeros(x.shape, bool)
    if not np.any(mascara):
        indice = int(np.argmin(np.abs(x - centro)))
        return float(x[indice]), float(y[indice])
    # Mediana é mais resistente a um pico estreito ou spike residual dentro da janela.
    return float(np.mean(x[mascara])), float(np.median(y[mascara]))

def calcular_linha_base_por_ancoras(x, y, ancoras_x, meia_janela=5.0):
    """
    Constrói uma baseline linear por trechos através das regiões de ancoragem.
    Também extrapola usando a inclinação dos dois primeiros/últimos pontos.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ancoras = sorted(set(float(v) for v in ancoras_x))
    meia_janela = float(meia_janela)
    if len(ancoras) < 2:
        raise ValueError("At least two baseline anchors are required.")
    if not np.isfinite(meia_janela) or meia_janela < 0:
        raise ValueError("Baseline anchor half-window must be finite and non-negative.")
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 3:
        raise ValueError("Invalid spectrum for baseline calculation.")
    pontos = [_nivel_ancora(x, y, a, meia_janela) for a in ancoras]
    pontos.sort(key=lambda item: item[0])
    xa = np.asarray([p[0] for p in pontos], dtype=float)
    ya = np.asarray([p[1] for p in pontos], dtype=float)
    # Remove X duplicado após aproximação à malha experimental.
    unicos_x = [xa[0]]
    unicos_y = [ya[0]]
    for xv, yv in zip(xa[1:], ya[1:]):
        if abs(float(xv) - float(unicos_x[-1])) <= np.finfo(float).eps:
            unicos_y[-1] = 0.5 * (float(unicos_y[-1]) + float(yv))
        else:
            unicos_x.append(float(xv))
            unicos_y.append(float(yv))
    xa = np.asarray(unicos_x, dtype=float)
    ya = np.asarray(unicos_y, dtype=float)
    if xa.size < 2:
        raise ValueError("Baseline anchors collapse to fewer than two sampled X positions.")
    ordem_x = np.argsort(x)
    xs = x[ordem_x]
    baseline_s = np.interp(xs, xa, ya)
    # Extrapolação linear à esquerda e à direita, em vez de baseline constante.
    dx_esq = xa[1] - xa[0]
    dx_dir = xa[-1] - xa[-2]
    if abs(dx_esq) > np.finfo(float).eps:
        m_esq = (ya[1] - ya[0]) / dx_esq
        mask = xs < xa[0]
        baseline_s[mask] = ya[0] + m_esq * (xs[mask] - xa[0])
    if abs(dx_dir) > np.finfo(float).eps:
        m_dir = (ya[-1] - ya[-2]) / dx_dir
        mask = xs > xa[-1]
        baseline_s[mask] = ya[-1] + m_dir * (xs[mask] - xa[-1])
    baseline = np.empty_like(baseline_s)
    baseline[ordem_x] = baseline_s
    return baseline, xa, ya

def corrigir_linha_base_por_ancoras(f3, ancoras_x, meia_janela=5.0):
    """Aplica a mesma lista de posições X de ancoragem a todos os espectros."""
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    corrigidos = []
    for p in range(len(f3) // 2):
        x = np.asarray(f3[2 * p])
        y = np.asarray(f3[2 * p + 1])
        baseline, _, _ = calcular_linha_base_por_ancoras(
            x, y, ancoras_x, meia_janela
        )
        corrigidos.append(x.copy())
        corrigidos.append(y.astype(np.float64) - baseline)
    return corrigidos

def corrigir_linha_base_automatica(f3, numero_ancoras=12, meia_janela=5.0):
    """
    Detecta regiões de baseline em toda a série e aplica a correção.

    Retorna (dados_corrigidos, ancoras_x) para que a interface possa mostrar
    ao usuário exatamente quais regiões foram escolhidas automaticamente.
    """
    ancoras = detectar_ancoras_baseline_automaticas(
        f3, numero_ancoras=numero_ancoras
    )
    corrigidos = corrigir_linha_base_por_ancoras(
        f3, ancoras, meia_janela=meia_janela
    )
    return corrigidos, ancoras

def normalizar(f3, x_ymin, x_in, x_fi, p2):
    """
    Normalização baseada na rotina fornecida pelo professor.

    Parâmetros preservados do normalizar_v1.py:
      f3     : [x1, y1, x2, y2, ...]
      x_ymin : posição x usada como base (y inferior)
      x_in   : início da faixa onde o pico é procurado
      x_fi   : fim da faixa onde o pico é procurado
      p2     : índice (base 0) do espectro de referência

    A matemática e o dtype são preservados como na rotina do professor.
    Foram acrescentadas apenas validações antes de operações inválidas.
    """
    if len(f3) < 2 or len(f3) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    numero_espectros = len(f3) // 2
    if not 0 <= int(p2) < numero_espectros:
        raise ValueError("Reference spectrum index is out of range.")
    p2 = int(p2)
    xref = 2 * p2
    yref = 2 * p2 + 1
    # Não forçamos float64: o programa do professor lê os dados como
    # float32 e sua rotina trabalha nesse dtype. Preservar isso evita
    # pequenas diferenças numéricas desnecessárias.
    colxref = np.asarray(f3[xref])
    colyref = np.asarray(f3[yref])
    ref_min, ref_max = float(np.min(colxref)), float(np.max(colxref))
    if not ref_min <= float(x_ymin) <= ref_max:
        raise ValueError(
            f"Normalization baseline point {float(x_ymin):g} cm^-1 is outside the reference spectrum range "
            f"({ref_min:g}–{ref_max:g} cm^-1)."
        )
    if not (ref_min <= float(x_in) <= ref_max and ref_min <= float(x_fi) <= ref_max):
        raise ValueError(
            "Normalization peak-range limits must lie inside the reference spectrum."
        )
    idxmref = int(np.argmin(np.abs(colxref - x_ymin)))
    ymnorm = colyref[idxmref]
    idxinref, idxfiref = _indices_faixa(colxref, x_in, x_fi)
    subref = colyref[idxinref:idxfiref + 1]
    if subref.size == 0:
        raise ValueError("The normalization peak range is empty.")
    yMnorm = np.max(subref)
    dif_desj = yMnorm - ymnorm
    if not np.isfinite(dif_desj) or abs(float(dif_desj)) <= np.finfo(float).eps:
        raise ValueError(
            "The reference peak height is zero or too small for normalization."
        )
    f5 = []
    for p in range(numero_espectros):
        x = 2 * p
        y = 2 * p + 1
        colx = np.asarray(f3[x])
        coly = np.asarray(f3[y])
        xmin, xmax = float(np.min(colx)), float(np.max(colx))
        if not xmin <= float(x_ymin) <= xmax:
            raise ValueError(
                f"Normalization baseline point {float(x_ymin):g} cm^-1 is outside spectrum {p + 1}."
            )
        if not (xmin <= float(x_in) <= xmax and xmin <= float(x_fi) <= xmax):
            raise ValueError(
                f"Normalization peak-range limits are outside spectrum {p + 1}."
            )
        idxm = int(np.argmin(np.abs(colx - x_ymin)))
        ymin = coly[idxm]
        idxin, idxfi = _indices_faixa(colx, x_in, x_fi)
        sub = coly[idxin:idxfi + 1]
        if sub.size == 0:
            raise ValueError(
                f"The normalization peak range is empty for spectrum {p + 1}."
            )
        ymax = np.max(sub)
        altura = ymax - ymin
        if not np.isfinite(altura) or abs(float(altura)) <= np.finfo(float).eps:
            raise ValueError(
                f"Spectrum {p + 1} has zero or too-small peak height "
                "in the selected normalization range."
            )
        # Mesmas operações da rotina original.
        fm = dif_desj / altura
        coly2 = coly * fm
        delta = coly2[idxm] - coly[idxm]
        coly2 += -delta
        f5.append(colx)
        f5.append(coly2)
    return f5

def distribuir(f6, xbase, delta):
    """
    Função de distribuição fornecida pelo professor.

    O primeiro espectro é a referência.
    Todos os demais são alinhados em xbase e depois deslocados
    verticalmente por múltiplos inteiros de delta.

    A função mantém o comportamento original e altera os vetores y
    recebidos; por isso a interface sempre passa uma cópia dos dados.
    """
    if len(f6) < 2 or len(f6) % 2 != 0:
        raise ValueError("Invalid Multi-Spectra data structure.")
    xbase = float(xbase)
    delta = float(delta)
    if not np.isfinite(xbase) or not np.isfinite(delta):
        raise ValueError("Distribution reference X and vertical offset must be finite.")
    comum_min, comum_max = faixa_comum_multiespectros(f6)
    if not comum_min <= xbase <= comum_max:
        raise ValueError(
            f"Distribution Reference X = {xbase:g} cm^-1 is outside the common Raman range "
            f"({comum_min:g}–{comum_max:g} cm^-1). Use 'Pick X on Plot' or enter a valid value."
        )
    colxref = f6[0]
    idxmref = np.argmin(
        np.abs(colxref - xbase)
    )
    ybase = f6[1][idxmref]
    final = int(
        len(f6) / 2 - 1
    )
    for p in range(0, final + 1):
        x = 2 * p
        y = 2 * p + 1
        if p > 0:
            colxref2 = f6[x]
            idxmref2 = np.argmin(
                np.abs(colxref2 - xbase)
            )
            dif = (
                f6[y][idxmref2]
                - ybase
            )
            f6[y] += -dif
            f6[y] += delta * p
    return f6

def visualizar_multiespectros(
    f8,
    caminhos=None,
    titulo="Multi-Spectra"
):
    """
    Visualizador simples mantido para compatibilidade.

    A interface principal atual usa uma janela de processamento
    integrada, mas esta função continua disponível para testes.
    """
    fig3 = plt.figure(
        figsize=(12, 7)
    )
    ax = fig3.add_subplot(111)
    final = int(
        len(f8) / 2 - 1
    )
    for p in range(0, final + 1):
        x = 2 * p
        y = 2 * p + 1
        ax.plot(
            f8[x],
            f8[y]
        )
    ax.set_xlabel(
        r'Raman shift (cm$^{-1}$)'
    )
    ax.set_ylabel(
        'Raman intensity (a.u.)'
    )
    ax.set_title(titulo)
    ax.set_yticks([])
    try:
        fig3.canvas.manager.set_window_title(
            "IMESPEC — Multi-Spectra"
        )
    except Exception:
        pass
    plt.show(block=False)
    return fig3
