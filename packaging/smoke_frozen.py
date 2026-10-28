"""Exercise both packaged GUI toolkits; fail on a crash or startup timeout."""

from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
exe = root / "dist" / "IMESPEC" / ("IMESPEC.exe" if os.name == "nt" else "IMESPEC")
environment = os.environ.copy()
environment["QT_QPA_PLATFORM"] = "offscreen"
for args in (["--smoke-test"], ["--raman-map", "--smoke-test"]):
    result = subprocess.run([str(exe), *args], env=environment, timeout=60)
    if result.returncode:
        raise SystemExit(f"Packaged startup failed: {args}; code={result.returncode}")
print("Both packaged workspaces started successfully.")
