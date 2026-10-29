"""Peak models, bounded fitting and overtone comparisons; no GUI or file mutation.

Centres/widths use cm^-1, areas a.u.*cm^-1. Uncertainty is conditional on
model/noise assumptions, not a calibration or a physical band assignment.
"""

from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib
import json
import math

import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import median_filter
from scipy.special import erf

MODELS = ("lorentzian", "gaussian", "pseudo_voigt")


@dataclass(frozen=True)
class Peak:
    label: str
    center: float
    center_min: float
    center_max: float
    fwhm: float
    width_min: float = 2.0
    width_max: float = 100.0


@dataclass(frozen=True)
class Band:
    key: str
    label: str
    order: int
    start: float
    stop: float
    peaks: tuple
    primary: int = -1
    tentative: bool = False

    def single(self):
        return replace(self, peaks=(self.peaks[self.primary],), primary=0)


BANDS = (
    Band(
        "C",
        "Fundamental CLC",
        1,
        1780.0,
        1940.0,
        (
            Peak("Ombro", 1835.0, 1805.0, 1850.0, 20.0, 2.0, 65.0),
            Peak("CLC principal", 1865.0, 1850.0, 1890.0, 13.0, 2.0, 65.0),
        ),
    ),
    Band(
        "2C",
        "Primeiro sobretom",
        2,
        3570.0,
        3830.0,
        (Peak("2C", 3705.0, 3650.0, 3760.0, 22.0, 3.0, 110.0),),
    ),
    Band(
        "3C",
        "Segundo sobretom",
        3,
        5460.0,
        5590.0,
        (Peak("3C", 5515.0, 5480.0, 5550.0, 38.0, 8.0, 110.0),),
    ),
    Band(
        "4C",
        "Candidato a terceiro sobretom",
        4,
        7228.0,
        7325.0,
        (Peak("4C candidato", 7275.0, 7240.0, 7310.0, 35.0, 8.0, 100.0),),
        tentative=True,
    ),
)


def profile(x, area, center, fwhm, model="lorentzian", fraction=0.5):
    """Unit-area definitions; pseudo-Voigt components share their FWHM."""
    x = np.asarray(x, dtype=float)
    if fwhm <= 0 or model not in MODELS or not 0 <= fraction <= 1:
        raise ValueError("Perfil, largura ou fração inválidos.")
    z = (x - center) / fwhm
    lorentz = area / (np.pi * fwhm / 2) / (1 + 4 * z * z)
    if model == "lorentzian":
        return lorentz
    gauss = (
        area
        * 2
        * np.sqrt(np.log(2))
        / (fwhm * np.sqrt(np.pi))
        * np.exp(-4 * np.log(2) * z * z)
    )
    return gauss if model == "gaussian" else (1 - fraction) * gauss + fraction * lorentz


def window_area(area, center, fwhm, low, high, model, fraction=0.5):
    lo, hi = sorted((float(low), float(high)))
    l = (
        np.arctan(2 * (hi - center) / fwhm) - np.arctan(2 * (lo - center) / fwhm)
    ) / np.pi
    g = 0.5 * (
        erf(2 * np.sqrt(np.log(2)) * (hi - center) / fwhm)
        - erf(2 * np.sqrt(np.log(2)) * (lo - center) / fwhm)
    )
    return float(
        area
        * (
            l
            if model == "lorentzian"
            else g if model == "gaussian" else (1 - fraction) * g + fraction * l
        )
    )


def noise_estimate(y):
    d = np.diff(np.asarray(y, dtype=float))
    if not len(d):
        return 1.0
    value = float(
        np.median(np.abs(d - np.median(d))) / (0.6744897501960817 * np.sqrt(2))
    )
    return max(value, float(np.ptp(y)) * 1e-8, np.finfo(float).eps)


