# PyInstaller specification. Run from the repository root.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
metadata_files = []
for distribution in ("PySide6", "PySide6_Essentials", "shiboken6", "numpy", "scipy", "matplotlib"):
    metadata_files += copy_metadata(distribution)
a = Analysis(
    [str(root / "IMESPEC.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "assets"), "assets"),
           (str(root / "README.md"), "."),
           (str(root / "docs"), "docs")] + metadata_files,
    hiddenimports=["Imespec1", "imespec_bib1", "imespec_maps", "imespec_analysis", "imespec_theme", "imespec_quality",
                   "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_qtagg",
                   "scipy.optimize", "scipy.special", "imespec_app.peaks", "imespec_app.peak_window", "scipy.signal", "scipy.sparse.linalg", "scipy.io", "mpl_toolkits.mplot3d"],
    hookspath=[], hooksconfig={"matplotlib": {"backends": ["TkAgg", "QtAgg"]}},
    runtime_hooks=[], excludes=["PyQt5", "PyQt6", "PySide2", "IPython", "notebook", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="IMESPEC",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / "assets" / "imespec.ico") if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="IMESPEC")

