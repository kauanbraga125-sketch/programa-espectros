"""Reproduce peak analysis without a graphical session: python -m imespec_app.peak_cli."""

import argparse
from pathlib import Path
from .spectra import read_spectrum
from .peaks import (
    BANDS,
    MODELS,
    analyze_series,
    export_csv,
    export_json,
    export_comparisons_csv,
)


def main():
    p = argparse.ArgumentParser(
        description="Ajustar perfis Raman e exportar centros, áreas e comparações preliminares."
    )
    p.add_argument("inputs", nargs="+", help="TXT/CSV ou pastas contendo TXT.")
    p.add_argument(
        "--output", required=True, help="Prefixo dos arquivos .json e .csv de saída."
    )
    p.add_argument("--model", choices=MODELS, default="lorentzian")
    p.add_argument("--baseline-degree", type=int, choices=[0, 1, 2], default=1)
    p.add_argument("--bootstrap", type=int, default=0)
    p.add_argument("--band", choices=["all", "C", "2C", "3C", "4C"], default="all")
    p.add_argument("--ordinary-least-squares", action="store_true")
    a = p.parse_args()
    paths = []
    for name in a.inputs:
        f = Path(name)
        paths.extend(sorted(f.glob("*.txt")) if f.is_dir() else [f])
    spectra = [read_spectrum(f) for f in paths]

    def progress(i, n, name, band):
        if i % 5 == 0 or i == n:
            print(f"{i}/{n} - {name} - {band}", flush=True)

    report = analyze_series(
        spectra,
        tuple(b for b in BANDS if a.band in ("all", b.key)),
        model=a.model,
        baseline_degree=a.baseline_degree,
        robust=not a.ordinary_least_squares,
        bootstrap=a.bootstrap,
        progress=progress,
    )
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    export_json(str(output) + ".json", report)
    export_csv(str(output) + ".csv", report)
    export_comparisons_csv(str(output) + "_sobretons.csv", report)
    print(
        f"{report['completed_fits']} ajustes; {sum(r['usable'] for r in report['fits'])} sem sinalização numérica. Atribuições físicas requerem revisão."
    )


if __name__ == "__main__":
    main()