def fit_band(
    x,
    y,
    band,
    *,
    model="lorentzian",
    baseline_degree=1,
    robust=True,
    bootstrap=0,
    seed=12345,
    cancelled=None
):
    """Fit all measured points in a covered interval, preserving input arrays.

    soft_l1 reduces the influence of large residuals; it does not delete or
    repair samples. A numerical fit does not identify a physical vibration.
    """
    if model not in MODELS or baseline_degree not in (0, 1, 2):
        raise ValueError("Modelo ou grau do fundo inválido.")
    if bootstrap < 0 or bootstrap > 1000:
        raise ValueError("Reamostragens: 0 a 1000.")
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (
        x.ndim != 1
        or y.shape != x.shape
        or len(x) < 12
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("Espectro precisa de pares X,Y finitos.")
    dx = np.diff(x)
    if not (np.all(dx > 0) or np.all(dx < 0)):
        raise ValueError("Eixo Raman deve ser estritamente monotônico.")
    if dx[0] < 0:
        x, y = x[::-1], y[::-1]
    if not band.start < band.stop or x[0] > band.start or x[-1] < band.stop:
        raise ValueError("Espectro não cobre todo o intervalo configurado.")
    mask = (x >= band.start) & (x <= band.stop)
    xx, yy = x[mask].copy(), y[mask].copy()
    step = float(np.median(np.diff(xx)))
    span = band.stop - band.start
    ref = (band.start + band.stop) / 2
    scale = max(
        float(np.percentile(yy, 95) - np.percentile(yy, 5)), noise_estimate(yy), 1e-8
    )
    u = (xx - ref) / span
    v = yy / scale
    noise = noise_estimate(yy)
    nbg = baseline_degree + 1
    stride = 4 if model == "pseudo_voigt" else 3
    nparams = nbg + len(band.peaks) * stride
    if len(xx) <= nparams + 5:
        raise ValueError("Poucas amostras para o modelo solicitado.")
    edges = np.r_[
        np.arange(max(3, len(xx) // 10)),
        np.arange(len(xx) - max(3, len(xx) // 10), len(xx)),
    ]
    bg0 = np.polynomial.polynomial.polyfit(u[edges], v[edges], baseline_degree)
    q0 = list(bg0)
    lower = [-np.inf] * nbg
    upper = [np.inf] * nbg
    smooth = median_filter(
        v, size=5, mode="nearest"
    )  # initial guess only, never fitted data
    for pk in band.peaks:
        if not (band.start <= pk.center_min < pk.center < pk.center_max <= band.stop):
            raise ValueError("Limites do centro precisam estar dentro da janela.")
        wmin = max(pk.width_min, 2.5 * step)
        wmax = min(pk.width_max, span)
        if not 0 < wmin < wmax:
            raise ValueError("Limites da largura inválidos ou janela subamostrada.")
        j = int(np.argmin(np.abs(xx - pk.center)))
        height = max(
            float(smooth[j] - np.polynomial.polynomial.polyval(u[j], bg0)), 0.03
        )
        width = float(np.clip(pk.fwhm, wmin * 1.01, wmax * 0.99)) / span
        area = height * width * np.pi / 2
        q0.extend((area, (pk.center - ref) / span, width))
        lower.extend((0, (pk.center_min - ref) / span, wmin / span))
        upper.extend((np.inf, (pk.center_max - ref) / span, wmax / span))
        if stride == 4:
            q0.append(0.5)
            lower.append(0)
            upper.append(1)
    q0 = np.array(q0)
    lower = np.array(lower)
    upper = np.array(upper)

    def evaluate(q):
        value = np.polynomial.polynomial.polyval(u, q[:nbg])
        for k in range(len(band.peaks)):
            j = nbg + k * stride
            value = value + profile(
                u, q[j], q[j + 1], q[j + 2], model, q[j + 3] if stride == 4 else 0.5
            )
        return value

    def solve(obs, initial):
        if cancelled and cancelled():
            raise InterruptedError("Análise cancelada.")
        return least_squares(
            lambda q: evaluate(q) - obs,
            initial,
            bounds=(lower, upper),
            x_scale="jac",
            loss="soft_l1" if robust else "linear",
            f_scale=noise / scale,
            max_nfev=1400,
            ftol=1e-9,
            xtol=1e-9,
            gtol=1e-9,
        )

    opt = solve(v, q0)
    q = opt.x
    fitted = evaluate(q) * scale
    residual = yy - fitted
    dof = len(xx) - len(q)
    # Approximate local covariance (conditional on model/noise), not calibration accuracy.
    cov = np.linalg.pinv(opt.jac.T @ opt.jac, rcond=1e-12) * max(
        (noise / scale) ** 2,
        float(np.median((opt.fun - np.median(opt.fun)) ** 2)) / 0.4549364231195727,
    )
    err = np.sqrt(np.maximum(0, np.diag(cov)))
    samples = []
    if bootstrap:
        rng = np.random.default_rng(seed)
        centred = residual - np.median(residual)
        for _ in range(bootstrap):
            try:
                obs = (
                    fitted + rng.choice(centred, size=len(centred), replace=True)
                ) / scale
                trial = solve(obs, q)
                if trial.success and np.isfinite(trial.x).all():
                    samples.append(trial.x)
            except InterruptedError:
                raise
            except (ValueError, RuntimeError, np.linalg.LinAlgError):
                pass
        if len(samples) >= max(10, int(0.7 * bootstrap)):
            err = np.std(np.array(samples), axis=0, ddof=1)
    flags = []
    if not opt.success:
        flags.append("não convergiu")
    if np.linalg.matrix_rank(opt.jac) < len(q):
        flags.append("parâmetros não identificáveis")
    if bootstrap and len(samples) < max(10, int(0.7 * bootstrap)):
        flags.append("reamostragem insuficiente")
    components = []
    primary = band.primary % len(band.peaks)
    for k, pk in enumerate(band.peaks):
        j = nbg + k * stride
        area = float(q[j] * scale * span)
        center = float(ref + q[j + 1] * span)
        width = float(q[j + 2] * span)
        fraction = (
            float(q[j + 3]) if stride == 4 else (1.0 if model == "lorentzian" else 0.0)
        )
        height = float(
            profile(np.array([center]), area, center, width, model, fraction)[0]
        )
        snr = height / noise
        c = {
            "label": pk.label,
            "center_cm1": center,
            "center_se_cm1": float(err[j + 1] * span),
            "fwhm_cm1": width,
            "fwhm_se_cm1": float(err[j + 2] * span),
            "area_model_au_cm1": area,
            "area_se_au_cm1": float(err[j] * scale * span),
            "area_window_au_cm1": window_area(
                area, center, width, band.start, band.stop, model, fraction
            ),
            "fraction_lorentzian": fraction,
            "height_au": height,
            "height_to_noise": snr,
        }
        components.append(c)
        if k == primary:
            if snr < 3:
                flags.append("sinal fraco (altura/ruído < 3)")
            if min(center - pk.center_min, pk.center_max - center) < max(
                step, 0.01 * (pk.center_max - pk.center_min)
            ):
                flags.append("centro no limite")
            if min(q[j + 2] - lower[j + 2], upper[j + 2] - q[j + 2]) < 0.015 * (
                upper[j + 2] - lower[j + 2]
            ):
                flags.append("largura no limite")
            if not math.isfinite(c["center_se_cm1"]) or c["center_se_cm1"] > width / 3:
                flags.append("centro pouco determinado")
    residual_scale = float(
        np.median(np.abs(residual - np.median(residual))) / 0.6744897501960817
    )
    if residual_scale > 3 * noise:
        flags.append("resíduo acima do ruído estimado")
    background = np.polynomial.polynomial.polyval(u, q[:nbg]) * scale
    return {
        "band": asdict(band),
        "model": model,
        "baseline_degree": baseline_degree,
        "robust_loss": "soft_l1" if robust else "linear",
        "success": bool(opt.success),
        "usable": not flags,
        "review_reasons": flags,
        "physical_assignment_confirmed": False,
        "primary_index": primary,
        "components": components,
        "noise_au": noise,
        "residual_scale_au": residual_scale,
        "uncertainty_method": (
            "residual_bootstrap_iid_conditional"
            if len(samples) >= 10
            else "local_covariance_approximate_conditional"
        ),
        "bootstrap_requested": bootstrap,
        "bootstrap_successful": len(samples),
        "uncertainty_excludes_calibration_and_model_systematics": True,
        "points": len(xx),
        "dof": dof,
        "x": xx.tolist(),
        "observed": yy.tolist(),
        "model_y": fitted.tolist(),
        "background": background.tolist(),
        "residual": residual.tolist(),
        "input_fingerprint": hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest(),
    }


def primary(result):
    return result["components"][result["primary_index"]]


def relative_shift(fundamental, current, previous=None):
    """Lechner et al.: [nu1 - (nu_n - nu_(n-1))]/nu1, in percent.

    n=2 uses previous=fundamental. Statistical error assumes independent fits;
    common calibration errors and uncertain assignments are not accounted for.
    """
    order = current["band"]["order"]
    if order < 2 or order > 4:
        raise ValueError("Ordem do sobretom deve ser 2, 3 ou 4.")
    if fundamental["band"]["order"] != 1:
        raise ValueError("A referência precisa ser o fundamental.")
    prev = fundamental if order == 2 else previous
    if prev is None:
        raise ValueError("Falta o centro da ordem anterior.")
    if prev["band"]["order"] != order - 1:
        raise ValueError("A ordem anterior não corresponde ao sobretom.")
    if not all(r["usable"] for r in (fundamental, current, prev)):
        raise ValueError("Há ajuste que exige revisão.")
    if any(r["band"]["tentative"] for r in (current, prev)):
        raise ValueError(
            "Atribuição candidata: comparação física não liberada automaticamente."
        )
    a, b, c = primary(fundamental), primary(current), primary(prev)
    f, n, p = a["center_cm1"], b["center_cm1"], c["center_cm1"]
    value = 100 * (1 - (n - p) / f)
    variance = (
        ((n / f**2) * a["center_se_cm1"]) ** 2 + (b["center_se_cm1"] / f) ** 2
        if order == 2
        else (((n - p) / f**2) * a["center_se_cm1"]) ** 2
        + (b["center_se_cm1"] ** 2 + c["center_se_cm1"] ** 2) / f**2
    )
    return {
        "order": order,
        "relative_redshift_percent": value,
        "statistical_se_percent": 100 * math.sqrt(variance),
        "definition": "100 * (nu1 - (nu_n - nu_(n-1))) / nu1",
        "independent_fits_assumed": True,
        "physical_assignment_requires_review": True,
    }


def area_ratio(numerator, denominator, numerator_factor=1.0, denominator_factor=1.0):
    """Uncorrected exported-signal ratio unless explicit factors are supplied."""
    if not numerator["usable"] or not denominator["usable"]:
        raise ValueError("Revise os ajustes antes de calcular razões.")
    if not all(
        np.isfinite(v) and v > 0 for v in (numerator_factor, denominator_factor)
    ):
        raise ValueError("Fatores devem ser positivos e finitos.")
    a, b = primary(numerator), primary(denominator)
    av = a["area_model_au_cm1"] / numerator_factor
    bv = b["area_model_au_cm1"] / denominator_factor
    if bv <= 0:
        raise ValueError("Área de referência não positiva.")
    ratio = av / bv
    se = math.sqrt(
        (a["area_se_au_cm1"] / numerator_factor / bv) ** 2
        + (av * b["area_se_au_cm1"] / denominator_factor / bv**2) ** 2
    )
    return {
        "ratio": ratio,
        "statistical_se": se,
        "unit": "dimensionless",
        "area_definition": "integral of fitted primary profile over infinite domain",
        "numerator_factor": numerator_factor,
        "denominator_factor": denominator_factor,
        "instrumental_response_corrected": False,
        "interpretation": "Razão dos sinais exportados; fatores e resposta instrumental precisam de revisão.",
    }


def export_json(path, report):
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def analyze_series(
    spectra,
    bands=BANDS,
    *,
    model="lorentzian",
    baseline_degree=1,
    robust=True,
    bootstrap=0,
    progress=None,
    cancelled=None,
    area_factors=None
):
    """Analyze covered windows only, without joining unknown or ambiguous acquisitions."""
    import re
    from . import __version__

    area_factors = {int(k): float(v) for k, v in (area_factors or {}).items()}
    if any(not math.isfinite(v) or v <= 0 for v in area_factors.values()):
        raise ValueError("Divisores de área precisam ser positivos e finitos.")
    jobs = [
        (s, b)
        for s in spectra
        for b in bands
        if min(s.x) <= b.start and max(s.x) >= b.stop
    ]
    fits = []
    failures = []
    for index, (s, b) in enumerate(jobs):
        if cancelled and cancelled():
            break
        try:
            result = fit_band(
                s.x,
                s.y,
                b,
                model=model,
                baseline_degree=baseline_degree,
                robust=robust,
                bootstrap=bootstrap,
                seed=int(s.fingerprint[:8], 16),
                cancelled=cancelled,
            )
            result.update(
                source_name=s.name,
                source_uid=s.uid,
                source_fingerprint=s.fingerprint,
                temperature_K=s.temperature,
                return_label="volta" in s.name.casefold(),
                match_key=re.sub(r"_[ABCD]_", "_WINDOW_", Path(s.name).stem),
            )
            fits.append(result)
        except InterruptedError:
            break
        except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
            failures.append({"source_name": s.name, "band": b.key, "reason": str(exc)})
        if progress:
            progress(index + 1, len(jobs), s.name, b.label)
    comparisons = []
    keys = sorted(set(r["match_key"] for r in fits))
    for key in keys:
        rows = [r for r in fits if r["match_key"] == key]
        orders = {n: [r for r in rows if r["band"]["order"] == n] for n in range(1, 5)}
        for order in (2, 3, 4):
            if not orders[order] or not orders[1]:
                continue
            item = {
                "match_key": key,
                "order": order,
                "temperature_K": rows[0]["temperature_K"],
                "return_label": rows[0]["return_label"],
                "status": "revisar",
                "relative_shift": None,
                "area_ratio": None,
            }
            required = {1, order, order - 1}
            if any(len(orders[n]) != 1 for n in required):
                item["reason"] = "Correspondência ausente ou ambígua entre ordens."
            elif any(orders[n][0]["temperature_K"] is None for n in required):
                item["reason"] = (
                    "Temperatura não informada: confira a correspondência das aquisições."
                )
            elif (
                len(
                    {
                        (orders[n][0]["temperature_K"], orders[n][0]["return_label"])
                        for n in required
                    }
                )
                != 1
            ):
                item["reason"] = (
                    "Temperaturas ou ciclos diferentes: a correspondência precisa de revisão."
                )
            else:
                fund, current = orders[1][0], orders[order][0]
                prev = orders[order - 1][0]
                item["source_names"] = [
                    fund["source_name"],
                    current["source_name"],
                    prev["source_name"],
                ]
                try:
                    item["relative_shift"] = relative_shift(fund, current, prev)
                    item["area_ratio"] = area_ratio(
                        current,
                        fund,
                        area_factors.get(order, 1.0),
                        area_factors.get(1, 1.0),
                    )
                    item["status"] = "preliminar"
                    item["reason"] = (
                        "Correspondência por nome e temperatura; atribuição e resposta instrumental exigem revisão."
                    )
                except ValueError as exc:
                    item["reason"] = str(exc)
            comparisons.append(item)
    return {
        "format": "imespec-peak-analysis",
        "format_version": 1,
        "application_version": __version__,
        "settings": {
            "model": model,
            "baseline_degree": baseline_degree,
            "robust": robust,
            "bootstrap": bootstrap,
            "bands": [asdict(b) for b in bands],
            "area_factors": area_factors,
        },
        "source_count": len(spectra),
        "covered_jobs": len(jobs),
        "completed_fits": len(fits),
        "cancelled": bool(cancelled and cancelled()),
        "fits": fits,
        "failures": failures,
        "comparisons": comparisons,
        "interpretation": "Ajustes não confirmam atribuições. Erros estatísticos condicionais não incluem calibração, modelo ou resposta instrumental.",
    }


def export_csv(path, report):
    import csv

    fields = [
        "source_name",
        "temperature_K",
        "return_label",
        "band",
        "component",
        "model",
        "center_cm1",
        "center_se_cm1",
        "fwhm_cm1",
        "fwhm_se_cm1",
        "area_model_au_cm1",
        "area_se_au_cm1",
        "area_window_au_cm1",
        "height_to_noise",
        "usable",
        "review_reasons",
        "uncertainty_method",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for r in report["fits"]:
            c = primary(r)
            writer.writerow(
                {
                    **{k: c[k] for k in fields if k in c},
                    "source_name": r["source_name"],
                    "temperature_K": r["temperature_K"],
                    "return_label": r["return_label"],
                    "band": r["band"]["key"],
                    "component": c["label"],
                    "model": r["model"],
                    "usable": r["usable"],
                    "review_reasons": "; ".join(r["review_reasons"]),
                    "uncertainty_method": r["uncertainty_method"],
                }
            )


def export_comparisons_csv(path, report):
    import csv

    fields = [
        "temperature_K",
        "return_label",
        "order",
        "status",
        "relative_redshift_percent",
        "statistical_se_percent",
        "area_ratio",
        "area_ratio_statistical_se",
        "reason",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for r in report["comparisons"]:
            d = {k: r[k] for k in fields if k in r}
            if r["relative_shift"]:
                d.update(
                    {
                        k: r["relative_shift"][k]
                        for k in ("relative_redshift_percent", "statistical_se_percent")
                    }
                )
            if r["area_ratio"]:
                d.update(
                    area_ratio=r["area_ratio"]["ratio"],
                    area_ratio_statistical_se=r["area_ratio"]["statistical_se"],
                )
            writer.writerow(d)
