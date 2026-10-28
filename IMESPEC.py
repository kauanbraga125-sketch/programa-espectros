"""One entry point for source, Windows executable and the retained map module."""

import os
from pathlib import Path
import runpy
import sys


def main():
    if "--raman-map" in sys.argv:
        os.environ["IMESPEC_LEGACY_CHILD"] = "1"
        import matplotlib

        matplotlib.use("TkAgg", force=True)
        runpy.run_module("Imespec1", run_name="__main__")
        return 0
    from imespec_app.window import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
